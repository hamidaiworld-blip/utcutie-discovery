# Editorial rights review (discovery only)

Run `python editorial_adapters.py --input editorial_input.json`, then `python rights_review.py --candidates editorial_candidates.json --approvals rights_approvals.json`. These scripts do not fetch pages, download videos, change `daily_queue.json`, or publish.

Each candidate has `rights_status`:
- `verified`: one exact article/source URL approval matches the identified creator URL, with documented rightsholder, attribution, an allowed rights basis, evidence, and explicit Telegram republication permission. **Still not publishing-ready:** media, audio, license scope, duration, quality and dedup checks remain necessary.
- `pending`: creator identified but no adequate matching permission.
- `excluded`: unidentified ownership, unsuitable topic, restricted or paid source; an approval cannot automatically resurrect an excluded candidate.

The Dodo and SomePets supply manually collected or otherwise authorized metadata leads only. Never infer rights from public playback, embedding, attribution, downloads, or a user-provided verified flag. Shutterstock and National Geographic remain reference-only. The approval registry is not a general domain allowlist; approval must be for the exact work and intended use. Keep permission evidence securely, and do not commit private correspondence or personal information to a public repository.

`editorial_reviewed.json` is a separate review artifact, not a queue. A future explicit promotion step must independently verify media and rights before constructing any queue item. Existing publisher is unchanged.
