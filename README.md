<div align="center">
  <img src="data/icons/hicolor/scalable/apps/io.github.hernantz.timezones.svg" width="128" height="128" alt="Timezones icon">
  <h1>Timezones</h1>
</div>

Timezones is a native GTK4 / Libadwaita app that shows a grid of cities and timezones on one shared timeline, so a glance tells you who
is asleep, who is at work, and what an hour of your day looks like everywhere at
once. Park the cursor on a given time and every row reads that same instant to plan your next meeting.

<p align="center">
  <img src="data/screenshots/main-light.png" width="720" alt="The main window, with an hour parked on the timeline">
</p>

## Features

### The timeline

- **One shared grid.** Easily compare at glance what a given time represent on different timezones.
- **Scrub to compare.** Move the pointer across the list and every row previews
  its local time for the instant under the cursor, marked in accent color so a
  preview is never mistaken for the real current time.
- **Park an hour.** Click (or press Enter) to pin the instant. A bar names the
  reading and stays until you discard it; the rows keep showing that moment
  while you compare them.
- **Daylight shading.** Cells are colored by whether the sun is actually above
  the horizon over that city — computed from the zone's own coordinates, so it
  holds inside the polar circles too — with sunrise and sunset markers on the
  strip.
- **Date flags.** A timezone whose day rolls over inside the visible window carries a
  date pill naming the day that begins there, so a "tomorrow" is never silent.
- **Daylight-saving warnings.** A row spending the day on both sides of a
  transition says so in words ("Clocks in Cairo move back 1 hour…") and shows
  both abbreviations, e.g. `EDT → EST`.
- **Offset pills.** Each non-reference row shows how far ahead of or behind the
  reference it is — not just UTC, which is rarely the number you want.

<p align="center">
  <img src="data/screenshots/daylight-saving-warnings-light.png" width="720" alt="Daylight-saving warnings on New York and Los Angeles as their clocks move back">
</p>

### Keyboard navigation

The timeline is a single focusable control, the way a slider is: **Tab** to the
list, then drive it with the arrows.

| Key | Action |
| --- | --- |
| <kbd>Tab</kbd> | Focus the timeline list (it takes focus itself before its rows) |
| <kbd>←</kbd> / <kbd>→</kbd> | Scrub 15 minutes at a time, snapped to quarter hours |
| <kbd>Enter</kbd> / <kbd>Space</kbd> | Park the cursor on the hour it is on |
| <kbd>Esc</kbd> | Discard the parked time (from anywhere in the window) |
| <kbd>Ctrl</kbd>+<kbd>N</kbd> | Add a timezone |
| <kbd>Ctrl</kbd>+<kbd>T</kbd> | Back to today |
| <kbd>Ctrl</kbd>+<kbd>,</kbd> | Preferences |
| <kbd>Ctrl</kbd>+<kbd>Q</kbd> | Quit |

Arrows work from wherever the cursor already is — the keyboard's own position,
a parked selection, the pointer, or simply *now* — and nudging a parked time
adjusts it in place rather than unpinning it first.

### Planning ahead

- **Jump to any date** from the calendar button, and the whole list moves with
  it, daylight-saving changes included. A "Today" button appears only while you
  are parked somewhere else.
- **Copy all times** for the parked instant to the clipboard as an aligned
  block, one line per city, with a date in brackets on any row that is on a
  different day.
- **Save a calendar event.** A parked instant becomes a 30-minute `.ics` invite,
  timed in UTC, with the whole per-city comparison in its description, handed to
  whatever application handles calendar files (through the portal under Flatpak).

<p align="center">
  <img src="data/screenshots/add-timezone-light.png" width="560" alt="Searching the timezone list">
</p>

### Your list

- **Search ~400 zones** by city, country, abbreviation or zone id, each result
  showing its current time and offset.
- **Label a row** — "You", "Family", "Team" — and it keeps the city name beside
  the label everywhere it is shared.
- **Pick the reference row**, the one the timeline's hours and every offset are
  measured from.
- **Reorder** by dragging a row onto another, by the row menu's *Move up* /
  *Move down*, or from the reorder dialog in Preferences.
- The list persists to `~/.config/timezones/cities.json`, including an empty one.

### Appearance

- Light, dark, or follow the system.
- 12 or 24-hour clocks, from the header toggle or Preferences.
- Offset pills and daylight shading can each be turned off.
- **Adaptive layout.** Below 880px the rows restack for a phone-width window
  instead of being squeezed; past 1180px the surplus becomes margin, so an hour
  reads at the same scale on an ultrawide as on a laptop.

<p align="center">
  <img src="data/screenshots/main-dark.png" width="560" alt="Dark theme">
</p>

On a phone-width screen each row stacks its timeline under the city, and the
header drops the 12/24h toggle (it stays in Preferences):

<p align="center">
  <img src="data/screenshots/mobile-light.png" width="280" alt="The stacked layout at phone width">
  <img src="data/screenshots/mobile-dark.png" width="280" alt="The stacked layout at phone width, dark theme">
</p>

## Installing

### Flatpak

From the app's own Flatpak repository, which keeps it updated through
`flatpak update` and GNOME Software:

```sh
flatpak install --user https://hernantz.github.io/timezones/io.github.hernantz.timezones.flatpakref
```

Or download `timezones-<version>.flatpak` from the
[releases page](https://github.com/hernantz/timezones/releases) and open it;
it installs from the same repository, so it updates the same way. Either way
the GNOME runtime comes from Flathub, which is added if missing.

### FlatPark

Also listed on [FlatPark](https://flatpark.org/apps/io.github.hernantz.timezones/),
a community Flatpak repository:

```sh
flatpak --user remote-add --if-not-exists flatpark https://dl.flatpark.org/flatpark.flatpakrepo
flatpak --user install flatpark io.github.hernantz.timezones
```

### Fedora (COPR)

```sh
sudo dnf copr enable hernantz/timezones
sudo dnf install timezones
```

Fedora 43 or newer.

### Arch Linux (AUR)

`timezones` in the AUR, e.g. `yay -S timezones`.

### From source

```sh
make setup      # meson setup builddir
make install    # meson install -C builddir
```

To build the Flatpak from the source tree instead (needs the
`org.gnome.Platform` and `org.gnome.Sdk` runtimes, version 51):

```sh
flatpak-builder --user --install --force-clean build-flatpak packaging/flatpak/io.github.hernantz.timezones.json
flatpak run io.github.hernantz.timezones
```

## Contributing

Pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) covers running
the app from source, the code layout, what to test, translations and how
releases are made.

## License

GPL-3.0-or-later.
