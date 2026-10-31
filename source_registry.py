#!/usr/bin/env python3
"""Validate and report on the controlled source registry; performs no network or publishing actions."""
import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_REVIEW = {"proposed", "in_review", "approved", "rejected", "suspended"}
ALLOWED_PERMISSION = {"unknown", "approved", "prohibited"}
ALLOWED_DELIVERY = {"none", "direct_file", "official_api"}
ALLOWED_RIGHTS = {"", "cc0", "public_domain", "cc_by_4.0", "cc_by_sa_4.0", "written_permission"}
VALID_RIGHTS_EVIDENCE = {"cc0", "public_domain", "cc_by_4.0", "cc_by_sa_4.0", "written_permission"}


def validate_registry(registry):
    errors = []
    if not isinstance(registry, dict) or registry.get("schema_version") != 1:
        return ["Registry must be an object with schema_version=1."]
    defaults = registry.get("defaults", {})
    if any(defaults.get(k) is not False for k in (
        "automated_discovery_enabled", "media_download_enabled", "auto_publish_enabled"
    )):
        errors.append("Global defaults must keep discovery, downloading, and auto-publishing false.")
    sources = registry.get("sources")
    if not isinstance(sources, list):
        return errors + ["sources must be an array."]
    seen_ids, seen_urls = set(), set()
    for i, s in enumerate(sources):
        prefix = f"sources[{i}]"
        if not isinstance(s, dict):
            errors.append(f"{prefix} must be an object.")
            continue
        sid, url = s.get("source_id"), s.get("url")
        if not isinstance(sid, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", sid):
            errors.append(f"{prefix}.source_id must be a unique lowercase slug.")
        elif sid in seen_ids:
            errors.append(f"Duplicate source_id: {sid}")
        else:
            seen_ids.add(sid)
        parsed = urlparse(url or "")
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            errors.append(f"{prefix}.url must be a public HTTPS URL without embedded credentials.")
        elif url in seen_urls:
            errors.append(f"Duplicate source URL: {url}")
        else:
            seen_urls.add(url)
        if (parsed.hostname or "").lower().removeprefix("www.") != str(s.get("domain", "")).lower().removeprefix("www."):
            errors.append(f"{prefix}.domain must match the URL hostname.")
        if s.get("review_status") not in ALLOWED_REVIEW:
            errors.append(f"{prefix}.review_status is invalid.")
        for key in ("automated_access_permission", "terms_review", "robots_review",
                    "media_download_permission", "redistribution_permission"):
            if s.get(key) not in ALLOWED_PERMISSION:
                errors.append(f"{prefix}.{key} must be unknown, approved, or prohibited.")
        if s.get("media_delivery_method") not in ALLOWED_DELIVERY:
            errors.append(f"{prefix}.media_delivery_method is invalid.")
        if s.get("rights_evidence_type", "") not in ALLOWED_RIGHTS:
            errors.append(f"{prefix}.rights_evidence_type is invalid.")
        if s.get("drm_or_access_control_bypass") is not False:
            errors.append(f"{prefix}: bypassing DRM or access controls is never permitted.")
        if s.get("automation_status") != "disabled":
            errors.append(f"{prefix}: automation_status must remain disabled.")
        if s.get("review_status") == "approved":
            required = ("reviewed_by", "reviewed_at", "terms_url", "evidence_url")
            if any(not s.get(k) for k in required):
                errors.append(f"{prefix}: approved entries require reviewer, timestamp, terms URL, and evidence URL.")
            if any(s.get(k) != "approved" for k in (
                "automated_access_permission", "terms_review", "robots_review"
            )):
                errors.append(f"{prefix}: approved source access requires documented approval for access, terms, and robots.")
            if s.get("media_download_permission") != "approved" or s.get("media_delivery_method") not in {"direct_file", "official_api"}:
                errors.append(f"{prefix}: approved downloading requires explicit permission and an official direct-file/API route.")
            if s.get("redistribution_permission") != "approved":
                errors.append(f"{prefix}: source approval requires explicit redistribution permission.")
            if s.get("rights_evidence_type") not in VALID_RIGHTS_EVIDENCE or not s.get("rights_holder"):
                errors.append(f"{prefix}: approved redistribution requires a recognized rights basis and named rights holder.")
            if s.get("telegram_public_channel_republication") is not True or s.get("zero_cost") is not True:
                errors.append(f"{prefix}: approval must explicitly cover public Telegram reposting and zero-cost use.")
            if s.get("attribution_required") is None:
                errors.append(f"{prefix}: attribution requirement must be explicitly true or false.")
            if s.get("attribution_required") is True and not s.get("required_attribution"):
                errors.append(f"{prefix}: required attribution text is missing.")
            try:
                datetime.fromisoformat(s["reviewed_at"].replace("Z", "+00:00"))
            except Exception:
                errors.append(f"{prefix}.reviewed_at must be ISO-8601.")
    return errors


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=Path("source_registry.json"))
    p.add_argument("--report", type=Path, default=Path("source_registry_report.json"))
    args = p.parse_args()
    registry = json.loads(args.input.read_text(encoding="utf-8"))
    errors = validate_registry(registry)
    report = {
        "registry_file": str(args.input),
        "schema_version": registry.get("schema_version") if isinstance(registry, dict) else None,
        "source_count": len(registry.get("sources", [])) if isinstance(registry, dict) else 0,
        "errors": errors, "valid": not errors,
        "automation_enabled": False, "downloads_enabled": False, "publishing_enabled": False,
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if not errors else 1)


if __name__ == "__main__":
    main()
