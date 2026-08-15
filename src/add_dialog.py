from __future__ import annotations

from datetime import datetime

from gi.repository import Adw, GLib, GObject, Gtk

from . import tzinfo_helpers as tzinfo


class AddTimezoneDialog(Adw.Dialog):
    __gtype_name__ = "TimezonesAddDialog"

    __gsignals__ = {
        "timezone-added": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, existing: set[str]):
        super().__init__()
        self.set_title("Add Timezone")
        self.set_content_width(420)
        self.set_content_height(520)
        self._existing = existing

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)
        toolbar_view.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        body.set_margin_top(16)
        body.set_margin_bottom(18)
        body.set_margin_start(16)
        body.set_margin_end(16)

        self._search = Gtk.SearchEntry()
        self._search.add_css_class("tz-search-entry")
        self._search.set_placeholder_text("Search for a city or timezone")
        self._search.connect("search-changed", self._on_search_changed)
        body.append(self._search)

        results_label = Gtk.Label(label="RESULTS", xalign=0)
        results_label.add_css_class("tz-results-label")
        results_label.set_margin_top(4)
        body.append(results_label)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.add_css_class("boxed-list")
        scroller.set_child(self._list)
        body.append(scroller)

        toolbar_view.set_content(body)
        self.set_child(toolbar_view)

        self._all_ids = tzinfo.all_timezone_ids()
        self._populate("")

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._populate(entry.get_text().strip())

    def _populate(self, query: str) -> None:
        child = self._list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._list.remove(child)
            child = nxt

        q = query.lower()
        matches = []
        for tz_id in self._all_ids:
            city = tzinfo.city_name(tz_id).lower()
            country = tzinfo.country_name(tz_id).lower()
            abbr = tzinfo.abbreviation(tz_id).lower()
            if not q or q in city or q in country or q in abbr or q in tz_id.lower():
                rank = 0 if city.startswith(q) else (1 if q in city else 2)
                matches.append((rank, city, tz_id))

        matches.sort()
        for _, _, tz_id in matches[:60]:
            self._list.append(self._make_row(tz_id))

    def _make_row(self, tz_id: str) -> Gtk.Widget:
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(10)
        box.set_margin_end(10)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text_box.set_hexpand(True)
        name = Gtk.Label(label=tzinfo.city_name(tz_id), xalign=0)
        name.set_halign(Gtk.Align.START)
        name.add_css_class("heading")

        offset = tzinfo.utc_offset_hours(tz_id)
        subtitle = Gtk.Label(
            label=f"{tzinfo.country_name(tz_id)} · {tzinfo.abbreviation(tz_id)} · UTC{tzinfo.format_offset(offset)}",
            xalign=0,
        )
        subtitle.set_halign(Gtk.Align.START)
        subtitle.add_css_class("dim-label")
        subtitle.add_css_class("caption")

        text_box.append(name)
        text_box.append(subtitle)

        now = tzinfo.local_now(tz_id, datetime.now().astimezone())
        preview = Gtk.Label(label=now.strftime("%H:%M"))
        preview.add_css_class("dim-label")

        add_btn = Gtk.Button()
        add_btn.add_css_class("tz-add-btn")
        add_btn.add_css_class("circular")
        icon = Gtk.Image.new_from_icon_name("list-add-symbolic")
        add_btn.set_child(icon)
        if tz_id in self._existing:
            add_btn.set_sensitive(False)
            icon.set_from_icon_name("object-select-symbolic")

        def reset_button() -> bool:
            icon.set_from_icon_name("list-add-symbolic")
            add_btn.set_sensitive(tz_id not in self._existing)
            return GLib.SOURCE_REMOVE

        def on_add(_btn: Gtk.Button) -> None:
            self.emit("timezone-added", tz_id)
            self._existing.add(tz_id)
            add_btn.set_sensitive(False)
            icon.set_from_icon_name("object-select-symbolic")
            GLib.timeout_add(1200, reset_button)

        add_btn.connect("clicked", on_add)

        box.append(text_box)
        box.append(preview)
        box.append(add_btn)
        row.set_child(box)
        return row
