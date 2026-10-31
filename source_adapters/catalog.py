from __future__ import annotations

from html.parser import HTMLParser
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from .base import VideoCandidate


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(" ".join(self._text).split())))
            self._href = None
            self._text = []


class PublicCatalogAdapter:
    """Conservative HTML catalog discovery. It extracts page links only.

    It deliberately does not extract protected media streams, bypass access
    controls, download videos, or infer reuse permission.
    """

    def __init__(self, source_id: str, catalog_url: str, rights_status: str,
                 allowed_hosts: tuple[str, ...] | None = None, timeout: int = 15):
        self.source_id = source_id
        self.catalog_url = catalog_url
        self.rights_status = rights_status
        self.allowed_hosts = allowed_hosts or (urlparse(catalog_url).hostname or "",)
        self.timeout = timeout

    def discover(self, query: str, limit: int = 20) -> list[VideoCandidate]:
        if limit < 1:
            return []
        request = Request(self.catalog_url, headers={"User-Agent": "UTCutieSourceResearch/1.0"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                if response.status != 200:
                    return []
                html = response.read(2_000_000).decode("utf-8", errors="replace")
        except (URLError, TimeoutError, OSError):
            return []

        parser = _Links()
        parser.feed(html)
        terms = {part.casefold() for part in query.split() if len(part) > 2}
        found: list[VideoCandidate] = []
        seen: set[str] = set()
        for href, title in parser.links:
            absolute = urljoin(self.catalog_url, href)
            parsed = urlparse(absolute)
            host = (parsed.hostname or "").casefold()
            if parsed.scheme != "https" or host not in self.allowed_hosts:
                continue
            if absolute in seen or not title:
                continue
            if terms and not any(term in title.casefold() for term in terms):
                continue
            seen.add(absolute)
            found.append(VideoCandidate(
                source_id=self.source_id,
                source_url=absolute,
                title=title,
                rights_status=self.rights_status,
                metadata={"discovery_mode": "public_page_link", "media_extracted": "false"},
            ))
            if len(found) >= limit:
                break
        return found

    def close(self) -> None:
        return None
