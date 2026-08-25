from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from math import asin, atan2, cos, degrees, radians, sin
from pathlib import Path
from zoneinfo import TZPATH, ZoneInfo

# Signed degrees and minutes, optionally seconds, as zone.tab writes a position:
# +DDMM+DDDMM or +DDMMSS+DDDMMSS, latitude then longitude, no separator.
_ISO6709 = re.compile(r"([+-]\d{2})(\d{2})(\d{2})?([+-]\d{3})(\d{2})(\d{2})?")

# ---- The zone list, and the country each zone belongs to --------------------
#
# zoneinfo reads TZif binaries, which hold transitions, offsets and
# abbreviations and nothing else — no country, no coordinates. Those live in the
# plain-text tables the IANA distribution ships beside the compiled zones:
# zone.tab maps each zone to the ISO 3166 code of the country keeping it, and
# iso3166.tab spells those codes out. pytz read the very same two files; its
# only advantage was doing the open() for us.
#
# Both are taken as present: Fedora's tzdata and the GNOME and freedesktop
# flatpak runtimes all ship them, and those are the ways this app is installed.


def _read_table(*names: str) -> list[list[str]]:
    """Rows of the first of `names` found on TZPATH, split into fields.

    TZPATH rather than a hardcoded /usr/share/zoneinfo, so the tables are always
    read from the same database zoneinfo resolves the zones themselves through.

    Both tables share a format — tab-separated, lines beginning with '#' are
    comments — and both end in a free-text column that may itself contain a '#',
    so only whole-line comments are dropped.
    """
    for name in names:
        for root in TZPATH:
            path = Path(root, name)
            if path.is_file():
                return [
                    line.split("\t")
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line and not line.startswith("#")
                ]
    return []


@lru_cache(maxsize=None)
def _tz_to_country() -> dict[str, str]:
    """Every zone the app offers as a city, mapped to the country keeping it."""
    countries = {row[0]: row[1] for row in _read_table("iso3166.tab") if len(row) >= 2}

    # zone1970.tab is the maintained table, but it omits every zone that has
    # agreed with another since 1970 — Europe/Vatican, Africa/Accra and a couple
    # hundred more cities someone may well search for. zone.tab is marked
    # deprecated and still lists them all, so prefer it and fall back. Reading
    # the country column as a comma-separated list accepts either shape:
    # zone1970.tab names every country sharing a zone, most significant first,
    # and zone.tab's lone code parses as a list of one.
    table: dict[str, str] = {}
    for row in _read_table("zone.tab", "zone1970.tab"):
        if len(row) < 3:
            continue
        code, tz_id = row[0].split(",")[0], row[2]
        table.setdefault(tz_id, countries.get(code, code))

    # UTC is not a place, so zone.tab does not list it — but a world clock
    # without a UTC row is missing the zone a good share of its users actually
    # work in. Added by hand rather than by admitting the whole Etc/ family,
    # whose GMT±N members invert their sign (Etc/GMT+5 resolves to UTC−5) and
    # would misread badly in a column of offsets. The name spelled out keeps the
    # subtitle from reading "UTC · UTC · UTC+0h".
    table.setdefault("UTC", "Coordinated Universal Time")
    return table


@lru_cache(maxsize=None)
def _tz_to_coords() -> dict[str, tuple[float, float]]:
    """Each zone's principal city, as (latitude, longitude) in degrees.

    zone.tab carries the coordinates in the column beside the country code, in
    ISO 6709: a signed degrees-and-minutes pair, optionally with seconds — 363
    zones written +DDMM+DDDMM and the other 55 +DDMMSS+DDDMMSS. They locate the
    city the zone is named for, which is the city the row is labelled with, so
    the sun they imply is the sun over the place the row claims to be.
    """
    coords: dict[str, tuple[float, float]] = {}
    for row in _read_table("zone.tab", "zone1970.tab"):
        if len(row) < 3:
            continue
        match = _ISO6709.fullmatch(row[1])
        if match is None:
            continue
        lat_d, lat_m, lat_s, lon_d, lon_m, lon_s = match.groups()
        coords.setdefault(
            row[2], (_decimal_degrees(lat_d, lat_m, lat_s), _decimal_degrees(lon_d, lon_m, lon_s))
        )
    return coords


def _decimal_degrees(degree: str, minute: str, second: str | None) -> float:
    """A signed ISO 6709 degree/minute/second triple as decimal degrees.

    The sign belongs to the angle as a whole, not to its degrees alone, so it is
    applied after the minutes and seconds are added on — negating first would
    put every southern and western coordinate on the wrong side of its degree.
    """
    magnitude = abs(int(degree)) + int(minute) / 60 + int(second or 0) / 3600
    return -magnitude if degree.startswith("-") else magnitude


@lru_cache(maxsize=None)
def all_timezone_ids() -> list[str]:
    """Every zone offered as a city, sorted.

    The table lists *places*, so unlike zoneinfo.available_timezones() it never
    yields UTC, MST7MDT or Etc/GMT+5 — offsets wearing a zone's clothes, with no
    city behind them and a sign convention backwards from what the name reads
    like — nor the backward-compatibility aliases (America/Buenos_Aires,
    Africa/Asmera) that would otherwise sit in the list beside the canonical
    name of the same city. Nothing has to be filtered back out.
    """
    return sorted(_tz_to_country())


def is_known_timezone(tz_id: str) -> bool:
    return tz_id in _tz_to_country()


def city_name(tz_id: str) -> str:
    return tz_id.rsplit("/", 1)[-1].replace("_", " ")


def country_name(tz_id: str) -> str:
    return _tz_to_country().get(tz_id, tz_id.split("/", 1)[0].replace("_", " "))


def abbreviation(tz_id: str, at: datetime | None = None) -> str:
    at = at or datetime.now().astimezone()
    return at.astimezone(ZoneInfo(tz_id)).tzname() or ""


def utc_offset(tz_id: str, at: datetime | None = None) -> timedelta:
    """The zone's offset from UTC *at that instant*.

    There is no such thing as a timezone's offset in the abstract — a zone that
    observes DST has (at least) two, and which one applies is a fact about the
    moment, not about the city. Every offset in the app is resolved through
    here against a real instant, so it comes from the IANA rules rather than
    from anything remembered per city.
    """
    at = at or datetime.now().astimezone()
    return at.astimezone(ZoneInfo(tz_id)).utcoffset() or timedelta()


def utc_offset_hours(tz_id: str, at: datetime | None = None) -> float:
    return utc_offset(tz_id, at).total_seconds() / 3600.0


def local_now(tz_id: str, at: datetime | None = None) -> datetime:
    at = at or datetime.now().astimezone()
    return at.astimezone(ZoneInfo(tz_id))


# ---- Daylight ---------------------------------------------------------------

# Sunrise and sunset are conventionally the moments the sun's *upper limb* meets
# the horizon, which the sun's own radius and average atmospheric refraction put
# 0.833 degrees below the geometric one.
_HORIZON_DEGREES = -0.833


def solar_elevation(latitude: float, longitude: float, at: datetime) -> float:
    """The sun's angle above the horizon, in degrees, at that place and instant.

    The low-precision NOAA solar position algorithm, good to roughly a minute of
    time this century — against hour-wide cells, which ask far less of it.

    Asking for the angle at an instant, rather than for the day's sunrise and
    sunset, is what keeps this honest inside the polar circles. There, days
    occur with no sunrise to compute, and every formulation solving for one has
    to special-case the moment its acos() leaves the domain. An angle always
    exists: in Longyearbyen in December it is simply negative all day long, and
    the strip shades every cell dark without being told about polar night.
    """
    # Days since J2000.0. The Unix epoch is JD 2440587.5, and `at` names an
    # instant, so this is UTC however the caller happened to build the datetime.
    n = at.timestamp() / 86400.0 + 2440587.5 - 2451545.0

    mean_longitude = radians((280.460 + 0.9856474 * n) % 360)
    mean_anomaly = radians((357.528 + 0.9856003 * n) % 360)
    ecliptic_longitude = mean_longitude + radians(
        1.915 * sin(mean_anomaly) + 0.020 * sin(2 * mean_anomaly)
    )
    obliquity = radians(23.439 - 0.0000004 * n)

    declination = asin(sin(obliquity) * sin(ecliptic_longitude))
    right_ascension = atan2(cos(obliquity) * sin(ecliptic_longitude), cos(ecliptic_longitude))

    # Greenwich mean sidereal time in hours, turned into degrees and carried
    # east to the meridian of the place, giving the sun's hour angle there.
    hour_angle = radians((18.697374558 + 24.06570982441908 * n) % 24 * 15 + longitude)
    hour_angle -= right_ascension

    lat = radians(latitude)
    return degrees(
        asin(sin(lat) * sin(declination) + cos(lat) * cos(declination) * cos(hour_angle))
    )


def is_daylight(tz_id: str, at: datetime) -> bool:
    """Whether the sun stands above the horizon over `tz_id`'s city, then."""
    coords = _tz_to_coords().get(tz_id)
    if coords is None:
        # UTC is the only zone the app offers that has no coordinates, being a
        # reference rather than a place. Nothing casts a shadow there, so fall
        # back to the clock-face convention.
        return is_daylight_hour(local_now(tz_id, at).hour)
    latitude, longitude = coords
    return solar_elevation(latitude, longitude, at) > _HORIZON_DEGREES


def is_daylight_hour(local_hour: int) -> bool:
    """Fixed 6am-6pm convention, for a zone with no coordinates to do better."""
    return 6 <= (local_hour % 24) < 18


def format_offset(offset_hours: float) -> str:
    if offset_hours == 0:
        return "+0h"
    sign = "+" if offset_hours > 0 else "−"
    magnitude = abs(offset_hours)
    if magnitude == int(magnitude):
        return f"{sign}{int(magnitude)}h"
    return f"{sign}{magnitude:g}h"


# ---- Daylight-saving transitions -------------------------------------------


@dataclass(frozen=True)
class DstTransition:
    """One change of a zone's UTC offset, as the IANA rules define it.

    Three facts pin the whole event down: the instant the new offset takes
    effect, and the offsets either side of it. Everything a user-facing warning
    needs is derived from those — which way the clocks went, by how much, what
    the clock face read when it jumped, and what it read immediately after.
    """

    at: datetime  # the exact instant, UTC-aware
    before: timedelta
    after: timedelta

    @property
    def shift(self) -> timedelta:
        """Negative when clocks go back, positive when they go forward."""
        return self.after - self.before

    def _wall(self, offset: timedelta) -> datetime:
        # Naive on purpose: these are clock *faces*, not instants. Attaching the
        # zone back would make the two readings below compare equal for a
        # fall-back (both are legitimately "that" local time), which is exactly
        # the ambiguity the warning exists to spell out.
        return self.at.astimezone(timezone.utc).replace(tzinfo=None) + offset

    @property
    def switch_wall(self) -> datetime:
        """What the clock read at the moment it jumped — the "at 2:00 AM" every
        DST rule is stated as, and (going forward) the hour that never happens."""
        return self._wall(self.before)

    @property
    def resumed_wall(self) -> datetime:
        """What the clock read immediately after the jump — going back, the hour
        that is about to be lived through a second time."""
        return self._wall(self.after)


def find_transition(tz_id: str, earlier: datetime, later: datetime) -> DstTransition | None:
    """The offset change in `(earlier, later]`, or None if the offset holds.

    Callers hand in the two ends of a single timeline cell, so this only ever
    has to resolve one change; a window wide enough to contain two would find
    the later of them.
    """
    before = utc_offset(tz_id, earlier)
    after = utc_offset(tz_id, later)
    if before == after:
        return None

    # Bisect in UTC over whole minutes. UTC because adding a timedelta to a
    # zone-aware datetime is *wall-clock* arithmetic, which near a transition
    # is the very thing being measured; whole minutes because every transition
    # in the IANA data lands on one, and integer bounds keep each midpoint on
    # the minute grid instead of drifting off it the way halving a timedelta
    # repeatedly would.
    base = earlier.astimezone(timezone.utc)
    low, high = 0, int((later - earlier).total_seconds() // 60)
    while high - low > 1:
        mid = (low + high) // 2
        if utc_offset(tz_id, base + timedelta(minutes=mid)) == before:
            low = mid
        else:
            high = mid

    return DstTransition(at=base + timedelta(minutes=high), before=before, after=after)


def abbreviation_change(tz_id: str, transition: DstTransition) -> tuple[str, str]:
    """The zone's abbreviations either side of `transition`, e.g. ("EDT", "EST")."""
    return (
        abbreviation(tz_id, transition.at - timedelta(seconds=1)),
        abbreviation(tz_id, transition.at),
    )


def describe_transition(city: str, transition: DstTransition, fmt_24h: bool) -> str:
    """The transition stated as a rule, in the same words a person would use.

    The highlighted cell in the strip can only say "something happens here";
    which direction, by how much, and — the part that actually bites when
    scheduling — whether an hour is about to be repeated or skipped, has to be
    written out.
    """
    switch = _format_wall(transition.switch_wall, fmt_24h)
    date = transition.switch_wall.strftime("%b %-d")
    if transition.shift < timedelta():
        direction, tail = "back", f"{_format_wall(transition.resumed_wall, fmt_24h)} occurs twice"
    else:
        direction, tail = "forward", f"{switch} does not occur"
    span = _format_span(abs(transition.shift))
    return f"Clocks in {city} move {direction} {span} at {switch} on {date} — {tail}"


def _format_wall(wall: datetime, fmt_24h: bool) -> str:
    return wall.strftime("%H:%M" if fmt_24h else "%-I:%M %p")


def _format_span(span: timedelta) -> str:
    hours, minutes = divmod(int(span.total_seconds() // 60), 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if minutes:
        parts.append(f"{minutes} minute" + ("s" if minutes != 1 else ""))
    return " ".join(parts)
