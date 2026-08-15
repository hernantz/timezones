from __future__ import annotations

from gi.repository import Adw, Gdk, Gtk  # noqa: E402
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

    def do_activate(self):
        win = self.props.active_window
        if win is None:
            win = TimezonesMainWindow(application=self)
        win.present()


def main():
    app = App()
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
