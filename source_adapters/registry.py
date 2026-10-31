from __future__ import annotations

from dataclasses import dataclass

from .base import SourceAdapter
from .catalog import PublicCatalogAdapter


@dataclass(frozen=True)
class SourceEntry:
    source_id: str
    name: str
    catalog_url: str
    policy: str
    notes: str
    adapter: SourceAdapter

    @property
    def discovery_enabled(self) -> bool:
        return self.policy in {"discovery_only", "review_required"}

    @property
    def publication_approved(self) -> bool:
        return self.policy == "approved"


class SourceRegistry:
    def __init__(self, entries: list[SourceEntry]):
        self._entries = {entry.source_id: entry for entry in entries}
        if len(self._entries) != len(entries):
            raise ValueError("Duplicate source_id in registry")

    def entries(self) -> tuple[SourceEntry, ...]:
        return tuple(self._entries.values())

    def get(self, source_id: str) -> SourceEntry:
        return self._entries[source_id]

    def discovery_adapters(self) -> tuple[SourceAdapter, ...]:
        return tuple(e.adapter for e in self._entries.values() if e.discovery_enabled)

    def publication_adapters(self) -> tuple[SourceAdapter, ...]:
        return tuple(e.adapter for e in self._entries.values() if e.publication_approved)


def build_registry() -> SourceRegistry:
    # Conservative initial policy: none of the reviewed sites has supplied
    # an explicit licence/permission for reposting to the Telegram channel.
    definitions = [
        ("shutterstock", "Shutterstock", "https://www.shutterstock.com/video/search/cute-animals", "review_required", "Stock footage is licensed; use only after purchasing a licence that expressly covers the intended Telegram redistribution."),
        ("thedodo", "The Dodo", "https://www.thedodo.com/", "discovery_only", "Editorial discovery only. Obtain written permission or a suitable licence before downloading or reposting."),
        ("natgeo_kids", "National Geographic Kids Videos", "https://kids.nationalgeographic.com/videos", "discovery_only", "Editorial discovery only. Copyrighted video; no republication permission established."),
        ("natgeo_amazing_animals", "National Geographic Amazing Animals", "https://kids.nationalgeographic.com/videos/topic/amazing-animals", "discovery_only", "Editorial discovery only. Copyrighted video; no republication permission established."),
        ("somepets", "SomePets Cute Videos", "https://www.somepets.com/category/cute/cute-videos/", "review_required", "Ownership, contributor rights, and reuse terms must be verified before any media use."),
    ]
    entries = []
    for source_id, name, url, policy, notes in definitions:
        host = url.split("/")[2]
        adapter = PublicCatalogAdapter(source_id, url, policy, allowed_hosts=(host,))
        entries.append(SourceEntry(source_id, name, url, policy, notes, adapter))
    return SourceRegistry(entries)
