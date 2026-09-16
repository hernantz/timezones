from __future__ import annotations

import calendar
from datetime import date

from gi.repository import GObject, Gtk

_WEEKDAY_INITIALS = ["M", "T", "W", "T", "F", "S", "S"]
_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


class DatePopover(Gtk.Popover):
    __gtype_name__ = "TimezonesDatePopover"

    __gsignals__ = {
        "date-selected": (GObject.SignalFlags.RUN_FIRST, None, (int, int, int)),
    }

    def __init__(self):
        super().__init__()
        self.set_size_request(250, -1)
        self._today = date.today()
        self._selected = self._today
        self._view_year = self._today.year
        self._view_month = self._today.month

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._month_label = Gtk.Label(xalign=0)
        self._month_label.add_css_class("heading")
        self._month_label.set_hexpand(True)
        self._month_label.set_halign(Gtk.Align.START)

        prev_btn = Gtk.Button()
        prev_btn.set_icon_name("go-previous-symbolic")
        prev_btn.add_css_class("flat")
        prev_btn.add_css_class("circular")
        prev_btn.connect("clicked", lambda *_a: self._shift_month(-1))

        next_btn = Gtk.Button()
        next_btn.set_icon_name("go-next-symbolic")
        next_btn.add_css_class("flat")
        next_btn.add_css_class("circular")
        next_btn.connect("clicked", lambda *_a: self._shift_month(1))

        header.append(self._month_label)
        header.append(prev_btn)
        header.append(next_btn)
        root.append(header)

        weekday_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, homogeneous=True)
        for wd in _WEEKDAY_INITIALS:
            lbl = Gtk.Label(label=wd)
            lbl.add_css_class("tz-cal-weekday")
            weekday_row.append(lbl)
        root.append(weekday_row)

        self._grid = Gtk.Grid()
        self._grid.set_row_spacing(2)
        self._grid.set_column_spacing(2)
        self._grid.set_column_homogeneous(True)
        root.append(self._grid)

        self.set_child(root)
        self._render()

    def _shift_month(self, delta: int) -> None:
        month = self._view_month - 1 + delta
        self._view_year += month // 12
        self._view_month = month % 12 + 1
        self._render()

    def reset_to_today(self) -> None:
        """Re-center the calendar on today, for when something outside the
        popover (the header's Today button) takes the window back there —
        otherwise reopening it would still highlight the date just left.
        """
        self._today = date.today()
        self._selected = self._today
        self._view_year = self._today.year
        self._view_month = self._today.month
        self._render()

    def _select(self, d: date) -> None:
        self._selected = d
        self._view_year = d.year
        self._view_month = d.month
        self._render()
        self.emit("date-selected", d.year, d.month, d.day)

    def _render(self) -> None:
        self._month_label.set_label(f"{_MONTH_NAMES[self._view_month - 1]} {self._view_year}")

        child = self._grid.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._grid.remove(child)
            child = nxt

        cal = calendar.Calendar(firstweekday=0)
        weeks = cal.monthdatescalendar(self._view_year, self._view_month)
        for row_idx, week in enumerate(weeks):
            for col_idx, day in enumerate(week):
                btn = Gtk.Button(label=str(day.day))
                btn.add_css_class("flat")
                btn.add_css_class("tz-cal-day")
                if day.month != self._view_month:
                    btn.add_css_class("muted")
                if day == self._today:
                    btn.add_css_class("today")
                if day == self._selected:
                    btn.add_css_class("selected")
                btn.connect("clicked", lambda _b, d=day: self._select(d))
                self._grid.attach(btn, col_idx, row_idx, 1, 1)
