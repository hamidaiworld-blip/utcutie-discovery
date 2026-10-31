"""Isolated source discovery adapters for UTCutie."""

from .base import SourceAdapter, VideoCandidate
from .registry import build_registry

__all__ = ["SourceAdapter", "VideoCandidate", "build_registry"]
