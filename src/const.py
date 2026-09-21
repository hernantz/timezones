"""The application id and version, in one place.

Anything that has to agree with data/io.github.hernantz.timezones.* (the desktop
entry, the GSettings schema, the icon and the resource bundle) reads the id
from here, so renaming the app only means renaming those files and APP_ID.
"""

from __future__ import annotations

from pathlib import Path

APP_ID = "io.github.hernantz.timezones"

# GResource paths are the id as a path, which is what gresource.xml declares.
RESOURCE_PREFIX = "/" + APP_ID.replace(".", "/")

GRESOURCE_BUNDLE = f"{APP_ID}.gresource"

# src/VERSION is also what meson passes to project(), and it is installed
# beside this module, so a release means editing that one file.
VERSION = (Path(__file__).parent / "VERSION").read_text().strip()
