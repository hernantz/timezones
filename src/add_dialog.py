from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from operator import itemgetter

from gi.repository import Adw, GObject, Gtk

from . import tzinfo_helpers as tzinfo
from .i18n import _

_MAX_RESULTS = 60  # rows shown for one query, and so the size the row pool tops out at


@dataclass(frozen=True)
class _Entry:
    """One timezone as this dialog needs it for *matching*.

    Built once per dialog rather than per query. `tzinfo.abbreviation()` opens a
    `ZoneInfo` and converts a datetime, and the filter called it — along with
    `country_name()` and four `.lower()` calls — for every zone on every
    keystroke. None of it can change while the dialog is open.

    The offset deliberately is not here. It is the one displayed field no filter
    looks at, so resolving it for all ~400 zones to show at most 60 of them just
    made opening the dialog slower; `_ResultRow.bind` works it out per row from
    the conversion it already has to do.
    """

    tz_id: str
    city: str
    country: str
    abbr: str
    city_lower: str
    country_lower: str
    abbr_lower: str
    id_lower: str

    @classmethod
    def build(cls, tz_id: str) -> _Entry:
        city = tzinfo.city_name(tz_id)
        country = tzinfo.country_name(tz_id)
        abbr = tzinfo.abbreviation(tz_id)
        # The English names are searched too, joined on behind the translated
        # ones: they are what a zone is called in every other app, and a
        # German typing "Munich" should still find München. The ranking below
        # only looks at the start of the string, so the translation still
        # decides what counts as a prefix match.
        english_city = tzinfo.english_city_name(tz_id)
        english_country = tzinfo.english_country_name(tz_id)
        return cls(
            tz_id=tz_id,
            city=city,
            country=country,
            abbr=abbr,
            city_lower=_searchable(city, english_city),
            country_lower=_searchable(country, english_country),
            abbr_lower=abbr.lower(),
            id_lower=tz_id.lower(),
        )


def _searchable(name: str, english: str) -> str:
    folded = name.lower()
    return folded if name == english else f"{folded}\n{english.lower()}"


class _ResultRow:
    """One result line, built once and rebound as the query changes.

    Rebinding is why the add button's handler is a method here rather than a
    closure over one `tz_id`, as it was when every keystroke threw the row away:
    the row now outlives any particular timezone, so the zone it is currently
    showing has to live somewhere it can be updated — `self.tz_id`.
    """

    __slots__ = ("widget", "tz_id", "_dialog", "_name", "_subtitle", "_preview", "_btn", "_icon")

    def __init__(self, dialog: AddTimezoneDialog) -> None:
        self._dialog = dialog
        self.tz_id = ""

        self.widget = Gtk.ListBoxRow()
        self.widget.set_activatable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(10)
        box.set_margin_end(10)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text_box.set_hexpand(True)
        self._name = Gtk.Label(xalign=0)
        self._name.set_halign(Gtk.Align.START)
        self._name.add_css_class("heading")
        self._subtitle = Gtk.Label(xalign=0)
        self._subtitle.set_halign(Gtk.Align.START)
        self._subtitle.add_css_class("dim-label")
        self._subtitle.add_css_class("caption")
        text_box.append(self._name)
        text_box.append(self._subtitle)

        self._preview = Gtk.Label()
        self._preview.add_css_class("dim-label")

        self._btn = Gtk.Button()
        self._btn.add_css_class("tz-add-btn")
        self._btn.add_css_class("circular")
        self._btn.set_valign(Gtk.Align.CENTER)
        self._btn.set_halign(Gtk.Align.CENTER)
        self._icon = Gtk.Image.new_from_icon_name("list-add-symbolic")
        self._btn.set_child(self._icon)
        self._btn.connect("clicked", self._on_clicked)

        box.append(text_box)
        box.append(self._preview)
        box.append(self._btn)
        self.widget.set_child(box)

    def bind(self, entry: _Entry, at: datetime, added: bool) -> None:
        self.tz_id = entry.tz_id
        # One conversion, both facts: tzinfo.utc_offset() resolves the offset by
        # doing this very astimezone, so asking it separately would repeat the
        # work. Same instant either way, so the two cannot disagree.
        local = tzinfo.local_now(entry.tz_id, at)
        self._name.set_label(entry.city)
        self._subtitle.set_label(
            f"{entry.country} · {tzinfo.describe_zone(local.tzname() or '', local.utcoffset())}"
        )
        self._preview.set_label(local.strftime("%H:%M"))
        self._set_added(added)

    def _set_added(self, added: bool) -> None:
        # The check is permanent: the timezone is in the list now, and the only
        # way back is removing it from the main window.
        self._icon.set_from_icon_name(
            "object-select-symbolic" if added else "list-add-symbolic"
        )
        self._btn.set_sensitive(not added)
        self._btn.set_tooltip_text(_("Already added") if added else None)
        if added:
            self._btn.add_css_class("added")
        else:
            self._btn.remove_css_class("added")

    def _on_clicked(self, _btn: Gtk.Button) -> None:
        self._dialog.add_timezone(self.tz_id)
        self._set_added(True)


class AddTimezoneDialog(Adw.Dialog):
    __gtype_name__ = "TimezonesAddDialog"

    __gsignals__ = {
        "timezone-added": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, existing: set[str]):
        super().__init__()
        self.set_title(_("Add Timezone"))
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
        self._search.set_placeholder_text(_("Search for a city or timezone"))
        self._search.connect("search-changed", self._on_search_changed)
        # Escape would otherwise be dead here: the entry has a class binding
        # of Escape to stop-search, which sits below the dialog's own close
        # binding in the focus chain and reports the key as handled, so the
        # dialog never sees it — and stop-search does nothing by default. This
        # dialog *is* the search, so stopping it means dismissing the dialog.
        self._search.connect("stop-search", lambda *_a: self.close())
        body.append(self._search)

        self._results_label = Gtk.Label(label=_("Results").upper(), xalign=0)
        self._results_label.add_css_class("tz-results-label")
        self._results_label.set_margin_top(4)
        body.append(self._results_label)

        self._scroller = Gtk.ScrolledWindow()
        self._scroller.set_vexpand(True)
        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.add_css_class("boxed-list")
        self._scroller.set_child(self._list)

        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._stack.add_named(self._scroller, "results")
        self._stack.add_named(self._build_empty_state(), "empty")
        body.append(self._stack)

        toolbar_view.set_content(body)
        self.set_child(toolbar_view)

        self._index = [_Entry.build(tz_id) for tz_id in tzinfo.all_timezone_ids()]
        # Grown on demand up to _MAX_RESULTS and never torn down: a query only
        # ever rebinds these, so typing costs label updates instead of hundreds
        # of fresh widgets per keystroke.
        self._rows: list[_ResultRow] = []
        self._populate("")

    def _build_empty_state(self) -> Gtk.Widget:
        status = Adw.StatusPage()
        status.add_css_class("tz-empty-state")
        status.add_css_class("compact")
        status.set_icon_name("system-search-symbolic")
        status.set_title(_("No Results"))
        status.set_description(_("Try a different city, country, or timezone name."))
        return status

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._populate(entry.get_text().strip())

    def _populate(self, query: str) -> None:
        q = query.lower()
        matches = []
        for entry in self._index:
            if (
                not q
                or q in entry.city_lower
                or q in entry.country_lower
                or q in entry.abbr_lower
                or q in entry.id_lower
            ):
                rank = 0 if entry.city_lower.startswith(q) else (1 if q in entry.city_lower else 2)
                matches.append((rank, entry.city_lower, entry))

        # Sorted on the key alone: two zones can share a city name (Tripoli,
        # Santa Isabel), and _Entry has no ordering to fall back on.
        matches.sort(key=itemgetter(0, 1))
        shown = matches[:_MAX_RESULTS]

        at = datetime.now().astimezone()
        for i, (_rank, _key, entry) in enumerate(shown):
            if i == len(self._rows):
                row = _ResultRow(self)
                self._rows.append(row)
                self._list.append(row.widget)
            row = self._rows[i]
            row.bind(entry, at, entry.tz_id in self._existing)
            row.widget.set_visible(True)

        for row in self._rows[len(shown):]:
            row.widget.set_visible(False)

        # Rebuilding the list used to reset this for free; reused rows keep the
        # scroller wherever the last query left it, which would drop the user
        # into the middle of an unrelated set of results.
        self._scroller.get_vadjustment().set_value(0)

        self._results_label.set_visible(bool(matches))
        self._stack.set_visible_child_name("results" if matches else "empty")

    def add_timezone(self, tz_id: str) -> None:
        """Called by a row's add button; the row paints its own check."""
        self.emit("timezone-added", tz_id)
        self._existing.add(tz_id)
