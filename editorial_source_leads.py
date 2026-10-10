#!/usr/bin/env python3
"""Maintain a reference-only registry of animal-video inspiration sites.

This script deliberately performs no HTTP requests, crawling, scraping, media
downloads, or uploads. These sites can inspire search terms and manual research,
but their hosted videos are not eligible for automatic Telegram publication
unless explicit written permission or a license authorizes that exact use.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

OUTPUT = Path("source_leads.json")

SOURCES = [
    {
        "name": "Shutterstock Cute Animals",
        "url": "https://www.shutterstock.com/video/search/cute-animals",
        "use": "Manual inspiration / licensed-stock research only",
        "automated_access": False,
        "media_download_allowed": False,
        "auto_publish_allowed": False,
        "rights_status": "license_required",
        "reason": (
            "Stock footage requires a suitable license. A standard video license "
            "does not authorize redistributing the raw clip as a standalone video "
            "post; comp/watermarked previews are not for public distribution."
        ),
    },
    {
        "name": "The Dodo",
        "url": "https://www.thedodo.com/",
        "use": "Manual inspiration and link-sharing only",
        "automated_access": False,
        "media_download_allowed": False,
        "auto_publish_allowed": False,
        "rights_status": "permission_required",
        "reason": (
            "Vox Media's terms prohibit automated scraping and copying/reposting "
            "content without permission. Its licensing guidance allows linking and "
            "integrated share/embed tools where available, not raw-video reuploads."
        ),
    },
    {
        "name": "National Geographic Kids Videos",
        "url": "https://kids.nationalgeographic.com/videos",
        "use": "Manual inspiration and link-sharing only",
        "automated_access": False,
        "media_download_allowed": False,
        "auto_publish_allowed": False,
        "rights_status": "written_permission_required",
        "reason": (
            "National Geographic content terms restrict automated scraping and "
            "reposting/redistribution without specific written authorization."
        ),
    },
    {
        "name": "National Geographic Kids Amazing Animals",
        "url": "https://kids.nationalgeographic.com/videos/topic/amazing-animals",
        "use": "Manual inspiration and link-sharing only",
        "automated_access": False,
        "media_download_allowed": False,
        "auto_publish_allowed": False,
        "rights_status": "written_permission_required",
        "reason": (
            "National Geographic content terms restrict automated scraping and "
            "reposting/redistribution without specific written authorization."
        ),
    },
    {
        "name": "SomePets Cute Videos",
        "url": "https://www.somepets.com/category/cute/cute-videos/",
        "use": "Manual inspiration / original-source tracing only",
        "automated_access": False,
        "media_download_allowed": False,
        "auto_publish_allowed": False,
        "rights_status": "ownership_unverified",
        "reason": (
            "The site states it does not own exclusive rights to all published "
            "videos and includes material with unknown authors. Find the original "
            "creator and verify permission before considering reuse."
        ),
    },
]

def main():
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Reference registry only; not an ingest or publishing feed.",
        "automated_fetching_enabled": False,
        "media_download_enabled": False,
        "auto_publish_enabled": False,
        "sources": SOURCES,
        "leads": [],
        "lead_count": 0,
        "safety_rule": (
            "None of these websites may feed the Telegram queue directly. "
            "Only independently verified media with documented reuse rights "
            "can enter the publishing queue."
        ),
    }
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Reference registry saved: {OUTPUT}")
    print(f"Sources catalogued: {len(SOURCES)}")
    print("Network requests made: 0")
    print("Media downloaded or published: 0")

if __name__ == "__main__":
    main()
