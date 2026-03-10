from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from edenfintech_scanner_bootstrap.assets import load_json, sector_knowledge_schema_path
from edenfintech_scanner_bootstrap.schemas import SchemaValidationError, validate_instance

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sector"


class TestSectorSchema(unittest.TestCase):
    """Validate the sector-knowledge JSON Schema against fixtures."""

    @classmethod
    def setUpClass(cls):
        cls.schema = load_json(sector_knowledge_schema_path())
        cls.sample = load_json(FIXTURES_DIR / "sample-knowledge.json")

    def test_valid_knowledge_passes(self):
        validate_instance(self.sample, self.schema)

    def test_missing_kill_factors_rejected(self):
        bad = copy.deepcopy(self.sample)
        del bad["sub_sectors"][0]["kill_factors"]
        with self.assertRaises(SchemaValidationError):
            validate_instance(bad, self.schema)

    def test_empty_sub_sectors_rejected(self):
        bad = copy.deepcopy(self.sample)
        bad["sub_sectors"] = []
        with self.assertRaises(SchemaValidationError):
            validate_instance(bad, self.schema)

    def test_evidence_item_missing_source_url_rejected(self):
        bad = copy.deepcopy(self.sample)
        del bad["sub_sectors"][0]["key_metrics"][0]["source_url"]
        with self.assertRaises(SchemaValidationError):
            validate_instance(bad, self.schema)

    def test_sector_knowledge_schema_path_exists(self):
        path = sector_knowledge_schema_path()
        self.assertTrue(path.exists(), f"schema not found at {path}")
        self.assertEqual(path.name, "sector-knowledge.schema.json")


if __name__ == "__main__":
    unittest.main()
