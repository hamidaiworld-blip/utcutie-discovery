import unittest
from source_qualification import build_report, qualify_source


def approved_source():
    return {
        "name": "Example source", "url": "https://media.example.org/videos",
        "automated_access_permission": {"status": "approved", "evidence_url": "https://example.org/terms#automation"},
        "terms_review": {"status": "approved", "evidence_url": "https://example.org/terms"},
        "robots_review": {"status": "approved", "evidence_url": "https://example.org/robots.txt"},
        "media_download_permission": {"status": "approved", "evidence_url": "https://example.org/api-policy"},
        "media_delivery_method": "official_api", "drm_or_access_control_bypass": False,
        "redistribution_permission": {"status": "approved", "evidence_reference": "Archived permission PERM-001"},
        "rights_evidence_type": "written_permission", "rights_holder": "Example Media Ltd.",
        "telegram_public_channel_republication": True, "zero_cost": True,
        "attribution_required": True, "required_attribution": "Video courtesy of Example Media Ltd.",
    }


class SourceQualificationTests(unittest.TestCase):
    def test_legacy_flags_are_not_evidence(self):
        result = qualify_source({"name": "Legacy", "url": "https://example.org",
                                 "automated_access": True, "media_download_allowed": True,
                                 "auto_publish_allowed": True, "rights_status": "approved"})
        self.assertEqual(result["qualification_status"], "manual_review_required")
        self.assertFalse(result["discovery_eligible"])
        self.assertFalse(result["download_eligible"])

    def test_complete_evidence_passes_source_level_only(self):
        result = qualify_source(approved_source())
        self.assertEqual(result["qualification_status"], "approved_for_republication_source_level")
        self.assertTrue(result["discovery_eligible"])
        self.assertTrue(result["download_eligible"])
        self.assertTrue(result["source_level_republication_eligible"])
        self.assertTrue(result["candidate_level_rights_check_still_required"])

    def test_approval_without_evidence_is_unknown(self):
        source = approved_source()
        source["terms_review"] = {"status": "approved"}
        self.assertFalse(qualify_source(source)["discovery_eligible"])

    def test_explicit_prohibition_blocks(self):
        source = approved_source()
        source["automated_access_permission"]["status"] = "prohibited"
        result = qualify_source(source)
        self.assertEqual(result["qualification_status"], "blocked")
        self.assertFalse(result["discovery_eligible"])

    def test_download_requires_official_delivery_method(self):
        source = approved_source()
        source["media_delivery_method"] = "browser_extraction"
        result = qualify_source(source)
        self.assertTrue(result["discovery_eligible"])
        self.assertFalse(result["download_eligible"])
        self.assertEqual(result["qualification_status"], "approved_for_discovery_only")

    def test_republication_requires_telegram_scope_and_zero_cost(self):
        source = approved_source()
        source["telegram_public_channel_republication"] = False
        result = qualify_source(source)
        self.assertTrue(result["download_eligible"])
        self.assertFalse(result["source_level_republication_eligible"])
        self.assertEqual(result["qualification_status"], "approved_for_download_only")

    def test_report_never_enables_automation_or_publishing(self):
        report = build_report({"sources": [approved_source()]})
        self.assertFalse(report["automation_enabled"])
        self.assertFalse(report["downloads_enabled"])
        self.assertFalse(report["publishing_enabled"])

    def test_invalid_url_fails_closed(self):
        source = approved_source()
        source["url"] = "javascript:alert(1)"
        result = qualify_source(source)
        self.assertFalse(result["discovery_eligible"])
        self.assertEqual(result["qualification_status"], "manual_review_required")

    def test_source_ids_distinguish_paths_on_same_domain(self):
        base = {"name": "NatGeo", "url": "https://kids.example.org/videos"}
        other = {"name": "NatGeo animals", "url": "https://kids.example.org/videos/topic/animals"}
        self.assertNotEqual(qualify_source(base)["source_id"], qualify_source(other)["source_id"])


if __name__ == "__main__":
    unittest.main()
