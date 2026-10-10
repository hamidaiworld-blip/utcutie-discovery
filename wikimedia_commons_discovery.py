#!/usr/bin/env python3
"""Discover animal videos on Wikimedia Commons with explicit reusable licenses.

This script uses the public MediaWiki API, verifies per-file license metadata,
and reuses UTCutie's existing size, duration, and visual validation. It never
publishes directly. The queue builder remains responsible for its rights gate.
"""
import html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
import mastodon_test as validation

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "UTCutieDiscovery/1.0 (animal-video curation; respectful API use)"
SEARCH_TERMS = ["cat", "dog", "kitten", "puppy", "bird", "rabbit", "pet", "animal playing"]
RESULTS_PER_TERM = 15
MAX_METADATA_BATCH = 40
MAX_DOWNLOAD_ATTEMPTS = 30
MAX_SELECTED = 20
MAX_BYTES = 48 * 1024 * 1024
OUT_CANDIDATES = Path("commons_selected_candidates.json")
OUT_APPROVALS = Path("commons_rights_approvals.json")

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})

def plain(value):
    value = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", value).strip()

def metadata_value(ext, key):
    item = ext.get(key, {}) if isinstance(ext, dict) else {}
    return plain(item.get("value", "") if isinstance(item, dict) else item)

def classify_license(short_name, license_url):
    text = plain(short_name).casefold().replace("creative commons", "cc")
    url = str(license_url or "").strip().casefold()
    if "cc0" in text and "creativecommons.org/publicdomain/zero/1.0" in url:
        return "CC0"
    if ("cc by-sa 4.0" in text or "attribution-sharealike 4.0" in text) and "creativecommons.org/licenses/by-sa/4.0" in url:
        return "CC BY-SA 4.0"
    if ("cc by 4.0" in text or "attribution 4.0" in text) and "creativecommons.org/licenses/by/4.0" in url:
        return "CC BY 4.0"
    return ""

def api_get(params):
    response = session.get(API, params={"format": "json", "formatversion": 2, **params}, timeout=25)
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    return payload

def search_titles():
    titles = []
    seen = set()
    for term in SEARCH_TERMS:
        try:
            payload = api_get({
                "action": "query", "list": "search", "srnamespace": 6,
                "srlimit": RESULTS_PER_TERM, "srsearch": f"filetype:video {term}",
            })
            for item in payload.get("query", {}).get("search", []):
                title = str(item.get("title", ""))
                if title and title not in seen:
                    seen.add(title)
                    titles.append(title)
        except Exception as exc:
            print(f"Search skipped for {term!r}: {type(exc).__name__}: {exc}")
        time.sleep(0.15)
    print(f"Commons search returned {len(titles)} unique file pages.")
    return titles

def file_metadata(titles):
    found = []
    for start in range(0, len(titles), MAX_METADATA_BATCH):
        batch = titles[start:start + MAX_METADATA_BATCH]
        try:
            payload = api_get({
                "action": "query", "prop": "imageinfo", "titles": "|".join(batch),
                "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 640,
            })
            for page in payload.get("query", {}).get("pages", []):
                info_list = page.get("imageinfo", [])
                if not info_list:
                    continue
                info = info_list[0]
                mime = str(info.get("mime", "")).casefold()
                size = int(info.get("size", 0) or 0)
                media_url = str(info.get("url", ""))
                if not mime.startswith("video/") or not media_url or size <= 0 or size > MAX_BYTES:
                    continue
                ext = info.get("extmetadata", {}) or {}
                short_name = metadata_value(ext, "LicenseShortName")
                license_url = metadata_value(ext, "LicenseUrl")
                basis = classify_license(short_name, license_url)
                if not basis:
                    continue
                author = metadata_value(ext, "Artist") or metadata_value(ext, "Credit")
                if not author:
                    continue
                title = str(page.get("title", "File: animal video")).removeprefix("File:").replace("_", " ").strip()
                description = metadata_value(ext, "ImageDescription")
                page_url = "https://commons.wikimedia.org/wiki/" + quote(str(page.get("title", "")).replace(" ", "_"), safe=":/_()'!,.-")
                found.append({
                    "title": title, "description": description, "author": author,
                    "source_url": page_url, "media_url": media_url,
                    "file_size": size, "mime": mime, "rights_basis": basis,
                    "license_url": license_url, "license_short_name": short_name,
                })
        except Exception as exc:
            print(f"Metadata batch skipped: {type(exc).__name__}: {exc}")
        time.sleep(0.15)
    print(f"Files with an allowed explicit license and attribution: {len(found)}.")
    return found

def main():
    candidates = []
    approvals = []
    titles = search_titles()
    metadata = file_metadata(titles)
    history = validation.load_history()
    published = validation.history_keys(history)
    attempts = 0

    for item in metadata:
        if attempts >= MAX_DOWNLOAD_ATTEMPTS or len(candidates) >= MAX_SELECTED:
            break
        content = (item["title"] + " " + item["description"]).strip()
        # Avoid irrelevant videos before downloading; the existing visual gate
        # still checks representative frames after download.
        if not any(term in content.casefold() for term in validation.ANIMAL_TERMS):
            continue
        gate_candidate = {"content": content, "media_url": item["media_url"], "tags": []}
        content_ok, content_score, content_reason = validation.content_gate(gate_candidate)
        if not content_ok:
            print(f"  Rejected by content gate: {content_reason}")
            continue
        source_url = item["source_url"]
        if validation.canonical_status_url(source_url) in published or source_url in published:
            continue
        caption = validation.clean_caption(item["description"] or item["title"])
        if not caption:
            caption = item["title"][:220]
        attribution = f"{item['author'][:140]} · Source: {source_url} · License: {item['rights_basis']} ({item['license_url']})"
        candidate = {
            "id": source_url, "url": source_url, "canonical_url": source_url,
            "source_url": source_url, "account": item["author"],
            "instance": "Wikimedia Commons", "created_at": datetime.now(timezone.utc).isoformat(),
            "content": content[:1200], "caption": caption[:260],
            "media_description": item["description"][:1000], "media_url": item["media_url"],
            "media_type": "video", "content_score": content_score, "age_days": 0,
            "freshness_tier": "licensed_evergreen", "rights_verified": True,
            "rights_basis": item["rights_basis"], "license_url": item["license_url"],
            "attribution": attribution, "license_short_name": item["license_short_name"],
        }
        attempts += 1
        print(f"Validating Commons video {attempts}/{MAX_DOWNLOAD_ATTEMPTS}: {item['title'][:100]}")
        result, reason = validation.download_and_validate(candidate)
        if result is None:
            print(f"  Rejected: {reason}")
            continue
        result["quality_score"] = validation.quality_score(result)
        result["selection_score"] = validation.selection_score(result)
        if result.get("sha256") and f"sha:{result['sha256']}" in published:
            print("  Rejected: previously published file hash")
            continue
        candidates.append(result)
        approvals.append({
            "source_url": source_url, "reuse_allowed": True,
            "rights_basis": item["rights_basis"], "license_url": item["license_url"],
            "attribution": attribution, "permission_reference": "",
            "verification_source": "Wikimedia Commons per-file extmetadata API",
            "verified_at": datetime.now(timezone.utc).isoformat(),
        })
        print(f"  Accepted: {result['duration']} sec, {result['file_size']} bytes, {result['width']}x{result['height']}.")

    candidates.sort(key=lambda x: (x.get("selection_score", 0), x.get("quality_score", 0)), reverse=True)
    candidates = candidates[:MAX_SELECTED]
    allowed_urls = {x["source_url"] for x in candidates}
    approvals = [x for x in approvals if x["source_url"] in allowed_urls]
    OUT_CANDIDATES.write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_APPROVALS.write_text(json.dumps({"approvals": approvals}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Commons candidates ready for queue rights gate: {len(candidates)}.")
    print("No Telegram uploads were performed by this script.")

if __name__ == "__main__":
    main()
