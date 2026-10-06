from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from . import tzinfo_helpers as tzinfo
from .add_dialog import AddTimezoneDialog
from .const import APP_ID, VERSION
from .date_popover import DatePopover
from .i18n import C_, N_, _, format_clock, format_day, format_day_year, ngettext
from .model import City, ClockModel
from .persistence import LoadedCities, Settings, load_cities, save_cities
from .preferences import PreferencesDialog
from .row import TimezoneRow
from .share import EVENT_MINUTES, clipboard_text, launch_ics, write_ics
from .timeline import TimelineStrip

_SCRUB_STEP = 0.25  # 15 minutes, matches _snap_column()
_MAX_COLUMN = 24.0 - _SCRUB_STEP  # 23:45 — last snappable slot still inside the day

# Labels are marked here and translated when the defaults are copied: from
# then on they are the user's own text, saved as whatever language they were in.
_DEFAULT_CITIES = [
    City(tz="Europe/London", label=N_("You"), is_reference=True),
    City(tz="Africa/Cairo", label=N_("Family")),
    City(tz="Europe/Moscow", label=N_("Team")),
    City(tz="Pacific/Auckland"),
]

_TICK_SECONDS = 15

# Beyond this the timeline stops growing and the surplus becomes side margins.
_MAX_LIST_WIDTH = 1180
# Below this the side-by-side row can no longer hold its fixed columns plus a
# legible 24-cell strip, so the row switches to its stacked state instead of
# being squeezed further. 880 is not a taste call: the wide row's own minimum
# is 878px (26+180+118 of fixed columns, the kebab, and the strip's 456px
# floor of 24 legible hour cells), so anything narrower is a window GTK cannot
# actually satisfy — it warns and overflows rather than shrinking. Stacking
# has to take over at the floor, not below it.
_NARROW_WIDTH = 880


class ScrubList(Gtk.Box):
    """The rows' container, made into a real Tab stop.

    `set_focusable(True)` alone is not enough: GtkBox overrides the `focus`
    vfunc to hand traversal straight to its children, so Tab walked over the
    list to the row buttons inside it and the keyboard scrub was reachable
    only by clicking an hour first. `grab_focus` is *not* delegated the same
    way, which is why the click path worked and Tab did not.

    Taking focus here first, then deferring to the normal child walk on the
    way out, makes the whole list behave like the single control it is — the
    same deal a GtkScale offers: focus it, then arrow along it.
    """

    def do_focus(self, direction: Gtk.DirectionType) -> bool:
        # `get_focus_child()` is what separates arriving from leaving: GTK
        # calls this again when focus walks back out of a row's buttons, and
        # claiming it there too would bounce Tab between the list and its
        # first row forever.
        arriving = self.get_focus_child() is None and not self.is_focus()
        tabbing = direction in (
            Gtk.DirectionType.TAB_FORWARD,
            Gtk.DirectionType.TAB_BACKWARD,
        )
        if arriving and tabbing and self.get_focusable():
            return self.grab_focus()
        return Gtk.Box.do_focus(self, direction)


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
        self._viewing_date: date | None = None
        self._preferences: PreferencesDialog | None = None

        self._narrow = False
        self._selection_action_labels: list[Gtk.Label] = []
        self._hovering = False
        self._hover_column = 0.0
        # The keyboard's own scrub position, deliberately not shared with the
        # hover: arrow presses used to write `_hover_column`, so the pointer
        # overwrote them the moment it reported a position — including the
        # motion GTK delivers over a *stationary* pointer when the preview
        # labels underneath it change size. None means the keyboard is not
        # driving the cursor.
        self._key_column: float | None = None
        self._pointer_xy: tuple[float, float] | None = None
        self._pinned = False
        self._pinned_column: float | None = None
        self._grid_date: date | None = None
        # Rows removed while the current undo toast is up, as (index, city)
        # in removal order.
        self._removed: list[tuple[int, City]] = []
        self._removed_reference: City | None = None
        self._removed_toast: Adw.Toast | None = None

        defaults = [
            City(tz=d.tz, label=_(d.label) if d.label else "", is_reference=d.is_reference)
            for d in _DEFAULT_CITIES
        ]
        loaded = load_cities(defaults)
        self._model = ClockModel(loaded.cities)

        self._install_actions()
        self._build_ui()
        self._apply_theme_mode(self._settings.get_string("theme-mode", "system"))
        Adw.StyleManager.get_default().connect("notify::dark", self._on_style_dark_changed)
        self._sync_dark_class()

        self._install_breakpoint()

        self._rebuild_rows()
        GLib.timeout_add_seconds(_TICK_SECONDS, self._on_tick)
        self._report_load_problem(loaded)

    # -- UI construction ----------------------------------------------------

    def _build_ui(self) -> None:
        toolbar_view = Adw.ToolbarView()

        header = Adw.HeaderBar()
        header.add_css_class("tz-headerbar")
        header.set_decoration_layout(":close")

        title_label = Gtk.Label(label=_("Timezones"))
        title_label.add_css_class("title")
        header.set_title_widget(title_label)

        add_btn = Gtk.Button()
        add_btn.set_icon_name("list-add-symbolic")
        add_btn.set_tooltip_text(_("Add Timezone"))
        add_btn.add_css_class("flat")
        add_btn.set_action_name("win.new")
        header.pack_start(add_btn)

        self._date_btn = Gtk.MenuButton()
        self._date_btn.set_icon_name("x-office-calendar-symbolic")
        self._date_btn.set_tooltip_text(_("Jump to Date"))
        self._date_btn.add_css_class("flat")
        self._date_popover = DatePopover()
        self._date_popover.connect("date-selected", self._on_date_selected)
        self._date_btn.set_popover(self._date_popover)
        header.pack_start(self._date_btn)

        # Only an escape hatch: hidden while the window already shows today,
        # so it reads as "you are somewhere else" rather than as a permanent
        # control.
        self._today_btn = Gtk.Button(label=_("Today"))
        self._today_btn.set_tooltip_text(_("Back to Today"))
        self._today_btn.add_css_class("flat")
        self._today_btn.add_css_class("tz-today-btn")
        self._today_btn.set_visible(False)
        self._today_btn.set_action_name("win.today")
        header.pack_start(self._today_btn)

        self._fmt_group = Adw.ToggleGroup()
        toggle_24 = Adw.Toggle(name="24h", label=C_("clock format", "24h"))
        toggle_12 = Adw.Toggle(name="12h", label=C_("clock format", "12h"))
        self._fmt_group.add(toggle_24)
        self._fmt_group.add(toggle_12)
        self._fmt_group.set_active_name("24h" if self._fmt_24h else "12h")
        self._fmt_group.connect("notify::active", self._on_fmt_toggled)
        header.pack_end(self._build_menu_button())
        header.pack_end(self._fmt_group)

        toolbar_view.add_top_bar(header)

        toolbar_view.add_top_bar(self._build_selection_bar())

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        # Vertical only: a taller window shows more rows, a shorter one scrolls
        # them. Horizontally there is nothing to scroll — past the breakpoint
        # the rows restack rather than overflow.
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._list_box = ScrubList(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self._list_box.set_margin_top(10)
        self._list_box.set_margin_bottom(18)
        self._list_box.set_margin_start(16)
        self._list_box.set_margin_end(16)
        # Rows are their own height; spare vertical space belongs to the list,
        # not to the rows, so it collects at the bottom instead of inflating
        # every card.
        self._list_box.set_valign(Gtk.Align.START)

        # Past a generous width extra space becomes margin rather than wider
        # hours: an hour on an ultrawide should read at roughly the same scale
        # as an hour on a laptop, which is the whole basis for glancing down
        # the list and comparing.
        clamp = Adw.Clamp()
        clamp.set_maximum_size(_MAX_LIST_WIDTH)
        clamp.set_tightening_threshold(_MAX_LIST_WIDTH)
        clamp.set_child(self._list_box)
        scrolled.set_child(clamp)

        self._content_stack = Gtk.Stack()
        self._content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._content_stack.add_named(scrolled, "list")
        self._content_stack.add_named(self._build_empty_state(), "empty")

        # A toast overlay around the content, not the whole toolbar view, so
        # a toast rises over the list and never over the header bar.
        self._toasts = Adw.ToastOverlay()
        self._toasts.set_child(self._content_stack)
        toolbar_view.set_content(self._toasts)
        self.set_content(toolbar_view)

        self._list_box.set_focusable(True)
        self._list_box.add_css_class("tz-scrub-list")

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

        # Escape discards the selection wherever focus happens to be. The
        # controller above only sees keys while the list itself has focus, and
        # after picking a date focus sits on the calendar button instead — so
        # the one key whose whole job is "get me out of this" was unreachable
        # exactly when a selection had outlived a date jump. Global scope puts
        # it on the window; popovers and dialogs are their own roots, so their
        # own Escape (close me) still runs first.
        escape = Gtk.ShortcutController()
        escape.set_scope(Gtk.ShortcutScope.GLOBAL)
        escape.add_shortcut(
            Gtk.Shortcut(
                trigger=Gtk.ShortcutTrigger.parse_string("Escape"),
                action=Gtk.CallbackAction.new(self._on_escape),
            )
        )
        self.add_controller(escape)

    def _install_breakpoint(self) -> None:
        """One breakpoint decides which state every row is in — whether the
        narrowness comes from a phone or from someone dragging the window in."""
        condition = Adw.BreakpointCondition.new_length(
            Adw.BreakpointConditionLengthType.MAX_WIDTH,
            _NARROW_WIDTH,
            Adw.LengthUnit.PX,
        )
        breakpoint_ = Adw.Breakpoint.new(condition)
        breakpoint_.connect("apply", lambda *_a: self._set_narrow(True))
        breakpoint_.connect("unapply", lambda *_a: self._set_narrow(False))
        self.add_breakpoint(breakpoint_)

    def _set_narrow(self, narrow: bool) -> None:
        self._narrow = narrow
        # The format toggle is the one header control that is pure preference:
        # it has a home in Preferences, and at phone width the bar cannot hold
        # both it and the controls that are about *this* view. Dropping it is
        # also what gives "Today" — which only appears when the list is parked
        # on another date, and is the way back — room to stay a word.
        self._fmt_group.set_visible(not narrow)
        # Narrow drops the action names and leaves their icons. The bar's own
        # reading is the one thing on it that cannot be guessed from context,
        # so it is what keeps the width when there isn't enough to go round.
        for label in self._selection_action_labels:
            label.set_visible(not narrow)
        row = self._list_box.get_first_child()
        while row is not None:
            row.set_narrow(narrow)
            row = row.get_next_sibling()

    def _build_selection_bar(self) -> Gtk.Widget:
        """The bar that names the instant the timeline is parked on.

        A top bar rather than a marker floating over the strips: the reading is
        wanted *while* comparing rows, and every row already shows its own
        local time for that instant — what the list can't say for itself is
        which instant is being previewed and how to get back out of it. Sits
        with the "Viewing <date>" banner above it, and reads the same way: a
        statement about what the whole list is currently showing.
        """
        self._selection_label = Gtk.Label()
        self._selection_label.add_css_class("tz-selection-text")
        self._selection_label.set_ellipsize(Pango.EllipsizeMode.END)

        close = self._selection_button(
            "window-close-symbolic", _("Discard selected time"), self._on_unpin_requested
        )

        # The two hand-offs sit at the start and the discard stays at the end:
        # everything that *does something with* this instant on one side, the
        # one thing that throws it away on the other, so a mis-aimed click
        # between them costs a stray copy rather than the selection.
        #
        # Named rather than icon-only, unlike the close: a bare glyph is only
        # self-evident for the action the reader already expects, and nothing
        # about a parked hour suggests it can leave the app. The tooltips still
        # carry the detail the labels drop (which times, how long the event).
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        actions.append(
            self._selection_button(
                "edit-copy-symbolic",
                _("Copy all times to the clipboard"),
                self._on_copy_selection,
                label=_("Copy"),
            )
        )
        actions.append(
            self._selection_button(
                "x-office-calendar-symbolic",
                ngettext(
                    "Save a {n}-minute event to your calendar",
                    "Save a {n}-minute event to your calendar",
                    EVENT_MINUTES,
                ).format(n=EVENT_MINUTES),
                self._on_calendar_selection,
                label=_("Save event"),
            )
        )

        bar = Gtk.CenterBox()
        bar.add_css_class("tz-selection-bar")
        bar.set_start_widget(actions)
        bar.set_center_widget(self._selection_label)
        bar.set_end_widget(close)

        # Revealed rather than merely hidden, so the list slides down to make
        # room the way it does for the date banner instead of jumping.
        self._selection_bar = Gtk.Revealer()
        self._selection_bar.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._selection_bar.set_child(bar)
        self._selection_bar.set_reveal_child(False)
        return self._selection_bar

    def _selection_button(
        self, icon: str, tooltip: str, on_click, label: str | None = None
    ) -> Gtk.Button:
        """One control in the selection bar: circular and bare when it is only
        an icon, a pill with its name beside it when it has one."""
        button = Gtk.Button()
        button.add_css_class("tz-selection-action")
        button.add_css_class("flat")
        button.set_tooltip_text(tooltip)
        button.set_valign(Gtk.Align.CENTER)
        button.connect("clicked", on_click)

        if label is None:
            button.add_css_class("circular")
            button.set_icon_name(icon)
            return button

        text = Gtk.Label(label=label)
        text.add_css_class("tz-selection-action-label")
        # Kept so the narrow layout can drop back to icons: the bar's centred
        # reading is the thing that must survive a squeeze, and two names plus
        # a date and time do not fit a phone-width window.
        self._selection_action_labels.append(text)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        content.append(Gtk.Image.new_from_icon_name(icon))
        content.append(text)
        button.set_child(content)
        return button

    # -- Sharing the parked instant ------------------------------------------

    def _selected_instant(self) -> datetime | None:
        """The instant the buttons act on — only ever a *parked* one.

        Deliberately not `_keyboard_base_column`'s falling-back chain: those
        buttons are only on screen while something is pinned, and a copy that
        quietly fell back to "now" because the pin had just been discarded
        would be wrong in a way the clipboard doesn't show you.
        """
        if not self._pinned or self._pinned_column is None:
            return None
        return self._instant_for_column(self._pinned_column)

    def _on_copy_selection(self, _button: Gtk.Button) -> None:
        instant = self._selected_instant()
        if instant is None:
            return
        text = clipboard_text(self._model, instant, self._fmt_24h)
        if not text:
            return
        self.get_clipboard().set(text)
        self._toasts.add_toast(Adw.Toast.new(_("Times copied")))

    def _on_calendar_selection(self, _button: Gtk.Button) -> None:
        instant = self._selected_instant()
        if instant is None:
            return
        try:
            file = write_ics(self._model, instant, self._fmt_24h)
        except OSError as error:
            self._toasts.add_toast(
                Adw.Toast.new(_("Couldn't write the event: {error}").format(error=error.strerror))
            )
            return
        launch_ics(
            self,
            file,
            lambda message: self._toasts.add_toast(
                Adw.Toast.new(_("Couldn't open a calendar: {error}").format(error=message))
            ),
        )

    def _build_empty_state(self) -> Gtk.Widget:
        status = Adw.StatusPage()
        status.add_css_class("tz-empty-state")
        status.set_icon_name("globe-symbolic")
        status.set_title(_("No Timezones"))
        status.set_description(_("Add a city to keep track of the time where it matters to you."))

        btn = Gtk.Button(label=_("Add Timezone"))
        btn.add_css_class("pill")
        btn.add_css_class("suggested-action")
        btn.set_halign(Gtk.Align.CENTER)
        btn.connect("clicked", self._on_add_clicked)
        status.set_child(btn)
        return status

    def _build_menu_button(self) -> Gtk.MenuButton:
        menu = Gio.Menu()
        menu.append(_("Preferences"), "win.preferences")
        menu.append(_("Keyboard Shortcuts"), "win.shortcuts")
        menu.append(_("About Timezones"), "win.about")

        btn = Gtk.MenuButton()
        btn.set_icon_name("open-menu-symbolic")
        btn.set_tooltip_text(_("Main Menu"))
        btn.add_css_class("flat")
        btn.set_menu_model(menu)
        return btn

    def _install_actions(self) -> None:
        for name, cb in (
            ("new", self._on_add_clicked),
            ("today", self._on_jump_today),
            ("preferences", self._on_preferences),
            ("shortcuts", self._on_shortcuts),
            ("about", self._on_about),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", cb)
            self.add_action(action)
            if name == "today":
                self._today_action = action

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

    def _make_row(self, city: City) -> TimezoneRow:
        row = TimezoneRow(city)
        row.connect("set-reference", self._on_row_set_reference)
        row.connect("edit-label", self._on_row_edit_label)
        row.connect("move-up", self._on_row_move_up)
        row.connect("move-down", self._on_row_move_down)
        row.connect("remove-row", self._on_row_remove)
        row.connect("reorder", self._on_row_reorder)
        return row

    def _rebuild_rows(self) -> None:
        """Bring the list in line with the model, reusing the rows already up.

        Every one of the fifteen callers used to mean "throw away every row and
        every one of its 24 hour cells and build them again" — including a
        reorder, which changes no cell at all, and the up/down buttons in the
        reorder dialog, where the cost lands on every click. Rows are keyed by
        timezone and moved rather than rebuilt; `TimezoneRow.update()` and
        `TimelineStrip.update()` are both written to be re-run on a live row.
        """
        existing: dict[tuple, TimezoneRow] = {}
        child = self._list_box.get_first_child()
        while child is not None:
            existing[child.city.key] = child
            child = child.get_next_sibling()

        at = self._effective_at()
        n = len(self._model.cities)
        previous: TimezoneRow | None = None
        for i, city in enumerate(self._model.cities):
            row = existing.pop(city.key, None)
            if row is None:
                row = self._make_row(city)
                self._list_box.append(row)
            else:
                # The model may hand back a fresh City for the same zone (a
                # reload, say); the row's own reference has to follow it or it
                # keeps reporting the old label and reference flag.
                row.city = city
            if row.get_prev_sibling() is not previous:
                self._list_box.reorder_child_after(row, previous)
            row.set_move_enabled(i > 0, i < n - 1)
            row.update(self._model, self._fmt_24h, self._show_offsets, self._show_daynight, at)
            row.set_narrow(self._narrow)
            previous = row

        for stale in existing.values():
            self._list_box.remove(stale)

        self._update_empty_state()
        self._grid_date = self._current_grid_date()
        self._update_cursor_display()
        self._update_today_btn()

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

    def _update_now_line(self, column: float | None) -> None:
        """Hand the now-line to every row's own strip, so it can only ever
        cross hours — never the name, clock and kebab a stacked row puts above
        its strip."""
        row = self._list_box.get_first_child()
        while row is not None:
            row.set_now(column)
            row = row.get_next_sibling()

    def _update_scrub_line(self, column: float | None) -> None:
        """Same for the scrub line — the overlay keeps only its pill."""
        row = self._list_box.get_first_child()
        while row is not None:
            row.set_scrub(column)
            row = row.get_next_sibling()

    def _update_selection_bar(self, instant: datetime | None) -> None:
        ref = self._model.reference
        if instant is None or ref is None:
            self._selection_bar.set_reveal_child(False)
            return
        # The reference zone's reading, like every other number the timeline
        # is keyed to — each row states the same instant in its own terms
        # just below.
        local = tzinfo.local_now(ref.tz, instant)
        # The year only once the calendar has carried the view out of this
        # one: nothing else on screen says which year is being planned for.
        day = format_day(local) if local.year == date.today().year else format_day_year(local)
        self._selection_label.set_label(f"{day} · {format_clock(local, self._fmt_24h)}")
        self._selection_bar.set_reveal_child(True)

    def _timeline_at(self, x: float, y: float) -> TimelineStrip | None:
        """The strip under the pointer, or None when it is anywhere else.

        Asking the widget tree, rather than testing the x range against the
        first strip: every strip spans the same columns, so an x test alone
        says "which hour" but never "an hour at all". Stacked, the name, the
        clock and the kebab sit directly above their own strip and share its
        x range — reading a time off them is meaningless, so the pointer
        crossing them must leave the scrub where it was rather than drag it
        along.
        """
        widget = self._list_box.pick(x, y, Gtk.PickFlags.DEFAULT)
        while widget is not None and widget is not self._list_box:
            if isinstance(widget, TimelineStrip):
                return widget
            widget = widget.get_parent()
        return None

    def _column_fraction_at(self, x: float, y: float) -> float | None:
        strip = self._timeline_at(x, y)
        if strip is None:
            return None
        ok, rect = strip.compute_bounds(self._list_box)
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

        now_column = (
            self._model.now_column(datetime.now().astimezone())
            if is_today and ref is not None
            else None
        )
        self._update_now_line(now_column)

        # Once pinned, further hovering does NOT move the preview — otherwise
        # the pinned pill (and its "back to now" button) would jump away the
        # instant the pointer crosses the timeline on its way to click it.
        # Pinning is a deliberate "park here" action; only a new click (or
        # explicit unpin) should change what's shown while it's active.
        active_column = None
        if self._pinned:
            active_column = self._pinned_column
        elif self._key_column is not None:
            active_column = self._key_column
        elif self._hovering:
            active_column = self._hover_column

        if active_column is None or ref is None:
            self._update_scrub_line(None)
            self._update_selection_bar(None)
            self._refresh_rows()
            return

        snapped = self._snap_column(active_column)
        instant = self._instant_for_column(snapped)
        self._update_scrub_line(active_column)
        # Only a parked instant gets the bar. A hover is already fully told by
        # the line and the row times moving under the pointer, and a bar that
        # appeared and vanished with every pass of the mouse would shove the
        # whole list up and down as it went.
        self._update_selection_bar(instant if self._pinned else None)
        self._refresh_preview_rows(instant)

    def _on_timeline_motion(self, _controller, x: float, y: float) -> None:
        # A motion event at coordinates the pointer already had is not the
        # user moving the mouse — it is the layout shifting underneath a
        # pointer that never left. Acting on those is what let a resting
        # pointer undo every arrow press.
        if self._pointer_xy == (x, y):
            return
        self._pointer_xy = (x, y)

        fraction = self._column_fraction_at(x, y)
        self._hovering = fraction is not None
        if fraction is not None:
            # A real mouse move is a handover: the pointer is the live input
            # again and the keyboard's parked column steps aside.
            self._key_column = None
            self._hover_column = fraction
        self._update_cursor_display()

    def _on_timeline_leave(self, _controller) -> None:
        self._pointer_xy = None
        self._hovering = False
        self._update_cursor_display()

    def _on_timeline_click(self, _gesture, _n_press: int, x: float, y: float) -> None:
        # Same rule as the hover: a click on a row's name or clock is not a
        # click on an hour, so it parks nothing.
        fraction = self._column_fraction_at(x, y)
        if fraction is None:
            return
        # Parking on an hour is the same intent as tabbing in, so the keyboard
        # scrub should be live straight afterwards: the arrow/Enter controller
        # only sees keys while the list holds focus, and nothing else ever
        # gives it focus. Past the early return above, so a click on a row's
        # name or kebab still doesn't pull focus.
        self._list_box.grab_focus()
        self._pinned = True
        self._pinned_column = self._snap_column(fraction)
        self._update_cursor_display()

    def _keyboard_base_column(self) -> float:
        """Where a keypress acts from, in falling order of how deliberate the
        source is: the keyboard's own column, then a parked selection, then the
        pointer, then simply now. Shared by the arrows and by Enter, so landing
        on the list by keyboard always has a defined position — Enter used to
        require a prior arrow press and silently declined otherwise, letting
        the key propagate to whatever came next in the tab order."""
        if self._key_column is not None:
            return self._key_column
        if self._pinned and self._pinned_column is not None:
            return self._pinned_column
        if self._hovering:
            return self._hover_column
        return self._model.now_column()

    def _on_timeline_key(self, _controller, keyval: int, _keycode: int, _state) -> bool:
        # The controller is on the list, so it also sees keys bubbling up out
        # of the rows' own buttons. Scrubbing only when the list itself holds
        # focus keeps Enter/Space with the kebab that has it, and stops the
        # arrows from scrubbing from a focus position that looks nothing like
        # the timeline.
        if not self._list_box.is_focus():
            return False
        if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left, Gdk.KEY_Right, Gdk.KEY_KP_Right):
            step = -_SCRUB_STEP if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left) else _SCRUB_STEP
            # Snapped first: a base inherited from the pointer or from "now" is
            # an arbitrary fraction of an hour, and stepping from it would walk
            # the cursor along 15-minute offsets from a ragged start. Arrow keys
            # should land on the same quarter-hours the click path snaps to.
            base = self._snap_column(self._keyboard_base_column())
            column = max(0.0, min(_MAX_COLUMN, base + step))
            if self._pinned:
                # Keep the park, move what is parked: arrows adjust a committed
                # selection in place rather than being ignored until it is
                # released, so nudging a pinned time does not mean unpinning,
                # re-scrubbing and pinning again.
                self._pinned_column = column
            else:
                self._key_column = column
            self._update_cursor_display()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            # Always claimed: a focused control that lets Enter fall through
            # hands it to the next widget in the tab order, which from here is
            # a row's kebab — so Enter appeared to open a menu instead.
            self._pinned = True
            self._pinned_column = self._snap_column(self._keyboard_base_column())
            self._key_column = None
            self._update_cursor_display()
            return True
        return False

    def _on_escape(self, _widget, _args) -> bool:
        """Only claims the key when there is something to discard, so Escape
        keeps its usual meaning everywhere else in the window."""
        if not (self._pinned or self._hovering or self._key_column is not None):
            return False
        self._on_unpin_requested()
        return True

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
        self._key_column = None
        self._update_cursor_display()

    def _update_today_btn(self) -> None:
        away = self._viewing_date is not None and self._viewing_date != date.today()
        self._today_btn.set_visible(away)
        # Disabling it too, so Ctrl+T while already on today is a no-op rather
        # than a pointless full rebuild of every row.
        self._today_action.set_enabled(away)

    def _persist(self) -> None:
        save_cities(self._model.cities)

    def _report_load_problem(self, loaded: LoadedCities) -> None:
        if loaded.newer:
            message = _("These timezones were saved by a newer version; changes won't be saved")
        elif loaded.broken_copy is not None:
            message = _("Couldn't read the saved timezones; the file was kept as {name}").format(
                name=loaded.broken_copy.name
            )
        else:
            return
        toast = Adw.Toast.new(message)
        # Stays until dismissed: it explains why the list looks the way it does.
        toast.set_timeout(0)
        self._toasts.add_toast(toast)

    def _on_tick(self) -> bool:
        if self._grid_date != self._current_grid_date():
            self._rebuild_rows()
        else:
            self._update_cursor_display()
        return True

    # -- Header actions ------------------------------------------------------

    def _on_add_clicked(self, *_args) -> None:
        existing = {c.key for c in self._model.cities}
        dialog = AddTimezoneDialog(existing)
        dialog.connect("timezone-added", self._on_timezone_added)
        dialog.present(self)

    def _on_timezone_added(
        self, _dialog: AddTimezoneDialog, tz_id: str, place: tzinfo.Place | None
    ) -> None:
        if any(c.key == (tz_id, place) for c in self._model.cities):
            return
        # The first zone added to an empty list has to carry the reference flag
        # itself: `ClockModel.reference` would fall back to it anyway, but the
        # row's styling and the saved file read the flag, not the fallback.
        self._model.cities.append(
            City(tz=tz_id, is_reference=not self._model.cities, place=place)
        )
        self._persist()
        self._rebuild_rows()

    def _on_date_selected(self, _popover: DatePopover, year: int, month: int, day: int) -> None:
        picked = date(year, month, day)
        self._viewing_date = None if picked == date.today() else picked
        self._rebuild_rows()

    def _on_jump_today(self, *_args) -> None:
        self._viewing_date = None
        self._date_popover.reset_to_today()
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
        dialog = Adw.AlertDialog(
            heading=_("Edit label"),
            body=_("Set a label for {city}").format(city=row.city.name),
        )
        entry = Gtk.Entry()
        entry.set_text(row.city.label)
        entry.set_activates_default(True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("_Cancel"))
        dialog.add_response("clear", _("C_lear"))
        dialog.add_response("save", _("_Save"))
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
        cities = self._model.cities
        city = row.city
        if self._removed_toast is None:
            # The reference as it stood before this run of removals, so undo
            # can hand the role back even after it was reassigned to cities[0].
            self._removed_reference = self._model.reference
        self._removed.append((cities.index(city), city))
        cities.remove(city)
        # Cleared even when the list is left empty: a stale flag riding along
        # in `_removed` would make undo bring back a second reference next to
        # a zone added from the empty state in the meantime.
        was_reference = city.is_reference
        city.is_reference = False
        if was_reference and cities:
            cities[0].is_reference = True
        # Saved now, not when the toast goes away: quitting with the toast
        # still up must not bring the row back on the next launch.
        self._persist()
        self._rebuild_rows()
        self._show_removed_toast()

    def _show_removed_toast(self) -> None:
        # One toast for a run of removals, retitled in place, rather than a
        # queue of toasts each waiting out its own timeout.
        count = len(self._removed)
        if count == 1:
            title = _("Removed {city}").format(city=self._removed[0][1].name)
        else:
            title = ngettext(
                "Removed {n} timezone", "Removed {n} timezones", count
            ).format(n=count)
        toast = self._removed_toast
        if toast is None:
            toast = Adw.Toast.new(title)
            toast.set_button_label(_("_Undo"))
            toast.set_use_markup(False)
            toast.connect("button-clicked", self._on_undo_remove)
            toast.connect("dismissed", self._on_removed_toast_dismissed)
            self._removed_toast = toast
        else:
            toast.set_title(title)
        # Re-adding a toast that is already showing restarts its timeout.
        self._toasts.add_toast(toast)

    def _on_removed_toast_dismissed(self, toast: Adw.Toast) -> None:
        if toast is self._removed_toast:
            self._removed_toast = None
            self._removed = []
            self._removed_reference = None

    def _on_undo_remove(self, _toast: Adw.Toast) -> None:
        cities = self._model.cities
        present = {c.key for c in cities}
        # Reverse order, so each index means what it did when it was taken.
        # Clamped, since rows may have been moved in the meantime; skipped if
        # the city was added back by hand before undoing.
        for index, city in reversed(self._removed):
            if city.key in present:
                continue
            cities.insert(min(index, len(cities)), city)
            present.add(city.key)
        if self._removed_reference is not None and self._removed_reference in cities:
            self._model.set_reference(self._removed_reference)
        self._removed = []
        self._removed_reference = None
        self._persist()
        self._rebuild_rows()

    def _on_row_reorder(self, _row: TimezoneRow, source: City, target: City) -> None:
        if source not in self._model.cities or target not in self._model.cities:
            return
        # Dropping onto a row trades the two places outright; every other row
        # keeps the slot it had.
        self._model.swap(source, target)
        self._persist()
        self._rebuild_rows()

    # -- Menu actions -----------------------------------------------------------

    def _on_preferences(self, *_args) -> None:
        dialog = PreferencesDialog(
            theme_mode=self._settings.get_string("theme-mode", "system"),
            fmt_24h=self._fmt_24h,
            show_offsets=self._show_offsets,
            show_daynight=self._show_daynight,
        )
        dialog.connect("theme-changed", self._on_theme_changed)
        dialog.connect("fmt-24h-changed", self._on_prefs_fmt_changed)
        dialog.connect("show-offsets-changed", self._on_show_offsets_changed)
        dialog.connect("show-daynight-changed", self._on_show_daynight_changed)
        dialog.connect("reorder-requested", self._on_reorder_requested)
        self._preferences = dialog
        dialog.connect("closed", lambda *_a: setattr(self, "_preferences", None))
        dialog.present(self)

    def _on_shortcuts(self, *_args) -> None:
        shortcuts = (
            (_("Add timezone"), "Ctrl+N"),
            (_("Back to today"), "Ctrl+T"),
            (_("Preferences"), "Ctrl+,"),
            (_("Quit"), "Ctrl+Q"),
        )
        dialog = Adw.AlertDialog(
            heading=_("Keyboard Shortcuts"),
            body="\n".join(
                # Translators: a line of the keyboard shortcuts list, as in
                # "Quit: Ctrl+Q".
                _("{action}: {keys}").format(action=action, keys=keys)
                for action, keys in shortcuts
            ),
        )
        dialog.add_response("ok", _("_Close"))
        dialog.present(self)

    def _on_about(self, *_args) -> None:
        about = Adw.AboutDialog(
            application_name=_("Timezones"),
            application_icon=APP_ID,
            version=VERSION,
            developer_name="Hernan Lozano",
            license_type=Gtk.License.GPL_3_0,
            comments=_("Keep track of the time in cities that matter to you."),
            # Translators: replace with your name, and your email address if
            # you like, one translator per line.
            translator_credits=_("translator-credits"),
        )
        about.present(self)

    def _on_reorder_requested(self, *_args) -> None:
        self._open_reorder_dialog()

    def _open_reorder_dialog(self) -> None:
        dialog = Adw.Dialog()
        dialog.set_title(_("Reorder Timezones"))
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
                tz_row = Adw.ActionRow(title=city.name, subtitle=city.tz)
                up_btn = Gtk.Button.new_from_icon_name("go-up-symbolic")
                up_btn.set_tooltip_text(_("Move up"))
                up_btn.add_css_class("flat")
                up_btn.set_sensitive(i > 0)
                down_btn = Gtk.Button.new_from_icon_name("go-down-symbolic")
                down_btn.set_tooltip_text(_("Move down"))
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
        # Full rebuild, not _refresh_rows: the pill is set by row.update(),
        # which the time-label-only refresh never reaches.
        self._rebuild_rows()

    def _on_show_daynight_changed(self, _dialog: PreferencesDialog, value: bool) -> None:
        self._show_daynight = value
        self._settings.set_bool("show-daynight", value)
        self._rebuild_rows()

