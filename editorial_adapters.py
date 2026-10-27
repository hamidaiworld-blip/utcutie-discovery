#!/usr/bin/env python3
"""Discovery-only editorial adapters. No HTTP, scraping, downloads or publishing.

Input: JSON array of manually collected or otherwise authorized metadata records.
Run: python editorial_adapters.py --input editorial_input.json
Output: editorial_candidates.json; never daily_queue.json.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

SOURCES = {
    "the_dodo": ("thedodo.com",),
    "somepets": ("somepets.com",),
}
ANIMALS = re.compile(r"\b(cat|cats|kitten|dog|dogs|puppy|puppies|pet|pets|animal|animals|rabbit|bunny|bird|parrot|duck|goat|horse|pig|hamster|otter|fox|hedgehog|rescue)\b", re.I)
POSITIVE = re.compile(r"\b(cute|funny|playful|adorable|sweet|wholesome|silly|heartwarming|friendship|cuddle|surprise|happy|hilarious|love)\b", re.I)
EXCLUDE = re.compile(r"\b(abuse|death|dying|injury|injured|graphic|cruelty|donate|fundraiser|shop|sponsored|advertisement|product review)\b", re.I)
TRACKING = {"fbclid", "gclid", "mc_cid", "mc_eid"}

def canonical(value):
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        p = urlsplit(value.strip())
        host = (p.hostname or "").lower().removeprefix("www.")
        if p.scheme not in ("https", "http") or not host or p.username or p.password:
            return ""
        port = f":{p.port}" if p.port and p.port not in (80, 443) else ""
        query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                                 if not k.lower().startswith("utm_") and k.lower() not in TRACKING))
        return urlunsplit(("https", host + port, p.path.rstrip("/") or "/", query, ""))
    except ValueError:
        return ""

def source_for(url):
    host = urlsplit(url).hostname or ""
    for name, domains in SOURCES.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return name
    return None

def history_urls(obj):
    """Conservatively find URL strings anywhere in existing history/queue shapes."""
    found = set()
    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and node.startswith(("https://", "http://")):
            url = canonical(node)
            if url:
                found.add(url)
    walk(obj)
    return found

def relevance(title, description):
    text = " ".join((title, description))
    if EXCLUDE.search(text):
        return 0, "excluded_topic"
    if not ANIMALS.search(text):
        return 0, "animal_evidence_missing"
    score = 50 + (25 if POSITIVE.search(text) else 0) + (10 if len(description.strip()) >= 40 else 0)
    return score, "editorial_precheck_only"

def build(records, history):
    seen = history_urls(history)
    out = []
    for record in records:
        if not isinstance(record, dict):
            continue
        url = canonical(record.get("article_url") or record.get("video_url"))
        source = source_for(url)
        if not source:
            continue
        embeds = sorted(set(filter(None, (canonical(u) for u in record.get("embedded_source_links", []) if isinstance(u, str)))))
        original = canonical(record.get("original_creator_url"))
        identity = {url, *embeds}
        if original:
            identity.add(original)
        if seen.intersection(identity):
            continue
        seen.update(identity)
        title = str(record.get("title") or "").strip()
        description = str(record.get("description") or "").strip()
        score, reason = relevance(title, description)
        published = record.get("publication_date")
        if published:
            try:
                datetime.fromisoformat(str(published).replace("Z", "+00:00"))
            except ValueError:
                published = None
        out.append({
            "id": hashlib.sha256(url.encode()).hexdigest()[:20],
            "source": source,
            "article_url": url,
            "video_url": canonical(record.get("video_url")),
            "title": title,
            "description": description,
            "publication_date": published,
            "embedded_source_links": embeds,
            "original_creator_name": record.get("original_creator_name") or None,
            "original_creator_url": original or None,
            "relevance_score": score,
            "relevance_status": reason,
            "visual_quality_status": "unverified",
            "duration_status": "unverified",
            "rights_status": "pending_independent_verification",
            "rights_evidence": None,
            "review_status": "rejected" if score == 0 else "manual_review_required",
            "auto_publish_allowed": False,
            "download_allowed": False,
            "discovery_only": True,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        })
    return out

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path, help="Authorized/manual metadata JSON array")
    p.add_argument("--history", type=Path, default=Path("history.json"))
    p.add_argument("--output", type=Path, default=Path("editorial_candidates.json"))
    args = p.parse_args()
    if args.output.name in {"daily_queue.json", "history.json", "rights_approvals.json"}:
        p.error("Editorial adapters cannot overwrite publishing, history or rights files")
    records = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        p.error("Input must be a JSON array")
    history = json.loads(args.history.read_text(encoding="utf-8")) if args.history.exists() else {}
    result = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "sources": list(SOURCES), "discovery_only": True,
              "automatic_queue_integration": False, "candidate_count": 0, "candidates": []}
    result["candidates"] = build(records, history)
    result["candidate_count"] = len(result["candidates"])
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Editorial leads: {result['candidate_count']}; queued/published/downloaded: 0")

if __name__ == "__main__":
    main()
