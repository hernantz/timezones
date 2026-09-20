"""Handing a parked instant to something outside the app.

Both exports state the *same* instant in every zone on the list rather than
just the reference's reading. The reason to park on an hour at all is that it
has to work for several places at once, so the useful thing to paste into a
chat — or to read back off a calendar entry weeks later — is the whole
comparison, not the one number the banner happens to show.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from gi.repository import Gio, GLib, Gtk

from . import tzinfo_helpers as tzinfo
from .model import City, ClockModel

# How long the calendar event runs. Nothing in the app knows a duration — the
# timeline parks on a start time — so the event is a placeholder the user
# adjusts in their calendar, and half an hour is the meeting that needs the
# least editing when it is wrong.
EVENT_MINUTES = 30


def _row_name(city: City) -> str:
    """"Cairo (Family)" — the city first, the user's own label in brackets.

    The city leads because that is the part a reader outside this app can
    place; the label is what it means to *this* user, which is worth keeping
    but not worth leading with.
    """
    city_name = tzinfo.city_name(city.tz)
    if city.label and city.label.casefold() != city_name.casefold():
        return f"{city_name} ({city.label})"
    return city_name


def _clock(at: datetime, fmt_24h: bool) -> str:
    return at.strftime("%H:%M") if fmt_24h else at.strftime("%-I:%M %p").lstrip()


def zone_lines(model: ClockModel, instant: datetime, fmt_24h: bool) -> list[str]:
    """One line per city, aligned on the time column.

    A row carries its own date only when it differs from the reference's — the
    header already states the day, and repeating it on every line buries the
    one row where the date is the whole point.
    """
    ref = model.reference
    if ref is None:
        return []
    ref_date = tzinfo.local_now(ref.tz, instant).date()

    names = [_row_name(city) for city in model.cities]
    width = max(len(name) for name in names) if names else 0

    lines = []
    for city, name in zip(model.cities, names):
        local = tzinfo.local_now(city.tz, instant)
        text = f"{name.ljust(width)}  {_clock(local, fmt_24h)}"
        if local.date() != ref_date:
            text += f" ({local.strftime('%a, %b %-d')})"
        lines.append(text)
    return lines


def clipboard_text(model: ClockModel, instant: datetime, fmt_24h: bool) -> str:
    ref = model.reference
    if ref is None:
        return ""
    header = tzinfo.local_now(ref.tz, instant).strftime("%a, %b %-d %Y")
    return "\n".join([header, "", *zone_lines(model, instant, fmt_24h)])


def _ics_escape(text: str) -> str:
    # RFC 5545 §3.3.11: backslash first, or it would escape the escapes added
    # after it.
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """RFC 5545 §3.1 line folding, counted in *octets* rather than characters.

    City names are not all ASCII, and a fold placed by character count can land
    in the middle of a multi-byte one, which is how a calendar ends up showing
    a replacement character instead of a São Paulo.
    """
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    chunks, start = [], 0
    while start < len(raw):
        limit = 75 if not chunks else 74  # continuations carry a leading space
        end = min(start + limit, len(raw))
        # Back off to a character boundary: a UTF-8 continuation byte is
        # 0b10xxxxxx, so walk left until the next byte starts a character.
        while end < len(raw) and raw[end] & 0xC0 == 0x80:
            end -= 1
        chunks.append(raw[start:end].decode("utf-8"))
        start = end
    return "\r\n ".join(chunks)


def ics_text(model: ClockModel, instant: datetime, fmt_24h: bool) -> str:
    """A single-event calendar, timed in UTC.

    UTC rather than a VTIMEZONE block with the reference zone's rules: the
    instant is what was picked, every calendar renders a UTC stamp in the
    reader's own zone without needing the rules shipped alongside, and the
    per-zone readings that make this app's version of the answer interesting
    are in the description anyway.
    """
    start = instant.astimezone(timezone.utc)
    end = start + timedelta(minutes=EVENT_MINUTES)
    stamp = datetime.now(timezone.utc)
    fmt = "%Y%m%dT%H%M%SZ"

    ref = model.reference
    summary = "Meeting"
    if ref is not None:
        local = tzinfo.local_now(ref.tz, instant)
        summary = f"Meeting · {_clock(local, fmt_24h)} {tzinfo.city_name(ref.tz)}"

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//hernantz//Timezones//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}@timezones.hernantz.com",
        f"DTSTAMP:{stamp.strftime(fmt)}",
        f"DTSTART:{start.strftime(fmt)}",
        f"DTEND:{end.strftime(fmt)}",
        f"SUMMARY:{_ics_escape(summary)}",
        f"DESCRIPTION:{_ics_escape(chr(10).join(zone_lines(model, instant, fmt_24h)))}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    # CRLF throughout, including the final line: RFC 5545 §3.1 requires it, and
    # the stricter importers reject a file that ends without one.
    return "".join(_fold(line) + "\r\n" for line in lines)


def write_ics(model: ClockModel, instant: datetime, fmt_24h: bool) -> Gio.File:
    """Spill the event to a cache file and return it, ready to be launched.

    The cache directory rather than a temp path: inside the Flatpak sandbox it
    is a real, app-owned location the document portal can export from when the
    file is handed to another application, and it is the directory the system
    is already entitled to clear behind us.
    """
    directory = GLib.build_filenamev([GLib.get_user_cache_dir(), "timezones"])
    GLib.mkdir_with_parents(directory, 0o700)
    # Named for the instant, so repeatedly sharing the same slot reuses one
    # file instead of littering the directory with a UUID per click.
    name = instant.astimezone(timezone.utc).strftime("meeting-%Y%m%dT%H%M.ics")
    path = GLib.build_filenamev([directory, name])
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(ics_text(model, instant, fmt_24h))
    return Gio.File.new_for_path(path)


def launch_ics(parent: Gtk.Window, file: Gio.File, on_error) -> None:
    """Open the file with whatever handles calendar invitations.

    `Gtk.FileLauncher` rather than `Gio.AppInfo`: under Flatpak it routes
    through the OpenURI portal, which exports the file to the chosen
    application on the host without this app needing filesystem access.
    """
    launcher = Gtk.FileLauncher.new(file)

    def finished(source, result):
        try:
            source.launch_finish(result)
        except GLib.Error as error:
            # Dismissing the portal's own chooser is a decision, not a failure.
            if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                on_error(error.message)

    launcher.launch(parent, None, finished)
