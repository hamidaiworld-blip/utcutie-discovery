import unittest
from rights_review import evidence, review

URL = "https://www.thedodo.com/example"
CREATOR = "https://example.org/creator"
BASE = {"source_url": URL, "rightsholder": "Creator", "rightsholder_url": CREATOR,
        "rights_basis": "written permission", "permission_reference": "signed-consent-001",
        "attribution": "Creator", "telegram_republication_allowed": True, "reuse_allowed": True}
CANDIDATE = {"article_url": URL, "original_creator_url": CREATOR, "rights_status": "pending"}

class RightsGateTests(unittest.TestCase):
    def test_no_approval_stays_pending(self):
        self.assertEqual(review([CANDIDATE], [])[0]["rights_status"], "pending")
    def test_untrusted_verified_flag_cannot_bypass_gate(self):
        self.assertEqual(review([{**CANDIDATE, "rights_status": "verified", "auto_publish_allowed": True}], [])[0]["rights_status"], "pending")
    def test_valid_exact_permission_marks_verified_but_never_queues(self):
        c = review([CANDIDATE], [BASE])[0]
        self.assertEqual(c["rights_status"], "verified")
        self.assertFalse(c["auto_publish_allowed"])
        self.assertTrue(c["discovery_only"])
    def test_mismatched_creator_blocks(self):
        self.assertEqual(review([CANDIDATE], [{**BASE, "rightsholder_url": "https://example.org/other"}])[0]["rights_status"], "pending")
    def test_missing_telegram_permission_blocks(self):
        self.assertFalse(evidence({**BASE, "telegram_republication_allowed": False}))
    def test_excluded_cannot_be_resurrected(self):
        self.assertEqual(review([{**CANDIDATE, "rights_status": "excluded"}], [BASE])[0]["rights_status"], "excluded")
    def test_duplicate_conflicting_approvals_block(self):
        self.assertEqual(review([CANDIDATE], [BASE, BASE])[0]["rights_status"], "pending")

if __name__ == "__main__":
    unittest.main()
