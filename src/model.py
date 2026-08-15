from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import available_timezones

from . import tzinfo_helpers as tzinfo

# The strip's width, in cells, for every row — never 23 or 25. A column is one
# *absolute* hour: column C of every row starts at the same real instant, which
# is what lets a reader compare rows by looking straight down. A day that gains
# or loses an hour therefore shows up in the labels (an hour repeated, an hour
# missing) and never in the number of cells.
COLUMNS = 24


@dataclass
class City:
    tz: str
    label: str = ""
    is_reference: bool = False


class ClockModel:
    def __init__(self, cities: list[City]):
        self.cities = cities
        if cities and not any(c.is_reference for c in cities):
            cities[0].is_reference = True

    @staticmethod
    def is_valid_tz(tz: str) -> bool:
        return tz in available_timezones()

    @property
    def reference(self) -> City | None:
        for c in self.cities:
            if c.is_reference:
                return c
        return self.cities[0] if self.cities else None

    def set_reference(self, city: City) -> None:
        for c in self.cities:
            c.is_reference = c is city

    def move_up(self, city: City) -> None:
        i = self.cities.index(city)
        if i > 0:
            self.cities[i - 1], self.cities[i] = self.cities[i], self.cities[i - 1]

    def move_down(self, city: City) -> None:
        i = self.cities.index(city)
        if i < len(self.cities) - 1:
            self.cities[i + 1], self.cities[i] = self.cities[i], self.cities[i + 1]

    def offset_hours(self, city: City, at: datetime | None = None) -> float:
        ref = self.reference
        if ref is None:
            return 0.0
        return tzinfo.utc_offset_hours(city.tz, at) - tzinfo.utc_offset_hours(ref.tz, at)

    def reference_midnight(self, at: datetime | None = None) -> datetime:
        """The instant the reference zone's day begins — the strip's left edge.

        On the one day a year the reference zone springs forward *at* midnight,
        00:00 is a time that never happens there; zoneinfo resolves it with the
        pre-transition offset, so the strip opens on the day's first hour that
        does exist. That is the honest answer, and the only one available.
        """
        at = at or datetime.now().astimezone()
        ref = self.reference
        local = tzinfo.local_now(ref.tz, at) if ref else at
        return local.replace(hour=0, minute=0, second=0, microsecond=0)

    def now_column(self, at: datetime | None = None) -> float:
        at = at or datetime.now().astimezone()
        # Elapsed real time, not `local.hour + minutes` — on a fall-back day the
        # wall clock passes 1:30 twice and the now-line has to keep moving right
        # through the second one instead of jumping back a column.
        return (at - self.reference_midnight(at)).total_seconds() / 3600.0

    def column_instant(self, column: float, at: datetime | None = None) -> datetime:
        """The instant column `column` begins at, as an absolute point in time.

        `column` may be fractional (e.g. a mouse-scrub position between hour
        cells). The step is added in UTC: adding a timedelta to a zone-aware
        datetime is wall-clock arithmetic, which on a DST day would quietly make
        the strip span 23 or 25 real hours and knock every row out of alignment
        with every other.
        """
        base = self.reference_midnight(at).astimezone(timezone.utc)
        return base + timedelta(hours=column)

    def local_hour_at_column(self, city: City, column: int, at: datetime | None = None) -> int:
        """The hour on `city`'s clock face when column `column` begins.

        Read off the real instant rather than shifted by a stored offset, so a
        row that changes offset mid-strip repeats an hour or skips one exactly
        as its clocks do.
        """
        return tzinfo.local_now(city.tz, self.column_instant(column, at)).hour

    def boundary_column(self, city: City, at: datetime | None = None) -> int:
        """The column where `city`'s date rolls over, or 0 if it does so at the
        strip's own left edge.

        Found by walking the strip rather than computed from the offset: 24
        absolute hours contain exactly one midnight, but which column holds it
        depends on the offset *in force at that column*, which a DST day changes
        partway across.
        """
        previous = self.row_current_date(city, self.column_instant(0, at))
        for column in range(1, COLUMNS):
            current = self.row_current_date(city, self.column_instant(column, at))
            if current != previous:
                return column
            previous = current
        return 0

    def row_transitions(
        self, city: City, at: datetime | None = None
    ) -> list[tuple[int, tzinfo.DstTransition]]:
        """Every clock change `city` makes inside the strip, with the column it
        lands in — the cell the strip marks and the warning text describes.

        The column reported is the first one on the *new* side of the change:
        the cell whose label is the repeated hour, or the one the skipped hour
        would have occupied.
        """
        base = self.reference_midnight(at).astimezone(timezone.utc)
        # One extra start at the front, so a change landing exactly on the
        # strip's left edge is still seen as a change.
        starts = [base + timedelta(hours=c) for c in range(-1, COLUMNS)]
        offsets = [tzinfo.utc_offset(city.tz, start) for start in starts]

        found = []
        for column in range(COLUMNS):
            if offsets[column] == offsets[column + 1]:
                continue
            transition = tzinfo.find_transition(city.tz, starts[column], starts[column + 1])
            # A change inside that leading hour already happened before the strip
            # begins; only one landing on column 0 itself belongs to this day.
            if transition is not None and transition.at >= starts[1]:
                found.append((column, transition))
        return found

    def row_current_date(self, city: City, at: datetime | None = None):
        return tzinfo.local_now(city.tz, at).date()
