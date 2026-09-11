from __future__ import annotations

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402
import sys

# Import side-effect ensures template class can resolve resources.
from .main_window import TimezonesMainWindow  # noqa: E402

RESOURCE_PREFIX = "/com/hernantz/timezones"


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
        super().__init__(application_id="com.hernantz.timezones")

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
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
