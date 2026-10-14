# Contributing to Timezones

Pull requests are welcome: bug fixes, translations, packaging fixes and
features alike. For anything large or that changes how the app behaves, open
an issue first so we can agree on the approach before you put the work in.
Small, focused PRs are the easiest to review; one change per PR.

## Getting started

```sh
make run        # builds, compiles the schema, runs from the source tree
```

`make run` sets `TIMEZONES_DEV=1`, which makes the application non-unique so a
source-tree run is not swallowed by an installed copy holding the same
application id.

Runtime requirements: Python 3.9+ (`zoneinfo` is stdlib), PyGObject, GTK 4,
libadwaita ≥ 1.7 and libgweather 4 with its GObject introspection data
(`GWeather-4.0`), which supplies the city database the add dialog searches. No timezone package is bundled — the IANA database is read
from disk, including `zone.tab` and `iso3166.tab` for each zone's coordinates
and country.

## Layout

| Path | What lives there |
| --- | --- |
| `src/app.py` | The application: resources, stylesheet, startup |
| `src/main_window.py` | The window, the scrub state machine, actions |
| `src/timeline.py` | The 24-column strip: cells, cursors, date flags |
| `src/row.py` | One city's row — identity, time block, strip, menu |
| `src/add_dialog.py` | The add dialog: zone and city search |
| `src/date_popover.py` | The calendar for jumping to a date |
| `src/preferences.py` | The preferences dialog, including reordering |
| `src/tzinfo_helpers.py` | IANA tables, solar elevation, DST transitions, libgweather places |
| `src/share.py` | Clipboard text and `.ics` export |
| `src/model.py` | Cities and the column arithmetic |
| `src/persistence.py` | The saved city list (versioned, with migrations) and settings |
| `src/i18n.py` | Translation setup and every date and clock format |
| `src/const.py`, `src/VERSION` | The application id and the version |
| `bin/timezones.in` | The launcher meson installs |
| `data/` | Desktop entry, GSettings schema, icons, CSS, metainfo, screenshots |
| `po/` | Translations: `timezones.pot` template and one `<lang>.po` per language |
| `tests/` | Unit tests (`make test`), with a sample saved file per schema version |
| `packaging/` | Flatpak manifest and landing page, rpm spec, PKGBUILD, FlatPark templates |
| `.github/workflows/`, `.packit.yaml` | The release pipeline (see [Releasing](#releasing)) |

## Before you open a PR

- Run `make test`, and `make run` to try the change in the real app.
- Describe what you tested and on what (distro, GNOME version, Flatpak or
  not); for a visible change, attach a before/after screenshot, in light and
  dark if colors are involved.
- Changed or added user-facing strings? Run `make pot` so the template and
  `po/*.po` pick them up. You don't need to translate them.
- New runtime dependency? It has to be added in three places: the rpm spec
  (`packaging/rpm/timezones.spec`), the PKGBUILD (`packaging/arch/PKGBUILD`) and,
  if the GNOME runtime lacks it, the Flatpak manifest
  (`packaging/flatpak/io.github.hernantz.timezones.json`). The FlatPark payload
  is built from that manifest, so it follows.
- Changing what `cities.json` stores? A new optional field needs nothing more.
  Anything an older version would misread needs a `SCHEMA_VERSION` bump, a
  `_vN_to_vN+1` step in `src/persistence.py` and a `tests/data/cities-vN.json`
  sample, so existing lists keep loading.
- Commit messages are a short imperative summary ("Fix calendar keyboard
  navigation"), with a body when the why isn't obvious.

## What to test

`make test` covers the saved-file handling; the rest is checked by hand. Time
zones are where the bugs hide, so try the change against zones that are not
whole hours from UTC or that misbehave around their transitions:

- **Daylight-saving days.** Use the calendar to jump to a transition (the US
  on the first Sunday of November, Europe on the last Sunday of October): the
  warning names it, both abbreviations show, the repeated or skipped hour
  reads right, and offsets between rows change on that day.
- **Fractional offsets.** `Asia/Kolkata` (+5:30), `Asia/Kathmandu` (+5:45),
  `Australia/Adelaide` (+9:30/+10:30) and `Australia/Lord_Howe`, whose clocks
  move by only 30 minutes.
- **The date line.** `Pacific/Kiritimati` (+14) and `Pacific/Pago_Pago` (−11)
  side by side are a full day apart: check the date pills and "tomorrow"
  flags.
- **Polar cities.** `Arctic/Longyearbyen` or `Antarctica/McMurdo`, around
  midsummer and midwinter: daylight shading should be all day or all night,
  not broken.
- **The reference row.** Change it, remove it, and add a city to an empty list
  (the first one becomes the reference); offsets follow it.
- **Scrubbing and parking** with the pointer and with the keyboard (see the
  table in the README): arrows from a parked time adjust it, Esc discards it.
- **Sharing.** Copy times, and save an event; open the `.ics` in a calendar and
  check the time lands right. Under Flatpak it goes through the portal, so
  test there too if you touched `src/share.py`.
- **Sizes and themes.** Below 880px the rows restack; above 1180px the extra
  width becomes margin. Light, dark, 12h and 24h.
- **A language other than English**: `LANGUAGE=es LC_ALL=es_ES.UTF-8 make run`
  catches strings that were not marked for translation and layouts that break
  with longer text.
- **Persistence.** Quit and reopen: the list, labels, order and reference
  survive. The source-tree build keeps them in `~/.config/timezones/`, the
  Flatpak in `~/.var/app/io.github.hernantz.timezones/config/timezones/`.

## Localization

The app's own strings are translated with gettext, one `po/<lang>.po` per
language. City and country names are not in there: they come from the
system's `gweather-locations` and `iso-codes` catalogs, so they are already
translated wherever those packages are. Cities beyond the one each IANA zone is
named for — Seattle, filed under `America/Los_Angeles` — come from libgweather,
which translates them itself.

**Updating an existing translation** after strings have changed in the code:

```sh
make pot                # regenerate po/timezones.pot and merge it into every po/<lang>.po
```

Then open `po/<lang>.po` (in a text editor or a tool such as Poedit or GNOME
Translation Editor) and fill in the empty `msgstr ""` entries and any marked
`#, fuzzy` — a fuzzy entry is a guess from a similar old string, and is ignored
until the flag is removed.

**Adding a new language**, say French:

```sh
echo fr >> po/LINGUAS                               # register the language code
make pot                                            # make sure the template is current
msginit -i po/timezones.pot -o po/fr.po -l fr_FR.UTF-8 --no-translator
```

Translate `po/fr.po`, then check it and try it out:

```sh
msgfmt --check --statistics -o /dev/null po/fr.po   # catches broken placeholders
LANGUAGE=fr LC_ALL=fr_FR.UTF-8 make run
```

Set both variables when running: `LANGUAGE` picks the translated text, `LC_ALL`
picks date words, AM/PM and the first day of the week. If the new language does
not show up, `meson setup --reconfigure builddir` makes meson re-read
`po/LINGUAS`.

Things to know while translating:

- Comments starting with `Translators:` above an entry explain what it is for.
- Entries with a `msgctxt` are short strings that mean different things in
  different places (a lone "M" is Monday's initial); translate each for its own
  context.
- Date formats such as `%b %-d` are translatable on purpose: reorder them to
  suit the language (`%-d %b`), and the locale fills in the words.
- Keep every `{placeholder}` and `%` directive from the original.

**Adding a translatable string** in code: wrap it in `_()` (or `C_()`,
`ngettext()`, `N_()` — see `src/i18n.py`), add the file to `po/POTFILES.in` if it
is not listed yet, and run `make pot`.

## Releasing

`src/VERSION` is the version; meson and `src/const.py` read it, and the rpm
spec, the PKGBUILD and the metainfo `<releases>` are kept in step by
`make release`.

```sh
make release VERSION=1.2.0   # bumps the version, adds a metainfo <release> and changelog entries
# write the notes: replace "TODO: release notes" in data/appdata/*.metainfo.xml
make pot                     # the notes are translatable; translate them in po/<lang>.po
make tag                     # commits the release files and tags v1.2.0
git push --follow-tags
```

`make tag` refuses while the notes are still the placeholder or anything outside
the release files is uncommitted. Pushing the tag runs
`.github/workflows/release.yml`, which:

- builds the Flatpak, signs it and publishes the repository on GitHub Pages
  (`make flatpak-repo`), so existing installs update;
- creates the GitHub Release, with the metainfo notes, the `.flatpak` bundle
  (`make bundle`) and the prebuilt tree FlatPark repackages
  (`make flatpark-payload`);
- pushes the PKGBUILD to the AUR with the tag tarball's checksum.

[Packit](https://packit.dev) (`.packit.yaml`) builds the rpm in the
`hernantz/timezones` COPR when the Release appears. FlatPark notices the new
Release by itself through `packaging/flatpark/resolve-update.sh` and opens its
own update PR. The make targets the workflow runs work locally too.

The [FlatPark](https://flatpark.org) listing is a folder in the
`flatpark/flatpark` repository: `make flatpark-registry` assembles it, pinned to
the current release's published tree, from the templates in
`packaging/flatpark/`.
