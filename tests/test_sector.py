from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from edenfintech_scanner_bootstrap.assets import load_json, sector_knowledge_schema_path
from edenfintech_scanner_bootstrap.schemas import SchemaValidationError, validate_instance
from edenfintech_scanner_bootstrap.sector import (
    KNOWLEDGE_CATEGORIES,
    STALENESS_DAYS,
    _slugify,
    check_sector_freshness,
    hydrate_sector,
    load_sector_knowledge,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "sector"


def _mock_evidence_item():
    return {
        "claim": "Test claim about the sub-sector.",
        "source_title": "Test Source",
        "source_url": "https://example.com/test",
        "confidence_note": "Test note",
    }


def _make_mock_transport():
    """Return a mock transport that returns valid sector evidence."""
    response_text = json.dumps({"items": [_mock_evidence_item()]})
    mock_response = {
        "candidates": [
            {"content": {"parts": [{"text": response_text}]}}
        ]
    }

    def transport(url, headers, payload):
        return mock_response

    return transport


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


class TestSlugify(unittest.TestCase):
    def test_consumer_defensive(self):
        self.assertEqual(_slugify("Consumer Defensive"), "consumer-defensive")

    def test_technology(self):
        self.assertEqual(_slugify("Technology"), "technology")

    def test_strips_trailing_hyphens(self):
        self.assertEqual(_slugify("  Energy  "), "energy")


class TestHydrateSector(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_writes_valid_knowledge_json(self):
        from edenfintech_scanner_bootstrap.gemini import GeminiClient

        transport = _make_mock_transport()
        client = GeminiClient("fake-key", transport=transport)
        result = hydrate_sector(
            "Consumer Defensive",
            sub_sectors=["Household Products"],
            client=client,
            project_root=self.project_root,
        )
        schema = load_json(sector_knowledge_schema_path())
        validate_instance(result, schema)

        knowledge_path = self.project_root / "data" / "sectors" / "consumer-defensive" / "knowledge.json"
        self.assertTrue(knowledge_path.exists())
        on_disk = json.loads(knowledge_path.read_text())
        validate_instance(on_disk, schema)

    def test_updates_registry(self):
        from edenfintech_scanner_bootstrap.gemini import GeminiClient

        transport = _make_mock_transport()
        client = GeminiClient("fake-key", transport=transport)
        hydrate_sector(
            "Consumer Defensive",
            sub_sectors=["Household Products"],
            client=client,
            project_root=self.project_root,
        )

        registry_path = self.project_root / "data" / "sectors" / "registry.json"
        self.assertTrue(registry_path.exists())
        registry = json.loads(registry_path.read_text())
        entry = registry["sectors"]["consumer-defensive"]
        self.assertEqual(entry["sector_name"], "Consumer Defensive")
        self.assertIn("hydrated_at", entry)
        self.assertEqual(entry["sub_sectors"], ["Household Products"])
        self.assertIn("knowledge_path", entry)

    def test_raises_without_sub_sectors(self):
        from edenfintech_scanner_bootstrap.gemini import GeminiClient

        client = GeminiClient("fake-key", transport=_make_mock_transport())
        with self.assertRaises(ValueError):
            hydrate_sector("Consumer Defensive", client=client, project_root=self.project_root)


class TestLoadSectorKnowledge(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_loads_and_validates(self):
        # Write fixture to temp dir
        sector_dir = self.project_root / "data" / "sectors" / "consumer-defensive"
        sector_dir.mkdir(parents=True)
        sample = load_json(FIXTURES_DIR / "sample-knowledge.json")
        (sector_dir / "knowledge.json").write_text(json.dumps(sample, indent=2))

        # Also write registry
        registry = {
            "sectors": {
                "consumer-defensive": {
                    "sector_name": "Consumer Defensive",
                    "hydrated_at": datetime.now().isoformat(),
                    "sub_sectors": ["Household Products"],
                    "knowledge_path": "data/sectors/consumer-defensive/knowledge.json",
                }
            }
        }
        registry_path = self.project_root / "data" / "sectors" / "registry.json"
        registry_path.write_text(json.dumps(registry, indent=2))

        result = load_sector_knowledge("Consumer Defensive", project_root=self.project_root)
        schema = load_json(sector_knowledge_schema_path())
        validate_instance(result, schema)

    def test_raises_for_unknown_sector(self):
        with self.assertRaises(FileNotFoundError):
            load_sector_knowledge("Unknown Sector", project_root=self.project_root)


class TestSectorFreshness(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write_registry(self, hydrated_at):
        registry = {
            "sectors": {
                "consumer-defensive": {
                    "sector_name": "Consumer Defensive",
                    "hydrated_at": hydrated_at,
                    "sub_sectors": ["Household Products"],
                    "knowledge_path": "data/sectors/consumer-defensive/knowledge.json",
                }
            }
        }
        registry_dir = self.project_root / "data" / "sectors"
        registry_dir.mkdir(parents=True, exist_ok=True)
        (registry_dir / "registry.json").write_text(json.dumps(registry, indent=2))

    def test_fresh_sector(self):
        self._write_registry(datetime.now().isoformat())
        result = check_sector_freshness("Consumer Defensive", project_root=self.project_root)
        self.assertEqual(result["status"], "FRESH")
        self.assertFalse(result["stale"])

    def test_stale_sector(self):
        old_date = (datetime.now() - timedelta(days=200)).isoformat()
        self._write_registry(old_date)
        result = check_sector_freshness("Consumer Defensive", project_root=self.project_root)
        self.assertEqual(result["status"], "STALE")
        self.assertTrue(result["stale"])

    def test_not_hydrated(self):
        result = check_sector_freshness("Unknown Sector", project_root=self.project_root)
        self.assertEqual(result["status"], "NOT_HYDRATED")
        self.assertTrue(result["stale"])


class TestGeminiSectorQueries(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_eight_queries_per_sub_sector(self):
        from edenfintech_scanner_bootstrap.gemini import GeminiClient

        call_count = 0
        response_text = json.dumps({"items": [_mock_evidence_item()]})
        mock_response = {
            "candidates": [{"content": {"parts": [{"text": response_text}]}}]
        }

        def counting_transport(url, headers, payload):
            nonlocal call_count
            call_count += 1
            return mock_response

        client = GeminiClient("fake-key", transport=counting_transport)
        hydrate_sector(
            "Consumer Defensive",
            sub_sectors=["Household Products"],
            client=client,
            project_root=self.project_root,
        )
        self.assertEqual(call_count, 8)

    def test_sixteen_queries_for_two_sub_sectors(self):
        from edenfintech_scanner_bootstrap.gemini import GeminiClient

        call_count = 0
        response_text = json.dumps({"items": [_mock_evidence_item()]})
        mock_response = {
            "candidates": [{"content": {"parts": [{"text": response_text}]}}]
        }

        def counting_transport(url, headers, payload):
            nonlocal call_count
            call_count += 1
            return mock_response

        client = GeminiClient("fake-key", transport=counting_transport)
        hydrate_sector(
            "Consumer Defensive",
            sub_sectors=["Household Products", "Food Products"],
            client=client,
            project_root=self.project_root,
        )
        self.assertEqual(call_count, 16)


if __name__ == "__main__":
    unittest.main()
