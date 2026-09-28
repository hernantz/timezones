from __future__ import annotations

from datetime import date

from gi.repository import Gdk, GLib, GObject, Gtk

# The keys Gtk.Calendar picks the focused day with.
_SELECT_KEYS = (Gdk.KEY_space, Gdk.KEY_KP_Space)


class DatePopover(Gtk.Popover):
    """The date picker behind the header's calendar button.

    A stock Gtk.Calendar: it takes the first day of the week, the month and
    weekday names and the right-to-left layout from the locale, and brings
    keyboard navigation and screen-reader support with it.
    """

    __gtype_name__ = "TimezonesDatePopover"

    __gsignals__ = {
        "date-selected": (GObject.SignalFlags.RUN_FIRST, None, (int, int, int)),
    }

    def __init__(self):
        super().__init__()
        self._calendar = Gtk.Calendar()
        self._calendar.add_css_class("tz-calendar")
        # Adwaita draws the calendar's month and year arrows as square
        # buttons, made for a calendar sitting in a window; in a popover they
        # read as unstyled. The same flat circular buttons as the rest of the
        # header instead. The calendar exposes no API for them, so they are
        # found by walking its header; missing them only costs the look.
        header = self._calendar.get_first_child()
        child = header.get_first_child() if header is not None else None
        while child is not None:
            if isinstance(child, Gtk.Button):
                child.add_css_class("flat")
                child.add_css_class("circular")
            child = child.get_next_sibling()
        self._calendar.set_margin_top(6)
        self._calendar.set_margin_bottom(6)
        self._calendar.set_margin_start(6)
        self._calendar.set_margin_end(6)
        # Only a day being picked moves the window: the month and year arrows
        # emit their own signals, so browsing ahead leaves the list alone.
        self._calendar.connect("day-selected", self._on_day_selected)
        # But the arrows also carry the selection along (the 28th stays the
        # 28th, a year on) without a day-selected, and clicking the day that is
        # already selected emits nothing either — so the day under the arrows
        # could never be picked. The same goes for Ctrl+arrows and Space, the
        # calendar's keyboard pick. A click on a day, or a Space, that GTK let
        # pass is taken as a pick all the same. Capture phase, so the press
        # runs before the calendar's own handlers and the release after them.
        self._day_signalled = False
        click = Gtk.GestureClick()
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", self._on_click_pressed)
        click.connect("released", self._on_click_released)
        self._calendar.add_controller(click)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key_pressed)
        keys.connect("key-released", self._on_key_released)
        self._calendar.add_controller(keys)
        self._resetting = False
        self.set_child(self._calendar)

    def reset_to_today(self) -> None:
        """Re-center the calendar on today, for when something outside the
        popover (the header's Today button) takes the window back there —
        otherwise reopening it would still highlight the date just left.
        """
        # select_day() emits day-selected like a click would, and the window
        # is already on its way back to today.
        self._resetting = True
        try:
            self._calendar.select_day(GLib.DateTime.new_now_local())
        finally:
            self._resetting = False

    def do_focus(self, direction: Gtk.DirectionType) -> bool:
        # The calendar is focusable itself, ahead of its month and year arrows.
        # A popover wraps Tab around without dropping the focus first (a
        # window does), so from the last arrow Tab skips back past the day
        # grid to the first arrow, and Shift+Tab sticks on the grid. Wrapping
        # from no focus at all, as a window would, restores both.
        if direction not in (Gtk.DirectionType.TAB_FORWARD, Gtk.DirectionType.TAB_BACKWARD):
            return Gtk.Popover.do_focus(self, direction)
        if self._calendar.child_focus(direction):
            return True
        self.get_root().set_focus(None)
        return self._calendar.child_focus(direction)

    def _on_click_pressed(self, gesture, n_press, x, y) -> None:
        self._day_signalled = False

    def _on_click_released(self, gesture, n_press, x, y) -> None:
        if self._day_signalled:
            return
        target = self._calendar.pick(x, y, Gtk.PickFlags.DEFAULT)
        if (
            target is not None
            and target.has_css_class("day-number")
            and not target.has_css_class("other-month")
        ):
            self._emit_selected()

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        if keyval in _SELECT_KEYS:
            self._day_signalled = False
        return False

    def _on_key_released(self, controller, keyval, keycode, state) -> None:
        # Space picks the focused day, which by now is the selected one.
        if keyval in _SELECT_KEYS and not self._day_signalled:
            self._emit_selected()

    def _on_day_selected(self, calendar: Gtk.Calendar) -> None:
        self._day_signalled = True
        if self._resetting:
            return
        self._emit_selected()

    def _emit_selected(self) -> None:
        picked = self._calendar.get_date()
        day = date(picked.get_year(), picked.get_month(), picked.get_day_of_month())
        self.emit("date-selected", day.year, day.month, day.day)
