"""Translation setup, and every date and clock reading the app shows.

The markers follow GLib's naming, which is what po/meson.build tells xgettext
to look for: `_` for a plain string, `C_` for one that needs a context to be
translated right (a lone "M" is Monday's initial, or a size), `N_` to mark a
module-level constant whose translation has to wait until it is used, and
`ngettext` for anything with a count in it.

Dates go through strftime with the *format itself* translated, so a translator
can reorder "Sep 25" into "25 sept." — the locale supplies the words, the
translation supplies the order. None of this looks anything up until it is
called, which is why `init()` can run from `main()`, after the modules holding
the strings have already been imported.
"""

from __future__ import annotations

import ctypes
import gettext
import locale
from datetime import datetime

DOMAIN = "timezones"

_ = gettext.gettext
C_ = gettext.pgettext
ngettext = gettext.ngettext


def N_(message: str) -> str:
    return message


# Where the installed catalogs live, or None to take gettext's default. The
# launcher knows it (meson substitutes it); a source-tree run leaves it unset.
localedir: str | None = None


def init(path: str | None = None) -> None:
    global localedir
    # GTK also sets the locale when it initialises, but strftime is read from
    # the C library well before any window exists — and without this, "%b"
    # would stay in English in an otherwise translated UI.
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass  # an unsupported LANG: carry on in the C locale rather than crash
    if path:
        localedir = path
    gettext.bindtextdomain(DOMAIN, localedir)
    gettext.textdomain(DOMAIN)


def catalog(domain: str) -> gettext.NullTranslations:
    """Another project's catalog — iso-codes' country names, gweather's cities.

    Looked for beside our own first, since a Flatpak installs the ones it
    bundles under /app rather than /usr, then wherever gettext looks by default.
    """
    for path in (localedir, None):
        found = gettext.find(domain, path)
        if found:
            return gettext.translation(domain, path)
    return gettext.NullTranslations()


# ---- Clock readings ----------------------------------------------------------


def meridiem(at: datetime) -> str:
    """AM or PM, as the locale spells it.

    %p is empty wherever the locale does not use a 12-hour clock — de_DE and
    fr_FR among them — which would leave "1:00" meaning either end of the day.
    Someone who picked the 12-hour format there still needs the half of the day
    spelled out, so the translation steps in.
    """
    text = at.strftime("%p")
    if text:
        return text
    return C_("before noon", "AM") if at.hour < 12 else C_("after noon", "PM")


def twelve_hour(time: str, meridiem: str) -> str:
    """Join a 12-hour reading to its AM/PM, in the order the language puts them.

    Separate from `format_clock` so a caller can dress the two parts up first —
    the row shows the meridiem smaller than the digits.
    """
    # Translators: a 12-hour clock reading. {time} is like "1:30" and
    # {meridiem} is AM or PM; reorder them if your language writes the
    # meridiem first (Korean: "{meridiem} {time}").
    return _("{time} {meridiem}").format(time=time, meridiem=meridiem)


def format_clock(at: datetime, fmt_24h: bool) -> str:
    if fmt_24h:
        return at.strftime("%H:%M")
    return twelve_hour(at.strftime("%-I:%M"), meridiem(at))


# ---- Dates -------------------------------------------------------------------


def format_day(at: datetime) -> str:
    # Translators: strftime format for a day, as in "Fri, Sep 25". Reorder to
    # suit your language; %a is the weekday, %b the month and %-d the day.
    return at.strftime(C_("strftime format", "%a, %b %-d"))


def format_day_year(at: datetime) -> str:
    # Translators: strftime format for a day with its year, as in
    # "Fri, Sep 25 2026". The header of a copied list of times.
    return at.strftime(C_("strftime format", "%a, %b %-d %Y"))


def format_month_day(at: datetime) -> str:
    # Translators: strftime format for a day without the weekday, as in
    # "Mar 29". Used in "Clocks move forward … on Mar 29".
    return at.strftime(C_("strftime format", "%b %-d"))


def format_date_flag(at: datetime) -> str:
    # Translators: strftime format for the small pill marking where a day
    # starts on the timeline, as in "FRI 25". It is shown in capitals.
    return at.strftime(C_("strftime format", "%a %-d")).upper()


def format_month_year(at: datetime) -> str:
    # Translators: strftime format for the calendar's heading, as in
    # "September 2026". %OB is the month's name standing on its own, which
    # differs from %B in languages that inflect it (Russian, Polish, Greek).
    return at.strftime(C_("strftime format", "%OB %Y"))


# ---- The calendar ------------------------------------------------------------

# glibc's nl_langinfo() items for the week, from <langinfo.h>. Python's locale
# module does not expose them, but their values are part of the C library's
# ABI, compiled into every program that asks, so they cannot move.
_NL_TIME_WEEK_1STDAY = 0x20066
_NL_TIME_FIRST_WEEKDAY = 0x20068

# The dates _NL_TIME_WEEK_1STDAY answers with, naming the day its count starts
# from: 30 Nov 1997 was a Sunday, 1 Dec 1997 a Monday.
_WEEK_ORIGINS = {19971130: 6, 19971201: 0}


def first_weekday() -> int:
    """The day the user's locale starts the week on, 0 for Monday to 6 for
    Sunday — the numbering Python's calendar module takes.

    Read the way GtkCalendar reads it: glibc stores a week origin, and the
    first weekday as a 1-based count from that origin. en_US counts 1 from
    Sunday (so Sunday), de_DE 2 from Sunday (Monday), ar_EG 7 (Saturday).
    Monday, what the popover always used, if the C library cannot say.
    """
    try:
        libc = ctypes.CDLL(None)
        libc.nl_langinfo.argtypes = [ctypes.c_int]
        libc.nl_langinfo.restype = ctypes.c_void_p
        # A 32-bit number stored in the pointer itself, not a string it points
        # to; the upper half of a 64-bit pointer is whatever was lying there.
        origin = _WEEK_ORIGINS[(libc.nl_langinfo(_NL_TIME_WEEK_1STDAY) or 0) & 0xFFFFFFFF]
        first = ctypes.string_at(libc.nl_langinfo(_NL_TIME_FIRST_WEEKDAY), 1)[0]
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return 0
    if not 1 <= first <= 7:
        return 0
    return (origin + first - 1) % 7
