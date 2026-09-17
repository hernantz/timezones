from __future__ import annotations

import os
import sys

from gi.repository import Gio

RESOURCE_PREFIX = "/com/hernantz/timezones"
_BUNDLE = "com.hernantz.timezones.gresource"


def _register_resources() -> None:
    """Has to happen before the window module is imported, so its templates
    and icons can resolve. Installed, the bundle sits beside this package in
    pkgdatadir; in the source tree meson leaves it in the build dir.
    """
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    build = os.environ.get("TIMEZONES_BUILD_DIR", "builddir")
    for path in (os.path.join(parent, _BUNDLE), os.path.join(parent, build, _BUNDLE)):
        if os.path.exists(path):
            Gio.Resource._register(Gio.resource_load(path))
            return
    raise FileNotFoundError(f"{_BUNDLE} not found next to {parent} — run `make build`")


_register_resources()

from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from .main_window import TimezonesMainWindow  # noqa: E402

# The window installs the win.* actions themselves; accelerators are
# application-wide, so they are bound here. Keep in sync with the list the
# Keyboard Shortcuts dialog prints.
_ACCELS = {
    "win.new": ["<primary>n"],
    "win.today": ["<primary>t"],
    "win.preferences": ["<primary>comma"],
    "app.quit": ["<primary>q"],
}


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
        # A source-tree run would otherwise be swallowed by an already running
        # installed copy: same application id means GApplication just raises
        # that window and exits, so you end up testing the old code.
        if os.environ.get("TIMEZONES_DEV"):
            self.set_flags(self.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)

    def do_startup(self):
        Adw.Application.do_startup(self)
        _load_style()

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_a: self.quit())
        self.add_action(quit_action)
        for name, accels in _ACCELS.items():
            self.set_accels_for_action(name, accels)

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
