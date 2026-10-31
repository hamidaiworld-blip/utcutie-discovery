# Controlled source registry and review process

## Purpose

This registry is the single intake record for potential sources. A source record is a lead, not permission to scrape, download, or republish. New sources are proposed through a GitHub pull request; they do not enter the discovery feed by being added to this file.

## Intake and review states

1. **proposed** — URL and purpose recorded; all permissions default to unknown; automation, downloads, and publishing remain disabled.
2. **in_review** — reviewer gathers evidence for the exact site, terms, robots/access policy, delivery method, rights holder, licence/permission, costs, attribution, and public Telegram redistribution scope.
3. **approved** — only after the required evidence is documented and source_registry.py passes. Approval is source-level permission to use a defined access route; it is not blanket clearance for every clip.
4. **rejected** — prohibited, incompatible, non-zero-cost, unclear, or impractical.
5. **suspended** — previously approved source paused after a terms change, rights complaint, access change, or failed review.

## Hard gates

- Unknown is not approval. Missing evidence keeps a source out of automated discovery and downloading.
- No login-wall, paywall, DRM, watermark, rate-limit, or other access-control circumvention.
- Automated discovery requires documented approval for access, terms, and robots policy.
- Downloading requires explicit permission and an official direct-file or official API route. A page URL, embed URL, browser playback, or third-party downloader is not sufficient.
- Reposting requires rights-holder evidence explicitly covering redistribution to a public Telegram channel, the intended use, and zero-cost constraints. Attribution must be recorded when required.
- Each individual video still requires an exact-media rights record in rights_approvals.json before it can enter a publishing queue. A source-level approval never substitutes for clip-level approval.
- A link/share/embed route may be used only where the publisher's own supported share/embed function and terms permit it; it does not authorize downloading or re-uploading.

## Pull-request checklist for every new source

- [ ] Add one unique source_id and canonical HTTPS URL.
- [ ] Identify the publisher, content type, original creator/rights holder model, and official terms/policy URLs.
- [ ] Record evidence URLs and review notes for automated access, terms, robots, download permission, delivery method, and redistribution rights.
- [ ] Explicitly document whether public Telegram reposting is allowed, whether zero-cost use is allowed, and any attribution text.
- [ ] Keep every permission unknown until evidence is checked. Do not infer permission from public visibility.
- [ ] Run python source_registry.py and python -m unittest discover -s tests.
- [ ] Request a human review of the evidence and diff. Merge only after approval.
- [ ] If approved, separately update the exact-video allowlist only for individual clips whose rights are documented.

## Qualification report

source_qualification.py --input source_registry.json produces a qualification report using the existing fail-closed checks. source_registry.py validates registry structure and approval completeness. Both are read-only with respect to discovery, queue, history, and Telegram. The report is an audit artifact, not an activation switch.

## Current status

The five initial website leads are registered as proposed. None is approved for automated access, downloading, or public Telegram reposting. The existing publisher remains independent and must not be enabled as a consequence of a registry change.
