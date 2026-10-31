from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class VideoCandidate:
    source_id: str
    source_url: str
    title: str
    media_url: str | None = None
    duration_seconds: float | None = None
    rights_status: str = "unverified"
    metadata: dict[str, str] | None = None

    @property
    def publishable(self) -> bool:
        # Discovery is never equivalent to a licence or permission to republish.
        return self.rights_status == "approved" and bool(self.media_url)


@runtime_checkable
class SourceAdapter(Protocol):
    source_id: str

    def discover(self, query: str, limit: int = 20) -> list[VideoCandidate]:
        """Return normalized candidates; never download or publish media."""

    def close(self) -> None:
        """Release resources. Stateless adapters may do nothing."""
