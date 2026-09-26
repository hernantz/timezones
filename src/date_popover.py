from __future__ import annotations

from datetime import date

from gi.repository import GLib, GObject, Gtk


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

    def _on_day_selected(self, calendar: Gtk.Calendar) -> None:
        if self._resetting:
            return
        picked = calendar.get_date()
        day = date(picked.get_year(), picked.get_month(), picked.get_day_of_month())
        self.emit("date-selected", day.year, day.month, day.day)
