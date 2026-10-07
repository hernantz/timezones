from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

from . import tzinfo_helpers as tzinfo
from .const import APP_ID
from .model import City

if TYPE_CHECKING:
    from .tzinfo_helpers import Place

XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
DATA_DIR = XDG_CONFIG_HOME / "timezones"
CITIES_FILE = DATA_DIR / "cities.json"

# Bumped only when older code would misread the file; a new optional field is
# ignored by older code and needs no bump. Each bump adds a step to _MIGRATIONS.
SCHEMA_VERSION = 1

# Set when the file came from a newer version: saving with this version's
# format would drop whatever that version added, so nothing is written.
_save_blocked = False


@dataclass
class LoadedCities:
    cities: list[City]
    # Saved by a newer version of the app; changes this session are not saved.
    newer: bool = False
    # An unreadable file, moved here so the empty list never overwrites it.
    broken_copy: Path | None = None


def _atomic_write_json(path: Path, payload: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


# version -> the step that turns it into version + 1; a file several versions
# behind goes through each in turn. The first one will be {1: _v1_to_v2}.
_MIGRATIONS: dict[int, Callable[[dict], dict]] = {}


def _migrate(data: dict, version: int) -> dict:
    while version < SCHEMA_VERSION:
        data = _MIGRATIONS[version](data)
        version += 1
    return data


def _move_aside(path: Path) -> Path | None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.broken-{stamp}")
    try:
        path.replace(target)
    except OSError:
        return None
    return target


def load_cities() -> LoadedCities:
    global _save_blocked
    try:
        text = CITIES_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return LoadedCities([])
    except OSError:
        # There, but not readable: saving would replace what could not be read.
        _save_blocked = True
        return LoadedCities([])

    try:
        data = json.loads(text)
        version = data.get("schema_version", 1)
        if not isinstance(version, int) or version < 1:
            raise ValueError(f"bad schema_version {version!r}")
        newer = version > SCHEMA_VERSION
        if version < SCHEMA_VERSION:
            # Kept until the user removes it, in case a migration step is wrong.
            backup = CITIES_FILE.with_name(f"cities.v{version}.json.bak")
            if not backup.exists():
                try:
                    backup.write_text(text, encoding="utf-8")
                except OSError:
                    pass
            data = _migrate(data, version)
        cities = _parse_cities(data)
    except Exception:
        return LoadedCities([], broken_copy=_move_aside(CITIES_FILE))

    if newer:
        # Read as well as this version can (unknown fields are ignored), but
        # left untouched on disk.
        _save_blocked = True
    return LoadedCities(cities, newer=newer)


def _parse_cities(data: dict) -> list[City]:
    raw = data.get("cities")
    if not isinstance(raw, list):
        raise ValueError("no cities list")
    cities: list[City] = []
    for entry in raw:
        if isinstance(entry, dict) and entry.get("tz"):
            cities.append(
                City(
                    tz=str(entry["tz"]),
                    label=str(entry.get("label", "")),
                    is_reference=bool(entry.get("is_reference", False)),
                    place=_load_place(entry.get("place")),
                )
            )
    return cities


def _load_place(raw) -> Place | None:
    """A saved place, or None for a row named after its zone, or for one
    GWeather no longer knows — which then shows the zone's own city rather
    than vanishing."""
    if not isinstance(raw, str) or not raw:
        return None
    return tzinfo.deserialize_place(raw)


def save_cities(cities: list[City]) -> None:
    if _save_blocked:
        return
    payload = []
    for c in cities:
        entry = {"tz": c.tz, "label": c.label, "is_reference": c.is_reference}
        if c.place is not None:
            # GWeather's own serialization, the one GNOME Clocks and Weather
            # store their locations in.
            entry["place"] = tzinfo.serialize_place(c.place)
        payload.append(entry)
    _atomic_write_json(CITIES_FILE, {"schema_version": SCHEMA_VERSION, "cities": payload})


class Settings:
    def __init__(self) -> None:
        self._settings = Gio.Settings.new(APP_ID)

    def get_bool(self, key: str, default: bool) -> bool:
        try:
            return self._settings.get_value(key).get_boolean()
        except Exception:
            return default

    def get_string(self, key: str, default: str) -> str:
        try:
            return self._settings.get_string(key)
        except Exception:
            return default

    def set_bool(self, key: str, val: bool) -> None:
        self._settings.set_boolean(key, val)

    def set_string(self, key: str, val: str) -> None:
        self._settings.set_string(key, val)
