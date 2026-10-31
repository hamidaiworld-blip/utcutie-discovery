#!/usr/bin/env python3
"""Offline, fail-closed qualification of potential video sources.

No network access, downloads, rights-allowlist edits, queue writes, or publishing.
"""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

APPROVED_EVIDENCE_TYPES = {"cc0", "public_domain", "cc_by_4.0", "cc_by_sa_4.0", "written_permission"}
PROTECTED_OUTPUTS = {"daily_queue.json", "history.json", "rights_approvals.json"}


def _permission(source, key):
    value = source.get(key)
    if not isinstance(value, dict):
        return "unknown", None
    status = str(value.get("status", "unknown")).strip().lower()
    evidence = value.get("evidence_url") or value.get("evidence_reference")
    if status == "approved" and not (isinstance(evidence, str) and evidence.strip()):
        return "unknown", None
    if status not in {"approved", "prohibited", "unknown"}:
        return "unknown", None
    return status, evidence.strip() if isinstance(evidence, str) and evidence.strip() else None


def _parsed_url(url):
    try:
        parsed = urlparse(str(url))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username or parsed.password:
            return None
        return parsed
    except ValueError:
        return None


def qualify_source(source):
    if not isinstance(source, dict):
        raise ValueError("Each source entry must be a JSON object.")
    name = str(source.get("name") or "Unnamed source").strip()
    url = str(source.get("url") or "").strip()
    parsed = _parsed_url(url)
    host = (parsed.hostname or "").lower().removeprefix("www.") if parsed else ""
    reasons = []
    if not host:
        reasons.append("A valid public HTTP(S) source URL is required.")

    access, access_evidence = _permission(source, "automated_access_permission")
    terms, terms_evidence = _permission(source, "terms_review")
    robots, robots_evidence = _permission(source, "robots_review")
    download, download_evidence = _permission(source, "media_download_permission")
    redistribution, rights_evidence = _permission(source, "redistribution_permission")

    prohibitions = [label for label, status in (
        ("automated access", access), ("terms of service", terms),
        ("robots policy", robots), ("media downloading", download),
        ("redistribution", redistribution),
    ) if status == "prohibited"]
    if prohibitions:
        reasons.append("Explicitly prohibited: " + ", ".join(prohibitions) + ".")

    discovery_ok = bool(host and access == "approved" and access_evidence
                        and terms == "approved" and terms_evidence
                        and robots == "approved" and robots_evidence)
    if not discovery_ok and not prohibitions:
        reasons.append("Automated discovery requires documented approval for access, terms review, and robots review.")

    delivery = str(source.get("media_delivery_method") or "").strip().lower()
    download_ok = bool(discovery_ok and download == "approved" and download_evidence
                       and delivery in {"direct_file", "official_api"}
                       and source.get("drm_or_access_control_bypass") is False)
    if discovery_ok and not download_ok and not prohibitions:
        reasons.append("Downloading requires documented permission, an official direct-file/API route, and confirmation that no access-control or DRM bypass is involved.")

    rights_type = str(source.get("rights_evidence_type") or "").strip().lower()
    rights_holder = str(source.get("rights_holder") or "").strip()
    telegram_scope = source.get("telegram_public_channel_republication") is True
    zero_cost = source.get("zero_cost") is True
    attribution_required = source.get("attribution_required") is True
    attribution_text = str(source.get("required_attribution") or "").strip()
    rights_ok = bool(download_ok and redistribution == "approved" and rights_evidence
                     and rights_type in APPROVED_EVIDENCE_TYPES and rights_holder
                     and telegram_scope and zero_cost
                     and (not attribution_required or attribution_text))
    if download_ok and not rights_ok and not prohibitions:
        reasons.append("Redistribution requires documented rights-holder evidence covering public Telegram-channel reposting, zero-cost use, and required attribution.")

    if prohibitions:
        status = "blocked"
    elif rights_ok:
        status = "approved_for_republication_source_level"
        reasons.append("Source-level checks passed. Each individual video still requires an exact-media entry in rights_approvals.json before queueing.")
    elif download_ok:
        status = "approved_for_download_only"
    elif discovery_ok:
        status = "approved_for_discovery_only"
    else:
        status = "manual_review_required"

    path = parsed.path.strip("/") if parsed else ""
    identity = host + (("-" + path) if path else "")
    source_id = re.sub(r"[^a-z0-9]+", "-", identity.lower()).strip("-") or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return {
        "source_id": source_id,
        "name": name, "url": url, "domain": host or None,
        "qualification_status": status,
        "discovery_eligible": discovery_ok,
        "download_eligible": download_ok,
        "source_level_republication_eligible": rights_ok,
        "candidate_level_rights_check_still_required": True,
        "evidence": {
            "automated_access": access_evidence, "terms_review": terms_evidence,
            "robots_review": robots_evidence, "media_download": download_evidence,
            "redistribution": rights_evidence, "rights_evidence_type": rights_type or None,
            "rights_holder": rights_holder or None,
        },
        "reasons": reasons,
    }


def build_report(registry):
    if not isinstance(registry, dict) or not isinstance(registry.get("sources"), list):
        raise ValueError("Input must be an object containing a 'sources' array.")
    results = [qualify_source(item) for item in registry["sources"]]
    counts = {}
    for item in results:
        key = item["qualification_status"]
        counts[key] = counts.get(key, 0) + 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Source qualification only; not a discovery feed or publishing queue.",
        "automation_enabled": False, "downloads_enabled": False, "publishing_enabled": False,
        "candidate_level_rights_check_required": True,
        "source_count": len(results), "status_counts": counts, "sources": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("source_leads.json"))
    parser.add_argument("--output", type=Path, default=Path("source_qualification_report.json"))
    args = parser.parse_args()
    if args.output.name in PROTECTED_OUTPUTS:
        parser.error(f"Refusing to overwrite protected file: {args.output.name}")
    if args.input.resolve() == args.output.resolve():
        parser.error("Input and output paths must be different.")
    registry = json.loads(args.input.read_text(encoding="utf-8"))
    report = build_report(registry)
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(args.output)
    print(f"Qualified {report['source_count']} sources; report written to {args.output}. No network, downloads, queue changes, or publishing performed.")


if __name__ == "__main__":
    main()
