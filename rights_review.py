#!/usr/bin/env python3
"""Review discovery candidates against an exact-source, evidence-backed allowlist.

Never downloads media, edits daily_queue.json, or publishes anything.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

BASES = {"cc0", "public domain", "cc by 4.0", "cc by-sa 4.0", "written permission"}

def valid_url(value):
    if not isinstance(value, str):
        return False
    p = urlsplit(value.strip())
    return p.scheme == "https" and bool(p.hostname) and not p.username and not p.password

def evidence(approval):
    if not isinstance(approval, dict) or approval.get("reuse_allowed") is not True:
        return False
    basis = str(approval.get("rights_basis") or "").strip().casefold()
    if basis not in BASES or not valid_url(approval.get("source_url")):
        return False
    if not str(approval.get("rightsholder") or "").strip() or not str(approval.get("attribution") or "").strip():
        return False
    if basis == "written permission":
        return bool(str(approval.get("permission_reference") or "").strip()) and approval.get("telegram_republication_allowed") is True
    return valid_url(approval.get("license_url")) and approval.get("telegram_republication_allowed") is True

def review(candidates, approvals):
    by_url = {}
    for a in approvals:
        if evidence(a):
            by_url.setdefault(a["source_url"], []).append(a)
    result = []
    for candidate in candidates:
        c = dict(candidate)
        c["rights_status"] = "excluded" if c.get("rights_status") == "excluded" else "pending"
        c["rights_evidence"] = None
        c["auto_publish_allowed"] = False
        c["download_allowed"] = False
        c["discovery_only"] = True
        original = c.get("original_creator_url")
        source = c.get("article_url")
        matches = by_url.get(source, [])
        if c["rights_status"] != "excluded" and original and len(matches) == 1:
            a = matches[0]
            if a.get("rightsholder_url") == original and valid_url(original):
                c["rights_status"] = "verified"
                c["rights_evidence"] = {k: a.get(k) for k in (
                    "source_url", "rightsholder", "rightsholder_url", "rights_basis",
                    "license_url", "permission_reference", "attribution",
                    "telegram_republication_allowed")}
                c["review_status"] = "rights_verified_media_checks_pending"
        result.append(c)
    return result

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--candidates", type=Path, default=Path("editorial_candidates.json"))
    p.add_argument("--approvals", type=Path, default=Path("rights_approvals.json"))
    p.add_argument("--output", type=Path, default=Path("editorial_reviewed.json"))
    args = p.parse_args()
    protected = {"daily_queue.json", "history.json", "rights_approvals.json"}
    if args.output.name in protected or args.output.resolve() in {args.candidates.resolve(), args.approvals.resolve()}:
        p.error("Cannot overwrite queue, history, approvals or inputs")
    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    approvals = json.loads(args.approvals.read_text(encoding="utf-8"))
    if not isinstance(candidates, dict) or not isinstance(candidates.get("candidates"), list):
        p.error("Expected discovery payload with candidates array")
    if not isinstance(approvals, dict) or not isinstance(approvals.get("approvals"), list):
        p.error("Expected approvals payload with approvals array")
    reviewed = review(candidates["candidates"], approvals["approvals"])
    payload = {"discovery_only": True, "queue_integration": False, "candidates": reviewed,
               "counts": {s: sum(c["rights_status"] == s for c in reviewed) for s in ("verified", "pending", "excluded")}}
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(payload["counts"], "No downloads, queue edits, or uploads.")

if __name__ == "__main__":
    main()
