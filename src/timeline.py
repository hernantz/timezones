from __future__ import annotations

import weakref
from dataclasses import dataclass
from datetime import datetime

from gi.repository import Gdk, Gtk

from . import tzinfo_helpers as tzinfo
from .i18n import format_date_flag
from .model import COLUMNS as _COLUMNS
from .model import City, ClockModel

_LABEL_EDGE_INSET = 3  # px kept clear between a date-flag label and the strip's own edge
_LABEL_GAP = 4  # px kept clear between the two date-flag labels when they'd otherwise overlap
_LABEL_TOP = 2  # px between a date-flag label and the top of the strip
_CAP_MARGIN_START = 6  # px; must match .tz-cell.cap-start margin-left in style.css
_LINE_WIDTH = 2  # px; the now/scrub cursors are both this wide
# Below this much width per column the hour numbers run into each other (the
# widest, "22", is ~12px at the label's 9.5px bold), so the strip goes compact:
# every other column keeps its number and the rest show a dot.
_COMPACT_COLUMN_WIDTH = 17

# The strip is exactly _COLUMNS equal cells (see model.COLUMNS for why that
# count never varies). Cell C is the one-hour block [C, C+1) of the reference
# timezone's day — the reference row therefore reads 12am through 11pm straight
# across — and carries the hour it represents centered inside it. Every row
# divides the same total width the same way, so column C sits at the same x in
# every row and each non-reference row just relabels those columns with its own
# local hours.


def _column_x(column: int, total_width: int) -> int:
    """Left edge of `column` in the strip's homogeneous 24-column grid.

    Derived from the width rather than read back off the cell, which means it's
    correct in the same pass that resizes the strip instead of one frame later.
    The `min` term mirrors how GTK hands out the leftover pixels a width that
    doesn't divide by 24 leaves over — one extra to each of the first few
    columns — so this lands on the exact seam the cells draw, not near it.
    """
    base, extra = divmod(total_width, _COLUMNS)
    return column * base + min(column, extra)


def _clamp(value: int, maximum: int) -> int:
    return max(0, min(maximum, value))


def _fractional_column_x(column: float, total_width: int) -> float:
    """Where a (possibly fractional) hour lands across the strip.

    Each cell is the whole one-hour block [C, C+1), so how far into the hour an
    instant is, is how far across its cell it draws. Interpolating between the
    two real seams rather than scaling `column / 24 * width` keeps it on the
    grid GTK actually laid out, including the leftover pixels _column_x hands
    to the first few columns. (24.0 lands on the trailing edge of the last
    cell, not on a 25th one.)
    """
    column = max(0.0, min(float(_COLUMNS), column))
    col = min(_COLUMNS - 1, int(column))
    left = _column_x(col, total_width)
    right = _column_x(col + 1, total_width)
    return left + (right - left) * (column - col)


def _flag_positions(
    total_width: int,
    start_width: int | None,
    boundary_width: int | None,
    boundary_column: int,
) -> tuple[int | None, int | None]:
    """Solve both date-flag pills' x positions, or None for a pill that can't be shown.

    Each pill names the day that *begins* where it sits, so its home is the left
    edge of its own date segment: the strip's start for the first pill, the
    day-break seam for the second. Two constraints bend that:

      * Neither may cross the strip's right edge — the strip's overlay spills
        past its own bounds, and just beyond it sits the row's menu button.
      * They must stay in chronological order. The pills are read as a sequence,
        so a later date drawn to the left of an earlier one misreads badly.

    The second pill is the one that yields. When the seam sits close enough to
    the strip's start that the two collide — any row an hour or two behind the
    reference — the first pill keeps its anchor and the second slides right to
    clear it, so both stay over as much of their own day as the space allows and
    the pair still reads left to right.
    """
    start_x = None if start_width is None else _LABEL_EDGE_INSET

    boundary_x = None
    if boundary_width is not None:
        # Past the gap the cap margin opens up, so the pill starts inside the
        # new day's rounded background rather than on top of the dashed rule
        # sitting in that gap.
        anchor = _column_x(boundary_column, total_width) + _CAP_MARGIN_START
        boundary_x = anchor + _LABEL_EDGE_INSET
        if start_x is not None:
            boundary_x = max(boundary_x, start_x + start_width + _LABEL_GAP)
        # A seam near the far end leaves the pill no room to extend rightward,
        # so it tucks flush against the strip's edge instead — the same flip a
        # tooltip does near a screen edge.
        boundary_x = min(boundary_x, total_width - _LABEL_EDGE_INSET - boundary_width)

        if start_x is not None and boundary_x < start_x + start_width + _LABEL_GAP:
            # Strip too narrow to seat both in order. The day-change pill is the
            # one carrying new information, so it keeps the space.
            start_x = None

    return start_x, boundary_x


class _DateFlagLayer(Gtk.Widget):
    """The layer the date-flag pills are painted on, above every cell.

    A bare Gtk.Widget, not a Gtk.Fixed: any widget carrying a layout manager
    (Fixed, Grid, Box, Overlay…) never has its size_allocate vfunc called, since
    GTK4 hands allocation to the layout manager instead. A Fixed here could only
    be repositioned by hand, and would hold coordinates from the old width until
    something else happened to rebuild the strip — pills stranded mid-cell, or
    out past the strip's edge and over the row's menu button. Owning the
    allocation directly means the pills are placed by the very pass that resizes
    the strip, so they cannot be stale.
    """

    __gtype_name__ = "TimezonesDateFlagLayer"

    def __init__(self):
        super().__init__()
        self.set_can_target(False)
        self._start: Gtk.Widget | None = None
        self._boundary: Gtk.Widget | None = None
        self._boundary_column = 0

    def set_flags(
        self,
        start: Gtk.Widget | None,
        boundary: Gtk.Widget | None,
        boundary_column: int,
    ) -> None:
        for old in (self._start, self._boundary):
            if old is not None:
                old.unparent()
        self._start = start
        self._boundary = boundary
        self._boundary_column = boundary_column
        for new in (start, boundary):
            if new is not None:
                new.set_parent(self)
        self.queue_resize()

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        start_w = self._natural_width(self._start)
        boundary_w = self._natural_width(self._boundary)
        start_x, boundary_x = _flag_positions(width, start_w, boundary_w, self._boundary_column)

        for flag, x, w in ((self._start, start_x, start_w), (self._boundary, boundary_x, boundary_w)):
            if flag is None:
                continue
            flag.set_child_visible(x is not None)
            if x is None:
                continue
            _, natural_h, _, _ = flag.measure(Gtk.Orientation.VERTICAL, w)
            # Field-by-field: Gdk.Rectangle is a boxed struct, and passing the
            # fields to its constructor silently ignores them and leaves zeroes.
            rect = Gdk.Rectangle()
            rect.x, rect.y, rect.width, rect.height = x, _LABEL_TOP, w, natural_h
            flag.size_allocate(rect, -1)

    @staticmethod
    def _natural_width(flag: Gtk.Widget | None) -> int | None:
        if flag is None:
            return None
        _, natural, _, _ = flag.measure(Gtk.Orientation.HORIZONTAL, -1)
        return natural

    def do_dispose(self) -> None:
        # A plain Gtk.Widget doesn't unparent its children for us the way a
        # container would, and finalizing with children still attached warns.
        # Unparent straight rather than via set_flags, which would queue a
        # resize on a widget that is already going away.
        for flag in (self._start, self._boundary):
            if flag is not None:
                flag.unparent()
        self._start = self._boundary = None
        Gtk.Widget.do_dispose(self)


class _CursorLayer(Gtk.Widget):
    """The layer both vertical cursors are painted on, above every cell.

    - the ambient "now" line: quiet, dashed.
    - the scrub line: solid, prominent, tracking the pointer or the pinned
      preview instant.

    Both live inside the strip rather than on the window-wide overlay so they
    can only ever cross hours: stacked, a strip is one band of a taller row,
    and a line drawn over the whole list ran straight through the city name,
    the clock and the kebab above it. The scrub's pill stays on the overlay —
    it is a label that has to be legible and clickable outside the strips.

    Same custom-allocation reasoning as _DateFlagLayer: owning size_allocate
    means the lines are placed by the very pass that resizes the strip, so they
    land on the same seams the cells do at every width, in the same frame.
    """

    __gtype_name__ = "TimezonesCursorLayer"

    def __init__(self):
        super().__init__()
        self.set_can_target(False)
        self._now_column: float | None = None
        self._scrub_column: float | None = None

        self._now_line = Gtk.Box()
        self._now_line.add_css_class("tz-now-line")

        # Parented last, so the scrub draws over the now-line where the two
        # coincide — the scrub is the one the user is actively pointing at.
        self._scrub_line = Gtk.Box()
        self._scrub_line.add_css_class("tz-scrub-line")

        for child in (self._now_line, self._scrub_line):
            child.set_parent(self)
            # Nothing to mark until set_now/set_scrub says otherwise, and an
            # unallocated visible child is one GTK complains about.
            child.set_child_visible(False)

    def set_now(self, column: float | None) -> None:
        if column == self._now_column:
            return
        self._now_column = column
        self._requeue()

    def set_scrub(self, column: float | None) -> None:
        if column == self._scrub_column:
            return
        self._scrub_column = column
        self._requeue()

    def _requeue(self) -> None:
        # Allocate, not resize: nothing about this layer's size depends on
        # where the lines sit, and they move on every tick and every motion
        # event.
        self.queue_allocate()

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        sized = width > 0 and height > 0
        now = self._now_column if sized else None
        scrub = self._scrub_column if sized else None

        self._now_line.set_child_visible(now is not None)
        self._scrub_line.set_child_visible(scrub is not None)

        if now is not None:
            self._allocate_line(self._now_line, _fractional_column_x(now, width), width, height)

        if scrub is not None:
            self._allocate_line(self._scrub_line, _fractional_column_x(scrub, width), width, height)

    @classmethod
    def _allocate_line(cls, line: Gtk.Widget, x: float, width: int, height: int) -> None:
        # Centered on the seam, then pulled inside the strip at either end:
        # the layer is clipped, so a line at midnight or at 24:00 would
        # otherwise lose half its width to the edge.
        cls._allocate(line, _clamp(round(x) - 1, width - _LINE_WIDTH), 0, _LINE_WIDTH, height)

    @staticmethod
    def _allocate(child: Gtk.Widget, x: int, y: int, width: int, height: int) -> None:
        # Field-by-field, as in _DateFlagLayer: Gdk.Rectangle is a boxed
        # struct whose constructor silently ignores the fields passed to it.
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = x, y, width, height
        child.size_allocate(rect, -1)

    def do_dispose(self) -> None:
        # See _DateFlagLayer.do_dispose: a plain Gtk.Widget keeps its children
        # parented until told otherwise, and finalizing with them still
        # attached warns.
        for child in (self._now_line, self._scrub_line):
            if child is not None:
                child.unparent()
        self._now_line = self._scrub_line = None
        Gtk.Widget.do_dispose(self)


@dataclass(frozen=True)
class _CellSpec:
    """Everything about one hour cell that a redraw can change.

    Comparing two of these is what lets `TimelineStrip.update()` skip the 21-odd
    columns that a typical redraw leaves alone. Frozen so a cell can hold on to
    the spec it was last painted with and trust it.
    """

    hour_label: str
    tone: str  # "day" | "night" | "neutral" | "dst"
    marker: str | None  # "sun" at a sunrise, "moon" at a sunset, else nothing
    cap_start: bool
    cap_end: bool


class _Cell:
    """One hour of the strip, built once and mutated thereafter.

    The slot always fills its whole grid column; only `base` — the painted
    background — is inset by the day-break margins. The hour label is an
    overlay sibling of `base` rather than its child, so that inset can never
    re-center it: the hour stays on its column's center in the two cells
    flanking the gap exactly like everywhere else, and only the background
    visibly pulls back.
    """

    __slots__ = ("slot", "base", "label", "rule", "marker", "spec", "label_shown")

    def __init__(self, spec: _CellSpec) -> None:
        self.spec = spec

        self.slot = Gtk.Overlay()
        self.slot.add_css_class("tz-cell-slot")
        self.slot.add_css_class(spec.tone)

        self.base = Gtk.Box()
        self.base.add_css_class("tz-cell")
        self.base.add_css_class(spec.tone)
        if spec.cap_start:
            self.base.add_css_class("cap-start")
        if spec.cap_end:
            self.base.add_css_class("cap-end")
        self.base.set_halign(Gtk.Align.FILL)
        self.base.set_valign(Gtk.Align.FILL)
        self.slot.set_child(self.base)

        self.label = Gtk.Label(label=spec.hour_label)
        self.label.add_css_class("tz-cell-label")
        self.label.set_halign(Gtk.Align.CENTER)
        self.label.set_valign(Gtk.Align.CENTER)
        # Reserved headroom so the hour number sits a little lower, leaving
        # clear space above it for a date-flag label — no collision, no need
        # to shuffle the label somewhere else.
        self.label.set_margin_top(10)
        self.slot.add_overlay(self.label)
        # ...but it still has to drive the cell's minimum width, which an
        # overlay child doesn't do by default — otherwise the strip would
        # happily shrink until the hours were unreadable.
        self.slot.set_measure_overlay(self.label, True)
        self.label_shown = True

        self.rule: Gtk.Widget | None = None
        self.marker: Gtk.Widget | None = None
        if spec.cap_start:
            self._add_rule()
        if spec.marker is not None:
            self._add_marker(spec.marker)

    def apply(self, spec: _CellSpec) -> None:
        """Move this cell from the state it is in to `spec`, and no further."""
        old = self.spec
        if spec == old:
            return

        if spec.hour_label != old.hour_label and self.label_shown:
            self.label.set_label(spec.hour_label)

        if spec.tone != old.tone:
            for widget in (self.slot, self.base):
                widget.remove_css_class(old.tone)
                widget.add_css_class(spec.tone)

        if spec.cap_start != old.cap_start:
            if spec.cap_start:
                self.base.add_css_class("cap-start")
                self._add_rule()
            else:
                self.base.remove_css_class("cap-start")
                self.slot.remove_overlay(self.rule)
                self.rule = None

        if spec.cap_end != old.cap_end:
            if spec.cap_end:
                self.base.add_css_class("cap-end")
            else:
                self.base.remove_css_class("cap-end")

        if spec.marker != old.marker:
            if self.marker is not None:
                self.slot.remove_overlay(self.marker)
                self.marker = None
            if spec.marker is not None:
                self._add_marker(spec.marker)

        self.spec = spec

    def show_label(self, shown: bool) -> None:
        """Show the hour number, or stand a dot in for it on a compact strip.

        Kept apart from the spec: whether a number fits is a matter of the
        strip's width, which changes without the hour behind it changing.
        """
        if shown == self.label_shown:
            return
        self.label_shown = shown
        self.label.set_label(self.spec.hour_label if shown else "\u00b7")
        if shown:
            self.label.remove_css_class("dot")
        else:
            self.label.add_css_class("dot")

    def _add_rule(self) -> None:
        # The dashed rule marks the seam itself: overlaid flush against the
        # column's leading edge, which is exactly the midpoint of the gap the
        # two cap margins open up around it. Being an overlay it takes no width
        # from the slot, so the day change costs the grid nothing and columns
        # stay aligned across rows.
        self.rule = Gtk.Box()
        self.rule.add_css_class("tz-daybreak")
        self.rule.set_halign(Gtk.Align.START)
        self.rule.set_valign(Gtk.Align.FILL)
        self.slot.add_overlay(self.rule)

    def _add_marker(self, kind: str) -> None:
        marker = Gtk.Box()
        marker.add_css_class("tz-marker")
        marker.add_css_class(kind)
        marker.set_size_request(15, 15)
        marker.set_halign(Gtk.Align.CENTER)
        # Anchored to the bottom of the cell (rather than the top, as in the
        # original spec) so it never collides with the date-flag pill, which
        # always anchors to the top of column 0 / the boundary column.
        marker.set_valign(Gtk.Align.END)
        marker.set_margin_bottom(2)
        icon = Gtk.Image.new_from_icon_name(
            "weather-clear-symbolic" if kind == "sun" else "weather-clear-night-symbolic"
        )
        icon.set_pixel_size(10)
        icon.set_hexpand(True)
        icon.set_vexpand(True)
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_valign(Gtk.Align.CENTER)
        marker.append(icon)
        self.slot.add_overlay(marker)
        self.marker = marker


class _StripLayout(Gtk.OverlayLayout):
    """The overlay's own layout, plus a word to the strip about its width.

    GtkOverlay allocates through its layout manager, so a `do_size_allocate`
    on the strip itself is never called; this is the one place that learns the
    width in the same pass that hands it out.
    """

    def __init__(self, on_allocate) -> None:
        super().__init__()
        # Weak, because the strip owns this layout: a strong bound method would
        # close a cycle through two GObjects and keep a removed row alive.
        self._on_allocate = weakref.WeakMethod(on_allocate)

    def do_allocate(self, widget: Gtk.Widget, width: int, height: int, baseline: int) -> None:
        callback = self._on_allocate()
        if callback is not None:
            callback(width)
        Gtk.OverlayLayout.do_allocate(self, widget, width, height, baseline)


class TimelineStrip(Gtk.Overlay):
    __gtype_name__ = "TimezonesTimelineStrip"

    def __init__(self):
        super().__init__()
        self.set_hexpand(True)
        self.set_layout_manager(_StripLayout(self._on_allocate))

        # A homogeneous 24-column grid, always — no row ever has an extra
        # sibling widget eating into the shared width, so every row divides
        # the exact same total width the exact same way and columns stay
        # aligned across rows.
        self._row = Gtk.Grid()
        self._row.set_column_homogeneous(True)
        self._row.set_row_homogeneous(True)
        self._row.add_css_class("tz-timeline")
        self._row.set_hexpand(True)
        # Time runs left to right on this strip in every language. Mirrored
        # for a right-to-left UI, the grid would put midnight on the right
        # while the pills, the cursors and the pointer-to-hour math — all
        # plain x offsets from the left — kept reading it from the left. Set
        # on the grid itself: GTK 4 falls back to the global default, not to
        # the parent, for a widget with no direction of its own.
        self._row.set_direction(Gtk.TextDirection.LTR)
        # Clipped so the strip can be given rounded corners of its own: stacked,
        # the grid *is* the bottom edge of the card, and the cells paint their
        # tints right into the corner. Without this they square off the curve
        # the card's border still draws, and the two read as two mismatched
        # roundings sitting on top of each other.
        self._row.set_overflow(Gtk.Overflow.HIDDEN)
        self.set_child(self._row)

        # Date-flag pills are painted on a layer above every cell — they
        # spill over neighboring cells and would otherwise be covered by the
        # next cell's own background. The day-break "cut" itself is NOT
        # here: it's real CSS margin on the cap-start/cap-end backgrounds
        # plus a dashed rule overlaid on the seam (see _Cell and
        # .tz-cell.cap-start/.cap-end in style.css), which keeps it inside
        # the normal layout pass instead of needing manual positioning that
        # can drift on resize.
        self._decor_layer = _DateFlagLayer()
        self.add_overlay(self._decor_layer)
        # Clipped, so a pill can never paint outside the strip and over the
        # row's menu button. _flag_positions already keeps them inside; this is
        # the backstop that makes overflowing visible as a cut-off pill rather
        # than as scribble on an unrelated control.
        self.set_clip_overlay(self._decor_layer, True)

        # Above the pills: the two cursors are the marks that have to stay
        # readable whatever else the strip is showing. Clipped for the same
        # reason — neither may reach the row's menu button.
        self._cursor_layer = _CursorLayer()
        self.add_overlay(self._cursor_layer)
        self.set_clip_overlay(self._cursor_layer, True)

        # Built on the first update() and kept for the strip's whole life;
        # see update() for why they are never torn down again.
        self._cells: list[_Cell] | None = None
        self._cell_widgets: list[Gtk.Widget] = [None] * _COLUMNS  # type: ignore[list-item]
        self._flag_key: tuple | None = None
        self._boundary = 0
        self._compact = False

    def _on_allocate(self, width: int) -> None:
        # Decided on the width actually handed out rather than on the window's
        # breakpoint: stacked or side by side, the strip's share of the window
        # differs. Dots are never wider than the numbers they replace, so going
        # compact can't raise the strip's minimum and talk itself back out.
        compact = 0 < width < _COMPACT_COLUMN_WIDTH * _COLUMNS
        if compact != self._compact:
            self._compact = compact
            self._show_labels()

    def _show_labels(self) -> None:
        """Number every other column on a compact strip, every column otherwise.

        Thinned by column, not by local hour, so a column is numbered in every
        row or in none and the grid still reads straight down. The day break is
        the exception: it always keeps its number — it is the hour the date
        pill above it is anchored to — and its neighbours give theirs up so it
        doesn't end up crowded all over again.
        """
        if self._cells is None:
            return
        boundary = self._boundary
        for col, cell in enumerate(self._cells):
            if not self._compact:
                shown = True
            elif boundary != 0 and col == boundary:
                shown = True
            elif boundary != 0 and abs(col - boundary) == 1:
                shown = False
            else:
                shown = col % 2 == 0
            cell.show_label(shown)

    def set_now(self, column: float | None) -> None:
        """Draw (or hide) the ambient now-line at `column` hours into the day."""
        self._cursor_layer.set_now(column)

    def set_scrub(self, column: float | None) -> None:
        """Draw (or hide) the scrub line at `column` hours into the day."""
        self._cursor_layer.set_scrub(column)

    def get_cell_widget(self, column: int) -> Gtk.Widget | None:
        # Used by the shared now-line/scrub-line overlay to find where a
        # given hour column actually renders.
        if 0 <= column < _COLUMNS:
            return self._cell_widgets[column]
        return None

    def update(
        self,
        model: ClockModel,
        city: City,
        fmt_24h: bool,
        show_daynight: bool,
        at: datetime | None = None,
        transitions: list[tuple[int, tzinfo.DstTransition]] | None = None,
    ) -> None:
        """Bring the strip in line with `at`, touching only what differs.

        The 24 cells are built once and then kept: a redraw is a label write
        and a class swap per column, and only the handful of columns whose
        sunrise/sunset marker or day-break rule actually moved pay for a child
        being added or removed. Tearing the grid down instead cost ~180ms of
        Python and ~80ms of GTK relayout at 30 rows, for a result that is
        usually identical in 23 of its 24 columns.
        """
        boundary = model.boundary_column(city, at)
        dst_columns = {column for column, _ in (transitions or ())}
        # The strip spans exactly the reference zone's day, so the reference
        # date is the same at every column — one comparison serves both pills.
        reference_date = model.reference_midnight(at).date()

        day_flags = [
            tzinfo.is_daylight(city.tz, model.column_instant(c, at), city.place) for c in range(_COLUMNS)
        ]
        prev_day = tzinfo.is_daylight(city.tz, model.column_instant(-1, at), city.place)

        specs: list[_CellSpec] = []
        flags: list[tuple[int, str, bool]] = []
        for col in range(_COLUMNS):
            is_day = day_flags[col]
            was_day = day_flags[col - 1] if col > 0 else prev_day

            if col == 0 or col == boundary:
                row_dt = tzinfo.local_now(city.tz, model.column_instant(col, at))
                # Accented when the day this pill names is not the reference's
                # day, matching the row's date label: the highlight marks a
                # date the reader can't assume, not a particular pill. A row
                # behind the reference therefore accents its opening pill
                # (yesterday, there) and leaves the rollover plain; a row ahead
                # does the reverse.
                flags.append(
                    (
                        col,
                        format_date_flag(row_dt),
                        row_dt.date() != reference_date,
                    )
                )

            if col in dst_columns:
                # The clock-change cell keeps its column, its width and its
                # label — only the paint changes, so the grid stays readable
                # straight down. The red is the app's destructive red, borrowed
                # rather than newly invented: "pay attention, something unusual
                # is happening here" is the same thing it says on Remove
                # timezone.
                tone = "dst"
            elif not show_daynight:
                tone = "neutral"
            else:
                tone = "day" if is_day else "night"

            sunrise = is_day and not was_day
            sunset = (not is_day) and was_day

            specs.append(
                _CellSpec(
                    hour_label=_hour_label(model.local_hour_at_column(city, col, at), fmt_24h),
                    tone=tone,
                    marker="sun" if sunrise else ("moon" if sunset else None),
                    cap_start=boundary != 0 and col == boundary,
                    cap_end=boundary != 0 and col == (boundary - 1) % _COLUMNS,
                )
            )

        if self._cells is None:
            self._cells = [_Cell(spec) for spec in specs]
            for col, cell in enumerate(self._cells):
                self._row.attach(cell.slot, col, 0, 1, 1)
            self._cell_widgets = [cell.slot for cell in self._cells]
            self._boundary = boundary
            self._show_labels()
        else:
            for cell, spec in zip(self._cells, specs):
                cell.apply(spec)
            if boundary != self._boundary:
                self._boundary = boundary
                self._show_labels()

        self._set_flags(flags, boundary)

    def _set_flags(self, flags: list[tuple[int, str, bool]], boundary: int) -> None:
        """Hand the date pills to the decor layer, but only when they changed.

        Two labels per row is cheap to rebuild; the queue_resize that comes
        with reparenting them is not, and on a 12/24h toggle or a reorder the
        pills are identical to the ones already up there.
        """
        key = (tuple(flags), boundary)
        if key == self._flag_key:
            return
        self._flag_key = key

        start_flag: Gtk.Widget | None = None
        boundary_flag: Gtk.Widget | None = None
        for col, text, accent in flags:
            # Positioned by _DateFlagLayer, which allocates it at its natural
            # size — hence no alignment set here.
            label = Gtk.Label(label=text)
            label.add_css_class("tz-flag")
            if accent:
                label.add_css_class("accent")
            if col == 0:
                start_flag = label
            else:
                boundary_flag = label
        self._decor_layer.set_flags(start_flag, boundary_flag, boundary)


def _hour_label(local_hour: int, fmt_24h: bool) -> str:
    if fmt_24h:
        return str(local_hour % 24)
    h = local_hour % 12
    return str(h if h != 0 else 12)
