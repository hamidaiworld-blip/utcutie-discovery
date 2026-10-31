import unittest
from unittest.mock import patch
from io import BytesIO

from source_adapters.base import VideoCandidate, SourceAdapter
from source_adapters.catalog import PublicCatalogAdapter
from source_adapters.registry import build_registry, SourceRegistry


class AdapterContractTests(unittest.TestCase):
    def test_default_adapters_satisfy_shared_interface(self):
        registry = build_registry()
        self.assertEqual(len(registry.entries()), 5)
        for adapter in registry.discovery_adapters():
            self.assertIsInstance(adapter, SourceAdapter)
            self.assertTrue(callable(adapter.discover))
            self.assertTrue(callable(adapter.close))

    def test_registry_has_no_unapproved_publication_adapters(self):
        registry = build_registry()
        self.assertEqual(registry.publication_adapters(), ())
        self.assertTrue(all(not e.publication_approved for e in registry.entries()))

    def test_duplicate_source_ids_are_rejected(self):
        registry = build_registry()
        entry = registry.entries()[0]
        with self.assertRaises(ValueError):
            SourceRegistry([entry, entry])

    def test_candidate_is_not_publishable_without_verified_rights_and_media(self):
        self.assertFalse(VideoCandidate("x", "https://example.com/v", "Cute", rights_status="discovery_only").publishable)
        self.assertFalse(VideoCandidate("x", "https://example.com/v", "Cute", media_url="https://cdn.example/v.mp4", rights_status="unverified").publishable)
        self.assertTrue(VideoCandidate("x", "https://example.com/v", "Cute", media_url="https://cdn.example/v.mp4", rights_status="approved").publishable)

    @patch("source_adapters.catalog.urlopen")
    def test_catalog_adapter_extracts_same_host_page_links_only(self, mocked):
        body = b'<a href="/videos/cute-cat">Cute cat video</a><a href="https://evil.example/steal">Cute dog</a><a href="http://example.com/insecure">Cute bird</a>'
        mocked.return_value.__enter__.return_value = type("Response", (), {"status": 200, "read": lambda self, n: body})()
        adapter = PublicCatalogAdapter("fixture", "https://example.com/catalog", "discovery_only")
        results = adapter.discover("cute", 10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source_url, "https://example.com/videos/cute-cat")
        self.assertIsNone(results[0].media_url)
        self.assertFalse(results[0].publishable)

    def test_nonpositive_limit_returns_empty(self):
        adapter = PublicCatalogAdapter("fixture", "https://example.com/catalog", "discovery_only")
        self.assertEqual(adapter.discover("cute", 0), [])


if __name__ == "__main__":
    unittest.main()
