from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import tzinfo_helpers as tzinfo
from .add_dialog import AddTimezoneDialog
from .cursor_overlay import TimelineCursorOverlay
from .date_popover import DatePopover
from .model import City, ClockModel
from .persistence import Settings, load_cities, save_cities
from .preferences import PreferencesDialog
from .row import TimezoneRow

_SCRUB_STEP = 0.25  # 15 minutes, matches _snap_column()
_MAX_COLUMN = 24.0 - _SCRUB_STEP  # 23:45 — last snappable slot still inside the day

_DEFAULT_CITIES = [
    City(tz="Europe/London", label="You", is_reference=True),
    City(tz="Africa/Cairo", label="Family"),
    City(tz="Europe/Moscow", label="Team"),
    City(tz="Pacific/Auckland"),
]

_TICK_SECONDS = 15


class TimezonesMainWindow(Adw.ApplicationWindow):
    __gtype_name__ = "TimezonesMainWindow"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_default_size(960, 560)
        self.add_css_class("tz-window")

        self._settings = Settings()
        self._fmt_24h = self._settings.get_bool("fmt-24h", False)
        self._show_offsets = self._settings.get_bool("show-offsets", True)
        self._show_daynight = self._settings.get_bool("show-daynight", True)
        self._compact_rows = self._settings.get_bool("compact-rows", False)
        self._viewing_date: date | None = None
        self._preferences: PreferencesDialog | None = None

        self._hovering = False
        self._hover_column = 0.0
        self._pinned = False
        self._pinned_column: float | None = None
        self._grid_date: date | None = None

        defaults = [City(tz=d.tz, label=d.label, is_reference=d.is_reference) for d in _DEFAULT_CITIES]
        cities = load_cities(defaults)
        self._model = ClockModel(cities)

        self._install_actions()
        self._build_ui()
        self._apply_theme_mode(self._settings.get_string("theme-mode", "system"))
        Adw.StyleManager.get_default().connect("notify::dark", self._on_style_dark_changed)
        self._sync_dark_class()

        self._rebuild_rows()
        GLib.timeout_add_seconds(_TICK_SECONDS, self._on_tick)

    # -- UI construction ----------------------------------------------------

    def _build_ui(self) -> None:
        toolbar_view = Adw.ToolbarView()

        header = Adw.HeaderBar()
        header.add_css_class("tz-headerbar")
        header.set_decoration_layout(":close")

        title_label = Gtk.Label(label="Timezones")
        title_label.add_css_class("title")
        header.set_title_widget(title_label)

        add_btn = Gtk.Button()
        add_btn.set_icon_name("list-add-symbolic")
        add_btn.set_tooltip_text("Add Timezone")
        add_btn.add_css_class("flat")
        add_btn.connect("clicked", self._on_add_clicked)
        header.pack_start(add_btn)

        self._date_btn = Gtk.MenuButton()
        self._date_btn.set_icon_name("x-office-calendar-symbolic")
        self._date_btn.set_tooltip_text("Jump to Date")
        self._date_btn.add_css_class("flat")
        self._date_popover = DatePopover()
        self._date_popover.connect("date-selected", self._on_date_selected)
        self._date_btn.set_popover(self._date_popover)
        header.pack_start(self._date_btn)

        self._fmt_group = Adw.ToggleGroup()
        toggle_24 = Adw.Toggle(name="24h", label="24h")
        toggle_12 = Adw.Toggle(name="12h", label="12h")
        self._fmt_group.add(toggle_24)
        self._fmt_group.add(toggle_12)
        self._fmt_group.set_active_name("24h" if self._fmt_24h else "12h")
        self._fmt_group.connect("notify::active", self._on_fmt_toggled)
        header.pack_end(self._build_menu_button())
        header.pack_end(self._fmt_group)

        toolbar_view.add_top_bar(header)

        self._banner = Adw.Banner()
        self._banner.set_button_label("Jump to Today")
        self._banner.connect("button-clicked", self._on_banner_jump_today)
        toolbar_view.add_top_bar(self._banner)

        overlay = Gtk.Overlay()
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        self._list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self._list_box.set_margin_top(10)
        self._list_box.set_margin_bottom(18)
        self._list_box.set_margin_start(16)
        self._list_box.set_margin_end(16)
        scrolled.set_child(self._list_box)

        overlay.set_child(scrolled)
        self._cursor = TimelineCursorOverlay()
        self._cursor.connect("unpin-requested", self._on_unpin_requested)
        overlay.add_overlay(self._cursor)

        self._content_stack = Gtk.Stack()
        self._content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._content_stack.add_named(overlay, "list")
        self._content_stack.add_named(self._build_empty_state(), "empty")

        toolbar_view.set_content(self._content_stack)
        self.set_content(toolbar_view)

        self._list_box.set_focusable(True)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_timeline_motion)
        motion.connect("leave", self._on_timeline_leave)
        self._list_box.add_controller(motion)

        click = Gtk.GestureClick()
        click.connect("released", self._on_timeline_click)
        self._list_box.add_controller(click)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_timeline_key)
        self._list_box.add_controller(key)

    def _build_empty_state(self) -> Gtk.Widget:
        status = Adw.StatusPage()
        status.add_css_class("tz-empty-state")
        status.set_icon_name("globe-symbolic")
        status.set_title("No Timezones")
        status.set_description("Add a city to keep track of the time where it matters to you.")

        btn = Gtk.Button(label="Add Timezone")
        btn.add_css_class("pill")
        btn.add_css_class("suggested-action")
        btn.set_halign(Gtk.Align.CENTER)
        btn.connect("clicked", self._on_add_clicked)
        status.set_child(btn)
        return status

    def _build_menu_button(self) -> Gtk.MenuButton:
        menu = Gio.Menu()
        menu.append("Preferences", "win.preferences")
        menu.append("Keyboard Shortcuts", "win.shortcuts")
        menu.append("About Timezones", "win.about")

        btn = Gtk.MenuButton()
        btn.set_icon_name("open-menu-symbolic")
        btn.add_css_class("flat")
        btn.set_menu_model(menu)
        return btn

    def _install_actions(self) -> None:
        for name, cb in (
            ("preferences", self._on_preferences),
            ("shortcuts", self._on_shortcuts),
            ("about", self._on_about),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", cb)
            self.add_action(action)

    # -- Row management -------------------------------------------------------

    def _effective_at(self) -> datetime:
        real_now = datetime.now().astimezone()
        if self._viewing_date is None:
            return real_now
        ref = self._model.reference
        ref_tz = ZoneInfo(ref.tz) if ref else real_now.tzinfo
        local_real = real_now.astimezone(ref_tz)
        return local_real.replace(
            year=self._viewing_date.year,
            month=self._viewing_date.month,
            day=self._viewing_date.day,
        )

    def _rebuild_rows(self) -> None:
        child = self._list_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._list_box.remove(child)
            child = nxt

        at = self._effective_at()
        n = len(self._model.cities)
        for i, city in enumerate(self._model.cities):
            row = TimezoneRow(city)
            row.connect("set-reference", self._on_row_set_reference)
            row.connect("edit-label", self._on_row_edit_label)
            row.connect("move-up", self._on_row_move_up)
            row.connect("move-down", self._on_row_move_down)
            row.connect("remove-row", self._on_row_remove)
            row.connect("reorder", self._on_row_reorder)
            row.set_move_enabled(i > 0, i < n - 1)
            row.update(self._model, self._fmt_24h, self._show_offsets, self._show_daynight, at)
            self._list_box.append(row)

        first_row = self._list_box.get_first_child()
        self._cursor.set_anchor(first_row.get_timeline() if first_row else None)
        self._update_empty_state()
        self._grid_date = self._current_grid_date()
        self._update_cursor_display()
        self._update_banner()

    def _update_empty_state(self) -> None:
        empty = not self._model.cities
        self._content_stack.set_visible_child_name("empty" if empty else "list")
        # Nothing left to look at on another day, so drop the date the user
        # had jumped to: keeping it would leave a hidden "viewing" state that
        # silently reappears the moment they add their first timezone back.
        if empty:
            self._viewing_date = None
        self._date_btn.set_sensitive(not empty)

    def _current_grid_date(self) -> date:
        """The calendar date the 24-cell grid currently represents. Only a
        change here (i.e. real midnight passing) warrants tearing down and
        rebuilding every row's timeline — not the routine per-tick refresh."""
        if self._viewing_date is not None:
            return self._viewing_date
        ref = self._model.reference
        now = datetime.now().astimezone()
        return tzinfo.local_now(ref.tz, now).date() if ref else now.date()

    def _refresh_rows(self) -> None:
        # Lightweight: only the time/date labels, never the 24-cell grid
        # (day/night tint, markers, date-flags, day-break) — that grid
        # doesn't change from one tick to the next, only from one calendar
        # day to the next (handled separately in _on_tick via _grid_date).
        at = self._effective_at()
        row = self._list_box.get_first_child()
        while row is not None:
            row.update_time_display(self._model, self._fmt_24h, at)
            row = row.get_next_sibling()

    def _refresh_preview_rows(self, instant: datetime) -> None:
        row = self._list_box.get_first_child()
        while row is not None:
            row.update_time_display(self._model, self._fmt_24h, instant, previewing=True)
            row = row.get_next_sibling()

    # -- Now-line / hover-scrub cursor -----------------------------------------

    def _anchor_timeline(self):
        first_row = self._list_box.get_first_child()
        return first_row.get_timeline() if first_row else None

    def _column_fraction_for_x(self, x: float) -> float | None:
        anchor = self._anchor_timeline()
        if anchor is None:
            return None
        ok, rect = anchor.compute_bounds(self._list_box)
        if not ok or rect.size.width <= 0:
            return None
        local_x = x - rect.origin.x
        if local_x < 0 or local_x > rect.size.width:
            return None
        # The strip is 24 equal one-hour cells covering [00:00, 24:00), so x
        # maps straight onto the day — the left edge of cell C is C o'clock
        # and its right edge is the next hour.
        return max(0.0, min(_MAX_COLUMN, (local_x / rect.size.width) * 24.0))

    @staticmethod
    def _snap_column(column: float) -> float:
        return round(column * 4) / 4  # nearest 15 minutes

    def _instant_for_column(self, column: float) -> datetime:
        return self._model.column_instant(column, self._effective_at())

    def _update_cursor_display(self) -> None:
        is_today = self._viewing_date is None or self._viewing_date == date.today()
        ref = self._model.reference

        if is_today and ref is not None:
            self._cursor.update_now(self._model.now_column(datetime.now().astimezone()), True)
        else:
            self._cursor.update_now(0.0, False)

        # Once pinned, further hovering does NOT move the preview — otherwise
        # the pinned pill (and its "back to now" button) would jump away the
        # instant the pointer crosses the timeline on its way to click it.
        # Pinning is a deliberate "park here" action; only a new click (or
        # explicit unpin) should change what's shown while it's active.
        active_column = None
        if self._pinned:
            active_column = self._pinned_column
        elif self._hovering:
            active_column = self._hover_column

        if active_column is None or ref is None:
            self._cursor.update_scrub(0.0, False, False)
            self._refresh_rows()
            return

        snapped = self._snap_column(active_column)
        instant = self._instant_for_column(snapped)
        local = tzinfo.local_now(ref.tz, instant)
        text = local.strftime("%H:%M") if self._fmt_24h else local.strftime("%-I:%M %p")
        self._cursor.update_scrub(active_column, True, self._pinned, text)
        self._refresh_preview_rows(instant)

    def _on_timeline_motion(self, _controller, x: float, _y: float) -> None:
        fraction = self._column_fraction_for_x(x)
        self._hovering = fraction is not None
        if fraction is not None:
            self._hover_column = fraction
        self._update_cursor_display()

    def _on_timeline_leave(self, _controller) -> None:
        self._hovering = False
        self._update_cursor_display()

    def _on_timeline_click(self, _gesture, _n_press: int, x: float, _y: float) -> None:
        fraction = self._column_fraction_for_x(x)
        if fraction is None:
            return
        self._pinned = True
        self._pinned_column = self._snap_column(fraction)
        self._update_cursor_display()

    def _on_timeline_key(self, _controller, keyval: int, _keycode: int, _state) -> bool:
        if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left, Gdk.KEY_Right, Gdk.KEY_KP_Right):
            base = (
                self._hover_column
                if self._hovering
                else (self._pinned_column if self._pinned else self._model.now_column())
            )
            step = -_SCRUB_STEP if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left) else _SCRUB_STEP
            self._hover_column = max(0.0, min(_MAX_COLUMN, base + step))
            self._hovering = True
            self._update_cursor_display()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space) and self._hovering:
            self._pinned = True
            self._pinned_column = self._snap_column(self._hover_column)
            self._update_cursor_display()
            return True
        if keyval == Gdk.KEY_Escape:
            self._hovering = False
            self._pinned = False
            self._pinned_column = None
            self._update_cursor_display()
            return True
        return False

    def _on_unpin_requested(self, *_args) -> None:
        # "Back to now" is a full reset, not just a pin release: the pointer
        # is necessarily still over the timeline right after this click (it
        # had to be, to hit the button), so leaving `_hovering` set would
        # make the display fall straight through to a live hover preview at
        # that same spot — indistinguishable from "clicking × just picked a
        # different time." Clearing it forces a real mouse-move before any
        # preview reappears.
        self._pinned = False
        self._pinned_column = None
        self._hovering = False
        self._update_cursor_display()

    def _update_banner(self) -> None:
        if self._viewing_date is None or self._viewing_date == date.today():
            self._banner.set_revealed(False)
        else:
            label = self._viewing_date.strftime("%a, %b %-d")
            self._banner.set_title(f"Viewing {label}")
            self._banner.set_revealed(True)

    def _persist(self) -> None:
        save_cities(self._model.cities)

    def _on_tick(self) -> bool:
        if self._grid_date != self._current_grid_date():
            self._rebuild_rows()
        else:
            self._update_cursor_display()
        return True

    # -- Header actions ------------------------------------------------------

    def _on_add_clicked(self, *_args) -> None:
        existing = {c.tz for c in self._model.cities}
        dialog = AddTimezoneDialog(existing)
        dialog.connect("timezone-added", self._on_timezone_added)
        dialog.present(self)

    def _on_timezone_added(self, _dialog: AddTimezoneDialog, tz_id: str) -> None:
        if any(c.tz == tz_id for c in self._model.cities):
            return
        self._model.cities.append(City(tz=tz_id))
        self._persist()
        self._rebuild_rows()

    def _on_date_selected(self, _popover: DatePopover, year: int, month: int, day: int) -> None:
        picked = date(year, month, day)
        self._viewing_date = None if picked == date.today() else picked
        self._rebuild_rows()

    def _on_banner_jump_today(self, *_args) -> None:
        self._viewing_date = None
        self._rebuild_rows()

    def _on_fmt_toggled(self, group: Adw.ToggleGroup, _pspec) -> None:
        self._fmt_24h = group.get_active_name() == "24h"
        self._settings.set_bool("fmt-24h", self._fmt_24h)
        if self._preferences is not None:
            self._preferences.sync_fmt_24h(self._fmt_24h)
        # Full rebuild, not _refresh_rows: the hour numbers live in the 24-cell
        # grid, which the lightweight refresh deliberately leaves alone.
        self._rebuild_rows()

    # -- Row signal handlers ---------------------------------------------------

    def _on_row_set_reference(self, row: TimezoneRow) -> None:
        self._model.set_reference(row.city)
        self._persist()
        self._rebuild_rows()

    def _on_row_edit_label(self, row: TimezoneRow) -> None:
        dialog = Adw.AlertDialog(heading="Edit label", body=f"Set a label for {tzinfo.city_name(row.city.tz)}")
        entry = Gtk.Entry()
        entry.set_text(row.city.label)
        entry.set_activates_default(True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clear", "Clear")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def on_response(_d: Adw.AlertDialog, response: str) -> None:
            if response == "save":
                row.city.label = entry.get_text().strip()
            elif response == "clear":
                row.city.label = ""
            else:
                return
            self._persist()
            self._rebuild_rows()

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_row_move_up(self, row: TimezoneRow) -> None:
        self._model.move_up(row.city)
        self._persist()
        self._rebuild_rows()

    def _on_row_move_down(self, row: TimezoneRow) -> None:
        self._model.move_down(row.city)
        self._persist()
        self._rebuild_rows()

    def _on_row_remove(self, row: TimezoneRow) -> None:
        was_reference = row.city.is_reference
        self._model.cities.remove(row.city)
        if was_reference and self._model.cities:
            self._model.cities[0].is_reference = True
        self._persist()
        self._rebuild_rows()

    def _on_row_reorder(self, _row: TimezoneRow, source_tz: str, target_tz: str) -> None:
        cities = self._model.cities
        try:
            source = next(c for c in cities if c.tz == source_tz)
            target_index = next(i for i, c in enumerate(cities) if c.tz == target_tz)
        except StopIteration:
            return
        cities.remove(source)
        target_index = next(i for i, c in enumerate(cities) if c.tz == target_tz)
        cities.insert(target_index, source)
        self._persist()
        self._rebuild_rows()

    # -- Menu actions -----------------------------------------------------------

    def _on_preferences(self, *_args) -> None:
        dialog = PreferencesDialog(
            theme_mode=self._settings.get_string("theme-mode", "system"),
            fmt_24h=self._fmt_24h,
            show_offsets=self._show_offsets,
            show_daynight=self._show_daynight,
            compact_rows=self._compact_rows,
        )
        dialog.connect("theme-changed", self._on_theme_changed)
        dialog.connect("fmt-24h-changed", self._on_prefs_fmt_changed)
        dialog.connect("show-offsets-changed", self._on_show_offsets_changed)
        dialog.connect("show-daynight-changed", self._on_show_daynight_changed)
        dialog.connect("compact-rows-changed", self._on_compact_rows_changed)
        dialog.connect("reorder-requested", self._on_reorder_requested)
        self._preferences = dialog
        dialog.connect("closed", lambda *_a: setattr(self, "_preferences", None))
        dialog.present(self)

    def _on_shortcuts(self, *_args) -> None:
        dialog = Adw.AlertDialog(
            heading="Keyboard Shortcuts",
            body="Add timezone: Ctrl+N\nPreferences: Ctrl+,\nQuit: Ctrl+Q",
        )
        dialog.add_response("ok", "Close")
        dialog.present(self)

    def _on_about(self, *_args) -> None:
        about = Adw.AboutDialog(
            application_name="Timezones",
            application_icon="com.hernantz.timezones",
            version="0.1.0",
            developer_name="Hernan Tz",
            license_type=Gtk.License.GPL_3_0,
            comments="Keep track of the time in cities that matter to you.",
        )
        about.present(self)

    def _on_reorder_requested(self, *_args) -> None:
        self._open_reorder_dialog()

    def _open_reorder_dialog(self) -> None:
        dialog = Adw.Dialog()
        dialog.set_title("Reorder Timezones")
        dialog.set_content_width(360)
        dialog.set_content_height(440)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(Adw.HeaderBar())

        listbox = Gtk.ListBox()
        listbox.add_css_class("boxed-list")
        listbox.set_margin_top(12)
        listbox.set_margin_bottom(12)
        listbox.set_margin_start(12)
        listbox.set_margin_end(12)

        def populate() -> None:
            child = listbox.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                listbox.remove(child)
                child = nxt
            n = len(self._model.cities)
            for i, city in enumerate(self._model.cities):
                tz_row = Adw.ActionRow(title=tzinfo.city_name(city.tz), subtitle=city.tz)
                up_btn = Gtk.Button.new_from_icon_name("go-up-symbolic")
                up_btn.add_css_class("flat")
                up_btn.set_sensitive(i > 0)
                down_btn = Gtk.Button.new_from_icon_name("go-down-symbolic")
                down_btn.add_css_class("flat")
                down_btn.set_sensitive(i < n - 1)

                def move(_b, c=city, delta=-1) -> None:
                    idx = self._model.cities.index(c)
                    if 0 <= idx + delta < len(self._model.cities):
                        self._model.cities[idx], self._model.cities[idx + delta] = (
                            self._model.cities[idx + delta],
                            self._model.cities[idx],
                        )
                        self._persist()
                        self._rebuild_rows()
                        populate()

                up_btn.connect("clicked", move, city, -1)
                down_btn.connect("clicked", move, city, 1)
                tz_row.add_suffix(up_btn)
                tz_row.add_suffix(down_btn)
                listbox.append(tz_row)

        populate()
        toolbar_view.set_content(listbox)
        dialog.set_child(toolbar_view)
        dialog.present(self)

    # -- Theme ------------------------------------------------------------------

    def _on_theme_changed(self, _dialog: PreferencesDialog, mode: str) -> None:
        self._settings.set_string("theme-mode", mode)
        self._apply_theme_mode(mode)

    def _apply_theme_mode(self, mode: str) -> None:
        sm = Adw.StyleManager.get_default()
        if mode == "light":
            sm.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        elif mode == "dark":
            sm.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        else:
            sm.set_color_scheme(Adw.ColorScheme.DEFAULT)

    def _on_style_dark_changed(self, *_args) -> None:
        self._sync_dark_class()

    def _sync_dark_class(self) -> None:
        if Adw.StyleManager.get_default().get_dark():
            self.add_css_class("dark")
        else:
            self.remove_css_class("dark")

    def _on_prefs_fmt_changed(self, _dialog: PreferencesDialog, fmt_24h: bool) -> None:
        # The header toggle group is the single source of truth: flipping it
        # runs _on_fmt_toggled, which persists the setting and rebuilds.
        self._fmt_group.set_active_name("24h" if fmt_24h else "12h")

    def _on_show_offsets_changed(self, _dialog: PreferencesDialog, value: bool) -> None:
        self._show_offsets = value
        self._settings.set_bool("show-offsets", value)
        self._refresh_rows()

    def _on_show_daynight_changed(self, _dialog: PreferencesDialog, value: bool) -> None:
        self._show_daynight = value
        self._settings.set_bool("show-daynight", value)
        self._rebuild_rows()

    def _on_compact_rows_changed(self, _dialog: PreferencesDialog, value: bool) -> None:
        self._compact_rows = value
        self._settings.set_bool("compact-rows", value)
        if value:
            self._list_box.add_css_class("compact")
        else:
            self._list_box.remove_css_class("compact")
