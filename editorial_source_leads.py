#!/usr/bin/env python3
"""Collect public animal-video discovery leads without downloading or republishing media.

These sites are editorial/reference sources only. A lead is NOT eligible for the
Telegram queue unless separate, documented permission or a suitable reuse license
is verified. This script stores page titles and links only; it never fetches video files.
"""

import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

import requests

OUTPUT = Path("source_leads.json")
TIMEOUT = 12
MAX_LEADS_PER_SITE = 20
HEADERS = {"User-Agent": "UTCutieDiscovery/1.0 (+public-page metadata; no media downloads)"}
SOURCES = [
    {"name": "Shutterstock Cute Animals", "url": "https://www.shutterstock.com/video/search/cute-animals", "domain": "shutterstock.com", "rights_note": "Stock footage; requires an applicable paid license. Comp/watermarked previews are not for public distribution."},
    {"name": "The Dodo", "url": "https://www.thedodo.com/", "domain": "thedodo.com", "rights_note": "Publisher-produced/editorial videos; permission or a license is required for re-uploading."},
    {"name": "National Geographic Kids Videos", "url": "https://kids.nationalgeographic.com/videos", "domain": "kids.nationalgeographic.com", "rights_note": "Publisher-owned/licensed videos; do not re-upload without explicit permission."},
    {"name": "National Geographic Kids Amazing Animals", "url": "https://kids.nationalgeographic.com/videos/topic/amazing-animals", "domain": "kids.nationalgeographic.com", "rights_note": "Publisher-owned/licensed videos; do not re-upload without explicit permission."},
    {"name": "SomePets Cute Videos", "url": "https://www.somepets.com/category/cute/cute-videos/", "domain": "somepets.com", "rights_note": "Ownership and reuse terms not verified; do not re-upload until rights are confirmed."},
]

ANIMAL_OR_VIDEO = re.compile(r"\b(video|watch|animal|animals|pet|pets|cute|cat|cats|kitten|dog|dogs|puppy|puppies|wildlife|bird|birds|puppies|amazing|funny|adorable|squirrel|raccoon|horse|farm|wild|rescue|puppet|otter|owl|elephant|fox|bear|penguin|monkey|turtle|fish)\b", re.I)
EXCLUDE = re.compile(r"\b(shop|store|subscribe|newsletter|advertis|privacy|terms|cookie|login|sign.?in|account|donate|merch|product|sweepstakes|contest|career|job)\b", re.I)
GENERIC_NAV = {"pets", "dogs", "cats", "travel", "wellness", "dog wellness", "cat wellness", "adoption", "wildlife", "environment", "video", "videos", "shop", "family", "kids & pets", "parenting", "celebration", "animal encounters", "see all", "see more", "watch now", "newsletter"}

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts = []
        self.in_title = False
        self.anchors = []
        self.current = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag == "a" and attrs.get("href"):
            self.current = {"href": attrs["href"], "text": [], "title": attrs.get("title", "")}
    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "a" and self.current is not None:
            self.anchors.append(self.current)
            self.current = None
    def handle_data(self, data):
        text = " ".join(data.split())
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
        if self.current is not None:
            self.current["text"].append(text)

def host_allowed(url, domain):
    host = (urlparse(url).hostname or "").lower()
    return host == domain or host.endswith("." + domain)

def main():
    session = requests.Session()
    session.headers.update(HEADERS)
    now = datetime.now(timezone.utc).isoformat()
    output = {
        "generated_at": now,
        "purpose": "reference-only source leads; not authorized for automatic republication",
        "auto_publish_enabled": False,
        "sources": [],
        "leads": [],
    }
    seen = set()
    for source in SOURCES:
        result = {"name": source["name"], "url": source["url"], "status": "not_checked", "http_status": None, "lead_count": 0, "rights_note": source["rights_note"]}
        try:
            response = session.get(source["url"], timeout=TIMEOUT, allow_redirects=True)
            result["http_status"] = response.status_code
            if not response.ok:
                result["status"] = "unavailable_or_blocked"
                result["detail"] = f"HTTP {response.status_code}; no media downloaded"
                output["sources"].append(result)
                continue
            parser = PageParser()
            parser.feed(response.text[:2_000_000])
            result["page_title"] = " ".join(parser.title_parts).strip()[:300]
            if not result["page_title"] and not parser.anchors:
                result["status"] = "challenge_or_empty_page"
                result["detail"] = "HTTP response contained no usable page metadata; no media downloaded"
                output["sources"].append(result)
                continue
            result["status"] = "page_metadata_read"
            count = 0
            base = response.url
            ranked_anchors = sorted(
                parser.anchors,
                key=lambda a: (
                    0 if re.search(r"/videos?/|/stories/|/video/|/watch/", a.get("href", ""), re.I) else 1,
                    -len(" ".join(a.get("text", []))),
                ),
            )
            for anchor in ranked_anchors:
                raw_url = urljoin(base, anchor["href"])
                raw_url, _ = urldefrag(raw_url)
                if urlparse(raw_url).scheme != "https" or not host_allowed(raw_url, source["domain"]):
                    continue
                text = " ".join(anchor["text"]).strip()
                title = (anchor.get("title") or text).strip()
                normalized_title = re.sub(r"\s+", " ", title).strip().casefold()
                if normalized_title in GENERIC_NAV:
                    continue
                if any(part in urlparse(raw_url).path.casefold() for part in ("/topics/", "/category/", "/paw-of-approval/", "/dodowell/", "/shop/", "/products/", "/product/")):
                    continue
                if len(title) < 8 or EXCLUDE.search(title) or not ANIMAL_OR_VIDEO.search(title + " " + raw_url):
                    continue
                key = raw_url.rstrip("/")
                if key in seen:
                    continue
                seen.add(key)
                output["leads"].append({
                    "source": source["name"],
                    "discovery_page": source["url"],
                    "title": title[:300],
                    "url": raw_url,
                    "observed_at": now,
                    "lead_type": "video_page" if re.search(r"/videos?/|/video/|/watch/", urlparse(raw_url).path, re.I) else "story_or_reference_page",
                    "rights_status": "permission_required_or_unverified",
                    "eligible_for_auto_publish": False,
                    "note": source["rights_note"],
                })
                count += 1
                if count >= MAX_LEADS_PER_SITE:
                    break
            result["lead_count"] = count
        except Exception as exc:
            result["status"] = "fetch_error"
            result["detail"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        output["sources"].append(result)
        print(f"{source['name']}: {result['status']}; leads={result['lead_count']}")
    output["lead_count"] = len(output["leads"])
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Reference-only leads saved: {len(output['leads'])} -> {OUTPUT}")
    print("Safety rule: no lead from these websites is copied into the Telegram queue.")

if __name__ == "__main__":
    main()
