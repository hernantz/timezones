from __future__ import annotations

from datetime import datetime

from gi.repository import Gdk, Gio, GObject, Graphene, Gtk

from . import tzinfo_helpers as tzinfo
from .model import City, ClockModel
from .timeline import TimelineStrip

_DRAG_MIME = "application/x-timezones-row"

# The row currently being dragged, so every other row can tell "the pointer is
# carrying me" from "the pointer is carrying someone else".
_drag_row: "TimezoneRow | None" = None


class TimezoneRow(Gtk.Box):
    __gtype_name__ = "TimezonesRow"

    __gsignals__ = {
        "set-reference": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "edit-label": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "move-up": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "move-down": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "remove-row": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "reorder": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(self, city: City):
        # Vertical, because a row is the card *plus* whatever it has to say
        # about itself: on a clock-change day a warning band sits under the
        # card, and the two have to move, reorder and drag as one thing.
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.city = city
        self._narrow = False
        self._compact = False

        # A row is sized by its own content and nothing else: it never takes a
        # share of the window's spare height, so a taller window reveals more
        # rows instead of stretching the ones already there.
        self.set_valign(Gtk.Align.START)
        self.set_vexpand(False)

        self._build()
        self._setup_dnd()

    def _build(self) -> None:
        self._card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._card.add_css_class("tz-row")
        self._card.set_overflow(Gtk.Overflow.HIDDEN)
        self.append(self._card)

        # Everything left of the timeline lives in one box so the narrow layout
        # can lift it out as a single header line without re-ordering anything
        # inside it. In the wide layout it is inert: a horizontal box of
        # fixed-width children measures exactly as those children did.
        self._head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._card.append(self._head)

        # 1. drag handle
        handle_box = Gtk.Box()
        handle_box.add_css_class("tz-drag-handle")
        handle_box.set_size_request(26, -1)
        handle_box.set_halign(Gtk.Align.CENTER)
        handle_box.set_valign(Gtk.Align.FILL)
        handle_icon = Gtk.Image.new_from_icon_name("list-drag-handle-symbolic")
        handle_icon.set_pixel_size(14)
        handle_box.append(handle_icon)
        handle_box.set_cursor(Gdk.Cursor.new_from_name("grab"))
        self._handle = handle_box
        self._head.append(handle_box)

        # 2. identity block
        identity = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        identity.add_css_class("tz-identity")
        identity.set_size_request(180, -1)
        identity.set_margin_top(14)
        identity.set_margin_bottom(14)
        identity.set_margin_start(2)
        identity.set_margin_end(16)
        identity.set_valign(Gtk.Align.CENTER)

        self._city_label = Gtk.Label(xalign=0)
        self._city_label.add_css_class("tz-city-name")
        self._city_label.set_halign(Gtk.Align.START)

        self._subtitle_label = Gtk.Label(xalign=0)
        self._subtitle_label.add_css_class("tz-subtitle")
        self._subtitle_label.set_halign(Gtk.Align.START)

        self._chip = Gtk.Label(xalign=0)
        self._chip.add_css_class("tz-chip")
        self._chip.set_halign(Gtk.Align.START)
        self._chip.set_margin_top(2)
        self._chip.set_visible(False)

        self._name_line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._name_line.append(self._city_label)

        identity.append(self._name_line)
        identity.append(self._subtitle_label)
        identity.append(self._chip)
        self._identity = identity
        self._head.append(identity)

        # 3. time block
        time_block = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        time_block.add_css_class("tz-time-block")
        time_block.set_size_request(118, -1)
        time_block.set_margin_top(14)
        time_block.set_margin_bottom(14)
        time_block.set_halign(Gtk.Align.END)
        time_block.set_valign(Gtk.Align.CENTER)

        self._time_label = Gtk.Label(xalign=1)
        self._time_label.add_css_class("tz-time-big")
        self._time_label.set_halign(Gtk.Align.END)

        self._date_label = Gtk.Label(xalign=1)
        self._date_label.add_css_class("tz-date")
        self._date_label.set_halign(Gtk.Align.END)

        trailer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        trailer.set_halign(Gtk.Align.END)
        trailer.set_margin_top(2)

        self._home_icon = Gtk.Image.new_from_icon_name("user-home-symbolic")
        self._home_icon.add_css_class("tz-home-icon")
        self._home_icon.set_pixel_size(16)
        self._home_icon.set_tooltip_text("Reference timezone")
        self._home_icon.set_visible(False)

        self._offset_pill = Gtk.Label()
        self._offset_pill.add_css_class("tz-offset-pill")
        self._offset_pill.set_visible(False)

        trailer.append(self._home_icon)
        trailer.append(self._offset_pill)

        time_block.append(self._time_label)
        time_block.append(self._date_label)
        time_block.append(trailer)
        self._time_block = time_block
        self._head.append(time_block)

        # Divider is a dedicated full-height sibling rather than a border on
        # time_block itself — time_block's own box is vertically inset by its
        # 14px top/bottom margins (to center its content), so a border drawn
        # on it would stop short of the row's actual top/bottom edges.
        divider = Gtk.Box()
        divider.add_css_class("tz-time-divider")
        divider.set_vexpand(True)
        self._divider = divider
        self._card.append(divider)

        # 4. timeline strip
        self._timeline = TimelineStrip()
        self._card.append(self._timeline)

        # 5. row-end: more button
        end_box = Gtk.Box()
        end_box.set_margin_start(6)
        end_box.set_margin_end(8)
        end_box.set_valign(Gtk.Align.CENTER)

        self._actions = Gio.SimpleActionGroup()
        for name, sig in (
            ("set-reference", "set-reference"),
            ("edit-label", "edit-label"),
            ("move-up", "move-up"),
            ("move-down", "move-down"),
            ("remove", "remove-row"),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda a, p, s=sig: self.emit(s))
            self._actions.add_action(action)
        self.insert_action_group("row", self._actions)

        menu = Gio.Menu()
        menu.append("Set as reference timezone", "row.set-reference")
        menu.append("Edit label…", "row.edit-label")
        section = Gio.Menu()
        section.append("Move up", "row.move-up")
        section.append("Move down", "row.move-down")
        menu.append_section(None, section)
        remove_section = Gio.Menu()
        remove_section.append("Remove timezone", "row.remove")
        menu.append_section(None, remove_section)

        self._more_btn = Gtk.MenuButton()
        self._more_btn.add_css_class("tz-more-btn")
        self._more_btn.add_css_class("flat")
        self._more_btn.set_icon_name("view-more-symbolic")
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.add_css_class("tz-row-menu")
        self._more_btn.set_popover(popover)
        self._set_ref_action = self._actions.lookup_action("set-reference")
        self._move_up_action = self._actions.lookup_action("move-up")
        self._move_down_action = self._actions.lookup_action("move-down")

        end_box.append(self._more_btn)
        self._end_box = end_box
        self._card.append(end_box)

        # 6. clock-change warning, hidden on all but the two days a year it
        # has something to say. Below the card rather than inside it: it is a
        # statement about the whole row, and there is no column of the card it
        # could sit in without competing with the numbers.
        self._warning = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)
        self._warning.add_css_class("tz-dst-warning")
        warning_icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        warning_icon.set_pixel_size(12)
        self._warning_label = Gtk.Label(xalign=0)
        self._warning_label.set_wrap(True)
        self._warning.append(warning_icon)
        self._warning.append(self._warning_label)
        self._warning.set_visible(False)
        self.append(self._warning)

    # -- Adaptive layout ------------------------------------------------------

    def set_narrow(self, narrow: bool) -> None:
        """Switch between the two states of the row: side-by-side and stacked.

        Not "the desktop row" and "the mobile row" — one component, two states,
        picked by the window's breakpoint. A narrow desktop window gets exactly
        what a phone gets.
        """
        if narrow == self._narrow:
            return
        self._narrow = narrow

        if narrow:
            # The head (handle · city · time) becomes a line of its own, with
            # the kebab pulled up onto it, and the timeline takes the full
            # width underneath.
            self._card.remove(self._divider)
            self._card.remove(self._end_box)
            self._card.set_orientation(Gtk.Orientation.VERTICAL)
            self._head.append(self._end_box)
            self._card.add_css_class("narrow")
            # 180px of reserved name column is a wide-window luxury; stacked,
            # the name simply takes what is left after the time.
            self._identity.set_size_request(-1, -1)
            self._identity.set_hexpand(True)
            self._time_block.set_hexpand(False)
            self._head.set_margin_bottom(2)
        else:
            self._head.remove(self._end_box)
            self._card.set_orientation(Gtk.Orientation.HORIZONTAL)
            # Back into wide order: head, divider, timeline, kebab.
            self._card.insert_child_after(self._divider, self._head)
            self._card.append(self._end_box)
            self._card.remove_css_class("narrow")
            self._identity.set_size_request(180, -1)
            self._identity.set_hexpand(False)
            self._head.set_margin_bottom(0)

    def set_compact(self, compact: bool) -> None:
        """The second, opt-in row height — never an automatic response to how
        many rows exist. Identity collapses to one line and the vertical
        padding is trimmed; the timeline's own minimum sizes are untouched, so
        a compact row is short, not degraded.
        """
        if compact == self._compact:
            return
        self._compact = compact

        pad = 7 if compact else 14
        for block in (self._identity, self._time_block):
            block.set_margin_top(pad)
            block.set_margin_bottom(pad)

        # The chip rides beside the city name instead of below the subtitle,
        # which is what makes the single line possible at all for a labelled row.
        self._chip.get_parent().remove(self._chip)
        if compact:
            self._card.add_css_class("compact")
            self._subtitle_label.set_visible(False)
            self._chip.set_margin_top(0)
            self._name_line.append(self._chip)
        else:
            self._card.remove_css_class("compact")
            self._subtitle_label.set_visible(True)
            self._chip.set_margin_top(2)
            self._identity.append(self._chip)

    def set_move_enabled(self, up: bool, down: bool) -> None:
        self._move_up_action.set_enabled(up)
        self._move_down_action.set_enabled(down)

    def update(
        self,
        model: ClockModel,
        fmt_24h: bool,
        show_offsets: bool,
        show_daynight: bool,
        at: datetime | None = None,
    ) -> None:
        city = self.city
        is_ref = city.is_reference

        self._card.remove_css_class("reference")
        if is_ref:
            self._card.add_css_class("reference")

        # The reference row is already the reference — offering the action
        # would be a no-op.
        self._set_ref_action.set_enabled(not is_ref)

        transitions = model.row_transitions(city, at)

        self._city_label.set_label(tzinfo.city_name(city.tz))
        self._subtitle_label.set_label(
            f"{tzinfo.country_name(city.tz)} · {self._zone_summary(city.tz, transitions, at)}"
        )
        self._update_warning(city, transitions, fmt_24h)

        if city.label:
            self._chip.set_label(city.label)
            self._chip.set_visible(True)
            self._chip.remove_css_class("you")
            if city.label.strip().lower() == "you":
                self._chip.add_css_class("you")
        else:
            self._chip.set_visible(False)

        self.update_time_display(model, fmt_24h, at)

        if is_ref:
            self._home_icon.set_visible(True)
            self._offset_pill.set_visible(False)
        else:
            self._home_icon.set_visible(False)
            if show_offsets:
                offset = model.offset_hours(city, at)
                self._offset_pill.set_label(tzinfo.format_offset(offset))
                self._offset_pill.set_visible(True)
            else:
                self._offset_pill.set_visible(False)

        self._timeline.update(model, city, fmt_24h, show_daynight, at, transitions)

    @staticmethod
    def _zone_summary(
        tz_id: str, transitions: list[tuple[int, tzinfo.DstTransition]], at: datetime | None
    ) -> str:
        """The zone's abbreviation, or both of them on a day that has two.

        A bare "EST" on a day the row spends half of on EDT would be a small
        lie, and the one place a reader looks to check which rules are in force.
        """
        if not transitions:
            return tzinfo.abbreviation(tz_id, at)
        _, first = transitions[0]
        _, last = transitions[-1]
        before, _ = tzinfo.abbreviation_change(tz_id, first)
        _, after = tzinfo.abbreviation_change(tz_id, last)
        return f"{before} → {after}"

    def _update_warning(
        self, city: City, transitions: list[tuple[int, tzinfo.DstTransition]], fmt_24h: bool
    ) -> None:
        self._warning.set_visible(bool(transitions))
        if not transitions:
            return
        # Always the city, never the row's own label: "Clocks in You move back
        # 1 hour" is not a sentence, and the rule belongs to the place anyway.
        name = tzinfo.city_name(city.tz)
        self._warning_label.set_label(
            "\n".join(
                tzinfo.describe_transition(name, transition, fmt_24h)
                for _, transition in transitions
            )
        )

    def update_time_display(
        self,
        model: ClockModel,
        fmt_24h: bool,
        at: datetime | None = None,
        *,
        previewing: bool = False,
    ) -> None:
        """Refresh only the time/date labels for `at` — cheap enough to call on every
        mouse-move during hover-scrub, unlike `update()` which rebuilds the timeline.

        `previewing` marks the big time in accent color so a hover/pinned scrub value
        is never mistaken for the real current time.
        """
        at = at or datetime.now().astimezone()
        local = tzinfo.local_now(self.city.tz, at)

        if previewing:
            self._time_label.add_css_class("previewing")
        else:
            self._time_label.remove_css_class("previewing")

        if fmt_24h:
            self._time_label.set_markup(local.strftime("%H:%M"))
        else:
            # Meridiem rides along at a smaller size so 12h times stay inside
            # the time block's width instead of pushing into the timeline.
            self._time_label.set_markup(
                local.strftime("%-I:%M") + f'<span size="62%"> {local.strftime("%p")}</span>'
            )

        ref = model.reference
        ref_today = tzinfo.local_now(ref.tz, at).date() if ref else at.date()
        differs = local.date() != ref_today
        self._date_label.set_label(local.strftime("%a, %b %-d"))
        self._date_label.remove_css_class("accent")
        if differs:
            self._date_label.add_css_class("accent")

    def get_timeline(self) -> TimelineStrip:
        return self._timeline

    def _drag_icon(self) -> Gdk.Paintable:
        """A *frozen* picture of this row, for the card that follows the cursor.

        Gtk.WidgetPaintable keeps rendering the live widget, so the row left
        behind and the card under the pointer would be the same picture: the
        moment `.dragging` fades the placeholder, the thing being dragged fades
        with it and the user is left dragging nothing. Snapshotting once, here
        in `prepare` — before `drag-begin` adds the class — keeps the card at
        full strength while the placeholder dims.
        """
        width, height = self.get_width(), self.get_height()
        live = Gtk.WidgetPaintable.new(self)
        if width <= 0 or height <= 0:
            return live
        snapshot = Gtk.Snapshot.new()
        live.snapshot(snapshot, width, height)
        frozen = snapshot.to_paintable(Graphene.Size().init(width, height))
        # to_paintable() yields None for an empty node; a live icon beats none.
        return frozen if frozen is not None else live

    def _setup_dnd(self) -> None:
        drag_source = Gtk.DragSource.new()
        drag_source.set_actions(Gdk.DragAction.MOVE)

        def on_prepare(source: Gtk.DragSource, x: float, y: float):
            # x/y arrive in *handle* coordinates while the icon is the whole
            # row, so translate the grab point into row space. (Today the
            # handle sits at the row's origin and this is a no-op, but it stops
            # being one the moment the handle moves.)
            ok, bounds = self._handle.compute_bounds(self)
            hx, hy = (bounds.origin.x + x, bounds.origin.y + y) if ok else (x, y)
            source.set_icon(self._drag_icon(), int(hx), int(hy))
            value = GObject.Value(str, self.city.tz)
            return Gdk.ContentProvider.new_for_value(value)

        def on_begin(*_args) -> None:
            global _drag_row
            _drag_row = self
            self.add_css_class("dragging")
            self._handle.set_cursor(Gdk.Cursor.new_from_name("grabbing"))

        def on_end(*_args) -> None:
            global _drag_row
            _drag_row = None
            self.remove_css_class("dragging")
            self._handle.set_cursor(Gdk.Cursor.new_from_name("grab"))

        drag_source.connect("prepare", on_prepare)
        drag_source.connect("drag-begin", on_begin)
        drag_source.connect("drag-end", on_end)
        self._handle.add_controller(drag_source)

        drop_target = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)

        def clear_hint() -> None:
            self.remove_css_class("drop-target")

        def hint() -> bool:
            """Light up this whole row as the one the drag would trade places with.

            Hovering the source row itself is a no-op, which is what stops the
            list from twitching as the drag passes back over its own gap.
            """
            if _drag_row is self:
                clear_hint()
                return False
            self.add_css_class("drop-target")
            return True

        def on_motion(_target: Gtk.DropTarget, _x: float, _y: float) -> int:
            return Gdk.DragAction.MOVE if hint() else 0

        def on_leave(_target: Gtk.DropTarget) -> None:
            clear_hint()

        def on_drop(target: Gtk.DropTarget, value: str, _x: float, _y: float) -> bool:
            clear_hint()
            if not value or value == self.city.tz:
                return False
            self.emit("reorder", value, self.city.tz)
            return True

        drop_target.connect("motion", on_motion)
        drop_target.connect("leave", on_leave)
        drop_target.connect("drop", on_drop)
        self.add_controller(drop_target)
