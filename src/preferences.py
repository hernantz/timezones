from __future__ import annotations

from gi.repository import Adw, GObject, Gtk

_APPEARANCE_OPTIONS = [("light", "Light"), ("dark", "Dark"), ("system", "System")]


class PreferencesDialog(Adw.PreferencesDialog):
    __gtype_name__ = "TimezonesPreferencesDialog"

    __gsignals__ = {
        "theme-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "fmt-24h-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "show-offsets-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "show-daynight-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "reorder-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(
        self,
        *,
        theme_mode: str,
        fmt_24h: bool,
        show_offsets: bool,
        show_daynight: bool,
    ):
        super().__init__()
        self.set_search_enabled(False)
        page = Adw.PreferencesPage()
        self.add(page)

        page.add(self._build_appearance_group(theme_mode))
        page.add(self._build_time_format_group(fmt_24h))
        page.add(self._build_view_options_group(show_offsets, show_daynight))

    # -- Appearance -------------------------------------------------------

    def _build_appearance_group(self, theme_mode: str) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Appearance")

        row = Adw.PreferencesRow()
        row.set_activatable(False)
        container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, homogeneous=True)
        container.set_margin_top(10)
        container.set_margin_bottom(10)
        container.set_margin_start(12)
        container.set_margin_end(12)

        self._swatch_widgets: dict[str, tuple[Gtk.Widget, Gtk.Label]] = {}
        for mode, title in _APPEARANCE_OPTIONS:
            option = self._build_swatch(mode, title)
            container.append(option)
        row.set_child(container)
        group.add(row)

        self._set_selected_theme(theme_mode)
        return group

    def _build_swatch(self, mode: str, title: str) -> Gtk.Widget:
        option_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        swatch = Gtk.Box()
        swatch.add_css_class("tz-swatch")

        if mode == "system":
            half = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0, homogeneous=True)
            half.append(self._swatch_face("light"))
            half.append(self._swatch_face("dark"))
            swatch.append(half)
        else:
            swatch.append(self._swatch_face(mode))

        label = Gtk.Label(label=title)
        label.add_css_class("tz-swatch-label")

        option_box.append(swatch)
        option_box.append(label)

        click = Gtk.GestureClick()
        click.connect("released", lambda *_a, m=mode: self._on_theme_selected(m))
        option_box.add_controller(click)
        option_box.set_cursor_from_name("pointer")

        self._swatch_widgets[mode] = (swatch, label)
        return option_box

    @staticmethod
    def _swatch_face(variant: str) -> Gtk.Widget:
        face = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        face.add_css_class(f"tz-swatch-{variant}")
        face.set_hexpand(True)

        header = Gtk.Box()
        header.add_css_class("tz-swatch-header")

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        body.add_css_class("tz-swatch-body")
        body.set_valign(Gtk.Align.CENTER)
        for _ in range(2):
            line = Gtk.Box()
            line.add_css_class("tz-swatch-line")
            body.append(line)

        face.append(header)
        face.append(body)
        return face

    def _on_theme_selected(self, mode: str) -> None:
        self._set_selected_theme(mode)
        self.emit("theme-changed", mode)

    def _set_selected_theme(self, mode: str) -> None:
        for m, (swatch, label) in self._swatch_widgets.items():
            selected = m == mode
            swatch.set_css_classes(["tz-swatch"] + (["selected"] if selected else []))
            label.set_css_classes(["tz-swatch-label", "selected" if selected else "unselected"])

    # -- Time format --------------------------------------------------------

    def _build_time_format_group(self, fmt_24h: bool) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Time format")

        row_24 = Adw.ActionRow(title="24-hour")
        row_24.set_activatable(True)
        radio_24 = Gtk.CheckButton()
        row_24.add_prefix(radio_24)
        row_24.add_suffix(Gtk.Label(label="13:00", css_classes=["dim-label"]))
        row_24.set_activatable_widget(radio_24)

        row_12 = Adw.ActionRow(title="12-hour (AM/PM)")
        row_12.set_activatable(True)
        radio_12 = Gtk.CheckButton()
        radio_12.set_group(radio_24)
        row_12.add_prefix(radio_12)
        row_12.add_suffix(Gtk.Label(label="1:00 PM", css_classes=["dim-label"]))
        row_12.set_activatable_widget(radio_12)

        radio_24.set_active(fmt_24h)
        radio_12.set_active(not fmt_24h)

        radio_24.connect("toggled", lambda b: b.get_active() and self.emit("fmt-24h-changed", True))
        radio_12.connect("toggled", lambda b: b.get_active() and self.emit("fmt-24h-changed", False))

        self._radio_24 = radio_24
        self._radio_12 = radio_12

        group.add(row_24)
        group.add(row_12)
        return group

    def sync_fmt_24h(self, fmt_24h: bool) -> None:
        self._radio_24.set_active(fmt_24h)
        self._radio_12.set_active(not fmt_24h)

    # -- View options ---------------------------------------------------------

    def _build_view_options_group(self, show_offsets: bool, show_daynight: bool) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="View options")

        # Not a UTC offset: ClockModel.offset_hours() is measured against the
        # reference row, so the pill reads +2h for Cairo when London is home.
        offsets_row = Adw.SwitchRow(
            title="Show offsets",
            subtitle="Hours each city is ahead of or behind the reference",
        )
        offsets_row.set_active(show_offsets)
        offsets_row.connect("notify::active", lambda r, _p: self.emit("show-offsets-changed", r.get_active()))
        group.add(offsets_row)

        daynight_row = Adw.SwitchRow(title="Show day / night colors")
        daynight_row.set_active(show_daynight)
        daynight_row.connect("notify::active", lambda r, _p: self.emit("show-daynight-changed", r.get_active()))
        group.add(daynight_row)

        reorder_row = Adw.ActionRow(title="Reorder timezones")
        reorder_row.set_activatable(True)
        reorder_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        reorder_row.connect("activated", lambda *_a: self.emit("reorder-requested"))
        group.add(reorder_row)

        return group
