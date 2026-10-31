import json
import unittest
from pathlib import Path
from source_registry import validate_registry


class SourceRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = json.loads(Path("source_registry.json").read_text(encoding="utf-8"))

    def test_current_registry_is_valid_and_inert(self):
        self.assertEqual(validate_registry(self.registry), [])
        self.assertTrue(all(s["review_status"] == "proposed" for s in self.registry["sources"]))
        self.assertTrue(all(s["automation_status"] == "disabled" for s in self.registry["sources"]))

    def test_duplicate_source_id_is_rejected(self):
        self.registry["sources"].append(dict(self.registry["sources"][0]))
        self.assertTrue(any("Duplicate source_id" in e for e in validate_registry(self.registry)))

    def test_non_https_source_is_rejected(self):
        self.registry["sources"][0]["url"] = "http://example.com/video"
        self.assertTrue(any("HTTPS" in e for e in validate_registry(self.registry)))

    def test_global_automation_cannot_be_enabled(self):
        self.registry["defaults"]["auto_publish_enabled"] = True
        self.assertTrue(any("Global defaults" in e for e in validate_registry(self.registry)))

    def test_approval_without_rights_evidence_is_rejected(self):
        self.registry["sources"][0]["review_status"] = "approved"
        self.assertTrue(any("approved entries require reviewer" in e for e in validate_registry(self.registry)))

    def test_access_control_bypass_is_always_rejected(self):
        self.registry["sources"][0]["drm_or_access_control_bypass"] = True
        self.assertTrue(any("bypassing DRM" in e for e in validate_registry(self.registry)))


if __name__ == "__main__":
    unittest.main()
