from __future__ import annotations

import json
import os
from pathlib import Path

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

from .const import APP_ID
from .model import City

XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
DATA_DIR = XDG_CONFIG_HOME / "timezones"
CITIES_FILE = DATA_DIR / "cities.json"


def _atomic_write_json(path: Path, payload: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_cities(default: list[City]) -> list[City]:
    if not CITIES_FILE.exists():
        return default
    try:
        data = json.loads(CITIES_FILE.read_text(encoding="utf-8"))
        raw = data.get("cities")
        if not isinstance(raw, list):
            return default
        cities: list[City] = []
        for entry in raw:
            if isinstance(entry, str):
                cities.append(City(tz=entry))
            elif isinstance(entry, dict) and entry.get("tz"):
                cities.append(
                    City(
                        tz=str(entry["tz"]),
                        label=str(entry.get("label", "")),
                        is_reference=bool(entry.get("is_reference", False)),
                    )
                )
        # An empty list is a state the user can actually reach (removing every
        # timezone), so it has to survive a restart — only a missing or
        # unreadable file falls back to the defaults.
        return cities
    except Exception:
        return default


def save_cities(cities: list[City]) -> None:
    payload = [
        {"tz": c.tz, "label": c.label, "is_reference": c.is_reference} for c in cities
    ]
    _atomic_write_json(CITIES_FILE, {"schema_version": 2, "cities": payload})


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
