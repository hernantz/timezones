from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

import pytz

_TZ_TO_COUNTRY: dict[str, str] = {}
for _cc, _zones in pytz.country_timezones.items():
    _country = pytz.country_names.get(_cc, _cc)
    for _z in _zones:
        _TZ_TO_COUNTRY[_z] = _country


@lru_cache(maxsize=None)
def all_timezone_ids() -> list[str]:
    return sorted(z for z in available_timezones() if "/" in z and not z.startswith("Etc/"))


def city_name(tz_id: str) -> str:
    return tz_id.rsplit("/", 1)[-1].replace("_", " ")


def country_name(tz_id: str) -> str:
    return _TZ_TO_COUNTRY.get(tz_id, tz_id.split("/", 1)[0].replace("_", " "))


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


def is_daylight_hour(local_hour: int) -> bool:
    """Fixed 6am-6pm heuristic. TODO: replace with real sunrise/sunset lookup per city/date."""
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
