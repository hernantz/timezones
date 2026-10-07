"""Saved city lists from every schema version still load, and a file this
version cannot read is never overwritten."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import persistence
from src.model import City

DATA = Path(__file__).parent / "data"


class PersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.file = self.dir / "cities.json"
        for name, value in {
            "DATA_DIR": self.dir,
            "CITIES_FILE": self.file,
            "_save_blocked": False,
        }.items():
            patcher = mock.patch.object(persistence, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def use(self, fixture: str) -> None:
        shutil.copy(DATA / fixture, self.file)

    def write(self, payload) -> None:
        self.file.write_text(json.dumps(payload), encoding="utf-8")

    def test_missing_file_gives_empty_list(self) -> None:
        loaded = persistence.load_cities()
        self.assertEqual(loaded.cities, [])
        self.assertFalse(loaded.newer)
        self.assertIsNone(loaded.broken_copy)

    def test_v1_loads(self) -> None:
        self.use("cities-v1.json")
        loaded = persistence.load_cities()
        self.assertEqual(
            loaded.cities,
            [
                City(tz="America/Argentina/Buenos_Aires", is_reference=True),
                City(tz="Europe/Madrid", label="Office"),
            ],
        )
        self.assertFalse(loaded.newer)
        self.assertEqual(list(self.dir.iterdir()), [self.file])

    def test_older_version_is_migrated_and_backed_up(self) -> None:
        # A stand-in for the first real step: v2 renames "label" to "name".
        def v1_to_v2(data: dict) -> dict:
            rows = [{**row, "name": row.pop("label", "")} for row in data["cities"]]
            return {"schema_version": 2, "cities": rows}

        self.use("cities-v1.json")
        with mock.patch.object(persistence, "SCHEMA_VERSION", 2), \
                mock.patch.dict(persistence._MIGRATIONS, {1: v1_to_v2}), \
                mock.patch.object(persistence, "_parse_cities", side_effect=lambda d: d["cities"]):
            rows = persistence.load_cities().cities
        self.assertEqual([row["name"] for row in rows], ["", "Office"])

        backup = self.dir / "cities.v1.json.bak"
        self.assertEqual(backup.read_text(), (DATA / "cities-v1.json").read_text())

    def test_empty_list_survives(self) -> None:
        self.write({"schema_version": 1, "cities": []})
        self.assertEqual(persistence.load_cities().cities, [])

    def test_newer_version_is_read_but_never_written(self) -> None:
        payload = {
            "schema_version": persistence.SCHEMA_VERSION + 1,
            "cities": [{"tz": "Asia/Tokyo", "colour": "red"}],
        }
        self.write(payload)
        before = self.file.read_text()

        loaded = persistence.load_cities()
        self.assertTrue(loaded.newer)
        self.assertEqual([c.tz for c in loaded.cities], ["Asia/Tokyo"])

        persistence.save_cities([City(tz="UTC")])
        self.assertEqual(self.file.read_text(), before)

    def test_unreadable_file_is_moved_aside(self) -> None:
        for content in ["{not json", "[]", '{"schema_version": 1}', '{"schema_version": "x", "cities": []}']:
            with self.subTest(content=content):
                self.file.write_text(content, encoding="utf-8")
                loaded = persistence.load_cities()
                self.assertEqual(loaded.cities, [])
                self.assertIsNotNone(loaded.broken_copy)
                self.assertEqual(loaded.broken_copy.read_text(), content)
                self.assertFalse(self.file.exists())

                # An empty list can now be saved without losing the broken file.
                persistence.save_cities(loaded.cities)
                self.assertEqual(loaded.broken_copy.read_text(), content)
                loaded.broken_copy.unlink()


if __name__ == "__main__":
    unittest.main()
