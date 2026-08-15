from __future__ import annotations

from gi.repository import GObject, Gtk

from .timeline import TimelineStrip

_TOP_MARKER_INSET = 4  # px from the content area's own top edge


class TimelineCursorOverlay(Gtk.Fixed):
    """Two vertical markers over the timeline list:

    - the ambient "now" line: quiet, dashed, a small dot — always-on context.
    - the scrub line: solid, prominent, follows the mouse/keyboard while
      hovering and (once clicked) stays put as a "pinned" preview instant.
    """

    __gtype_name__ = "TimezonesTimelineCursorOverlay"

    __gsignals__ = {
        "unpin-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_halign(Gtk.Align.FILL)
        self.set_valign(Gtk.Align.FILL)

        self._now_line = Gtk.Box()
        self._now_line.add_css_class("tz-now-line")
        self._now_dot = Gtk.Box()
        self._now_dot.add_css_class("tz-now-dot")

        self._scrub_line = Gtk.Box()
        self._scrub_line.add_css_class("tz-scrub-line")
        self._scrub_line.set_size_request(2, -1)

        self._scrub_pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._scrub_pill.add_css_class("tz-scrub-pill")
        self._scrub_label = Gtk.Label()
        self._unpin_btn = Gtk.Button()
        self._unpin_btn.set_can_target(True)
        self._unpin_btn.add_css_class("tz-scrub-unpin")
        self._unpin_btn.add_css_class("flat")
        self._unpin_btn.add_css_class("circular")
        self._unpin_btn.set_icon_name("window-close-symbolic")
        self._unpin_btn.set_tooltip_text("Back to now")
        self._unpin_btn.connect("clicked", lambda *_a: self.emit("unpin-requested"))
        self._unpin_btn.set_visible(False)
        self._scrub_pill.append(self._scrub_label)
        self._scrub_pill.append(self._unpin_btn)

        for widget in (self._now_line, self._now_dot, self._scrub_line, self._scrub_pill):
            self.put(widget, 0, 0)

        # Pure decoration: never a pointer target, so a click on any of them
        # reaches the timeline underneath. The pill is the exception — see
        # update_scrub, which turns it targetable only while pinned.
        for widget in (self._now_line, self._now_dot, self._scrub_line):
            widget.set_can_target(False)
        self._scrub_pill.set_can_target(False)

        self._anchor: TimelineStrip | None = None
        self._now_column = 0.0
        self._now_visible = False
        self._scrub_column = 0.0
        self._scrub_visible = False
        self._scrub_pinned = False

        self._now_line.set_visible(False)
        self._now_dot.set_visible(False)
        self._scrub_line.set_visible(False)
        self._scrub_pill.set_visible(False)

    def set_anchor(self, timeline: TimelineStrip | None) -> None:
        self._anchor = timeline
        self._reposition()

    def update_now(self, column: float, visible: bool) -> None:
        self._now_column = column
        self._now_visible = visible
        self._now_line.set_visible(visible)
        self._now_dot.set_visible(visible)
        self._reposition()

    def update_scrub(self, column: float, visible: bool, pinned: bool, label_text: str = "") -> None:
        self._scrub_column = column
        self._scrub_visible = visible
        self._scrub_pinned = pinned
        self._scrub_line.set_visible(visible)
        self._scrub_pill.set_visible(visible)
        if visible:
            self._scrub_label.set_label(label_text)
        if pinned:
            self._scrub_pill.add_css_class("pinned")
        else:
            self._scrub_pill.remove_css_class("pinned")
        self._unpin_btn.set_visible(pinned)
        # Only the parked pill takes the pointer. While it's merely tracking
        # the mouse it must stay click-through, or it would sit under the
        # pointer and steal the motion events the list box's own controller
        # needs — the list would see a `leave` and the scrub line would drop
        # out exactly where the pill overlaps it. Pinned it's harmless:
        # hovering no longer moves anything, so the × can hold the pointer.
        self._scrub_pill.set_can_target(pinned)
        self._reposition()

    def do_contains(self, _x: float, _y: float) -> bool:
        # This overlay covers the whole content area but is only ever a
        # backdrop for its markers, so it must never be picked as a pointer
        # target itself — otherwise it would swallow every click meant for
        # the timeline below it. Returning False here (rather than clearing
        # can-target, which stops GTK descending into the children at all)
        # leaves the pill's × reachable: gtk_widget_real_pick walks the
        # children first and only consults contains() once none of them hit.
        return False

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        Gtk.Fixed.do_size_allocate(self, width, height, baseline)
        self._reposition()

    def _column_x(self, column_fraction: float) -> float | None:
        # Measuring the actual cell widget (rather than predicting its
        # position from the strip's total width divided by cell count)
        # matters here: GTK's homogeneous grid allocates whole pixels with
        # rounding, so a purely analytical division drifts from where cells
        # are actually drawn. The real cell position is the source of truth.
        if self._anchor is None:
            return None
        column_fraction = max(0.0, min(24.0, column_fraction))
        col = max(0, min(23, int(column_fraction)))
        cell = self._anchor.get_cell_widget(col)
        if cell is None:
            return None
        ok, rect = cell.compute_bounds(self)
        if not ok:
            return None
        # Each cell is the whole one-hour block [col, col+1), so how far
        # into the hour an instant is, is how far across its cell it draws.
        # (24.0 lands on the trailing edge of the last cell, not a 25th one.)
        frac = max(0.0, min(1.0, column_fraction - col))
        return rect.origin.x + rect.size.width * frac

    def _reposition(self) -> None:
        height = self.get_height() or self.get_allocated_height()

        if self._now_visible:
            x = self._column_x(self._now_column)
            if x is not None:
                self._now_line.set_size_request(2, height)
                self.move(self._now_line, x - 1, 0)
                # Sit just inside the top edge — this overlay's own y=0 is
                # already the top of the content area (below the header bar),
                # so a negative/straddling offset here would paint over the
                # header bar itself rather than "above the line".
                self.move(self._now_dot, x - 3.5, _TOP_MARKER_INSET)

        if self._scrub_visible:
            x = self._column_x(self._scrub_column)
            if x is not None:
                self._scrub_line.set_size_request(2, height)
                self.move(self._scrub_line, x - 1, 0)
                _, pw, _, _ = self._scrub_pill.measure(Gtk.Orientation.HORIZONTAL, -1)
                self.move(self._scrub_pill, x - pw / 2, _TOP_MARKER_INSET)
