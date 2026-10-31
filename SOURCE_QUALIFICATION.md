# Source qualification component

## Purpose
The source qualification module is an offline, fail-closed admission layer. It evaluates three separate permission gates:

1. Automated discovery: documented automated-access permission, terms review, and robots review.
2. Media download: discovery approval plus documented download permission and an official direct-file or API route. Browser extraction, DRM circumvention, and access-control bypass do not qualify.
3. Source-level republication: download approval plus rights-holder evidence that explicitly covers public Telegram-channel reposting, zero-cost use, and required attribution.

Missing, unsupported, or undocumented permissions are unknown, never approval.

## Evidence schema
The default input is source_leads.json. Legacy flags such as automated_access=true, media_download_allowed=true, auto_publish_allowed=true, or rights_status=approved are not accepted as proof.

Each source must provide evidence-backed fields such as:
- automated_access_permission: {status: approved, evidence_url: ...}
- terms_review: {status: approved, evidence_url: ...}
- robots_review: {status: approved, evidence_url: ...}
- media_download_permission: {status: approved, evidence_url: ...}
- media_delivery_method: direct_file or official_api
- drm_or_access_control_bypass: false
- redistribution_permission: {status: approved, evidence_reference: ...}
- rights_evidence_type: cc0, public_domain, cc_by_4.0, cc_by_sa_4.0, or written_permission
- rights_holder: identified legal rights holder
- telegram_public_channel_republication: true
- zero_cost: true
- attribution_required and required_attribution when applicable

The evidence type label does not replace reviewing the actual license or permission scope.

## Run
    python source_qualification.py

The report is written to source_qualification_report.json. The component makes no network requests and does not download files, edit rights_approvals.json, write daily_queue.json, update publication history, or publish to Telegram.

A source passing source-level checks is not blanket permission for every video on that site. Each media item must still pass the existing exact-URL rights allowlist and normal duration, file-size, visual-quality, relevance, freshness, and deduplication checks before queueing.

The GitHub Actions workflow runs tests and uploads the report as an artifact. It has read-only repository permissions and does not commit or publish.
