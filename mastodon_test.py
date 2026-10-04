import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests


INSTANCES = [
    "mastodon.social",
    "mastodon.online",
    "mastodon.world",
]

HASHTAGS = [
    "cats",
    "cat",
    "dogs",
    "dog",
    "pets",
    "animals",
    "aww",
    "cuteanimals",
    "funnyanimals",
    "petsofthefediverse",
]

MAX_PER_HASHTAG = 40

MIN_DURATION = 15
MAX_DURATION = 180
MAX_FILE_SIZE = 48 * 1024 * 1024

MAX_SELECTED = 20

HISTORY_FILE = Path("history.json")
CANDIDATES_FILE = Path("mastodon_candidates.json")
VALIDATED_FILE = Path("validated_candidates.json")
SELECTED_FILE = Path("selected_candidates.json")

DOWNLOAD_TIMEOUT = 45

session = requests.Session()

session.headers.update({
    "User-Agent": "UTCutie/1.0 public video discovery"
})


# ---------------------------------------------------------
# BASIC HELPERS
# ---------------------------------------------------------

def safe_dict(value):
    if isinstance(value, dict):
        return value
    return {}


def clean_html(text):
    if not text:
        return ""

    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def load_json(path, default):
    if not path.exists():
        return default

    try:
        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:
            return json.load(f)

    except Exception:
        return default


def save_json(path, data):
    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# ---------------------------------------------------------
# MASTODON DISCOVERY
# ---------------------------------------------------------

def get_statuses(instance, hashtag):
    url = (
        f"https://{instance}/api/v1/timelines/tag/"
        f"{hashtag}"
    )

    params = {
        "limit": MAX_PER_HASHTAG,
        "only_media": "true",
        "local": "false",
    }

    try:
        response = session.get(
            url,
            params=params,
            timeout=20
        )

        print(
            f"{instance} #{hashtag}: "
            f"HTTP {response.status_code}"
        )

        if response.status_code != 200:
            return []

        data = response.json()

        if not isinstance(data, list):
            return []

        return data

    except Exception as exc:
        print(
            f"{instance} #{hashtag}: "
            f"ERROR {exc}"
        )
        return []


def is_video_attachment(attachment):
    attachment = safe_dict(attachment)

    media_type = attachment.get(
        "type",
        ""
    )

    if media_type == "video":
        return True

    meta = safe_dict(
        attachment.get("meta")
    )

    original = safe_dict(
        meta.get("original")
    )

    mime = original.get(
        "mime",
        ""
    )

    return (
        isinstance(mime, str)
        and mime.startswith("video/")
    )


def extract_video_url(attachment):
    attachment = safe_dict(attachment)

    return (
        attachment.get("url")
        or attachment.get("remote_url")
    )


def duration_from_attachment(attachment):
    attachment = safe_dict(attachment)

    meta = safe_dict(
        attachment.get("meta")
    )

    original = safe_dict(
        meta.get("original")
    )

    duration = (
        original.get("duration")
        or meta.get("duration")
    )

    try:
        return float(duration)
    except (
        TypeError,
        ValueError
    ):
        return None


def build_candidate(
    instance,
    status,
    attachment
):
    status = safe_dict(status)
    attachment = safe_dict(attachment)

    account = safe_dict(
        status.get("account")
    )

    caption = clean_html(
        status.get(
            "content",
            ""
        )
    )

    return {
        "source": "mastodon",
        "instance": instance,
        "status_id": status.get("id"),
        "status_url": (
            status.get("url")
            or status.get("uri")
        ),
        "author": (
            account.get("display_name")
            or account.get("username")
            or ""
        ),
        "created_at": status.get(
            "created_at"
        ),
        "caption": caption,
        "reblogs": status.get(
            "reblogs_count",
            0
        ),
        "favourites": status.get(
            "favourites_count",
            0
        ),
        "replies": status.get(
            "replies_count",
            0
        ),
        "video_url": extract_video_url(
            attachment
        ),
        "declared_duration": (
            duration_from_attachment(
                attachment
            )
        ),
        "mime": (
            safe_dict(
                safe_dict(
                    attachment.get("meta")
                ).get("original")
            ).get("mime")
        ),
    }


def discover():
    candidates = []
    seen_urls = set()

    total_statuses = 0

    for instance in INSTANCES:

        for hashtag in HASHTAGS:

            statuses = get_statuses(
                instance,
                hashtag
            )

            total_statuses += len(statuses)

            for status in statuses:

                attachments = status.get(
                    "media_attachments",
                    []
                )

                if not isinstance(
                    attachments,
                   
