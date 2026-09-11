from __future__ import annotations

import os
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

RESOURCE_PREFIX = "/com/hernantz/timezones"


def _register_resources():
    resource_path = os.path.join(os.path.dirname(__file__), 'com.hernantz.timezones.gresource')
    resource = Gio.resource_load(resource_path)
    Gio.Resource._register(resource)


_register_resources()

from src.main_window import TimezonesMainWindow  # noqa: E402


def _load_style() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_resource(f"{RESOURCE_PREFIX}/style.css")
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_resource_path(
        f"{RESOURCE_PREFIX}/icons"
    )


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.hernantz.timezones", flags=0)

    def do_startup(self):
        Adw.Application.do_startup(self)
        _load_style()
        # Wayland matches the window to com.hernantz.timezones.desktop by app id
        # and takes the icon from there; X11 needs it named explicitly.
        Gtk.Window.set_default_icon_name("com.hernantz.timezones")

    def do_activate(self):
        win = self.props.active_window
        if win is None:
            win = TimezonesMainWindow(application=self)
        win.present()


def main():
    # argv[0] would otherwise make the window show up as "python3": the shell
    # takes the Wayland app_id / X11 WM_CLASS from the program name.
    GLib.set_prgname("com.hernantz.timezones")
    GLib.set_application_name("Timezones")
    app = App()
    app.run(None)


if __name__ == "__main__":
    main()
