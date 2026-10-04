import json
import re
import requests
from datetime import datetime, timezone

INSTANCES = [
    "mastodon.social",
    "mastodon.online",
    "mstdn.social",
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

session = requests.Session()
session.headers.update({
    "User-Agent": "UTCutie/1.0 public video discovery"
})


def clean_html(text):
    if not text:
        return ""

    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def is_video_attachment(attachment):
    media_type = attachment.get("type", "")

    if media_type == "video":
        return True

    mime = (
        attachment.get("meta", {})
        .get("original", {})
        .get("mime", "")
    )

    return mime.startswith("video/")


def extract_video_url(attachment):
    url = attachment.get("url")

    if url:
        return url

    remote_url = attachment.get("remote_url")

    if remote_url:
        return remote_url

    return None


def duration_from_attachment(attachment):
    meta = attachment.get("meta", {})
    original = meta.get("original", {})

    duration = original.get("duration")

    if duration is None:
        duration = meta.get("duration")

    try:
        return float(duration)
    except (TypeError, ValueError):
        return None


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
            f"{instance} #{hashtag}: ERROR {exc}"
        )
        return []


def main():
    candidates = []
    seen = set()

    for instance in INSTANCES:
        for hashtag in HASHTAGS:
            statuses = get_statuses(
                instance,
                hashtag
            )

            for status in statuses:
                status_id = status.get("id")

                if not status_id:
                    continue

                status_url = (
                    status.get("url")
                    or status.get("uri")
                )

                attachments = status.get(
                    "media_attachments",
                    []
                )

                video_attachments = [
                    a
                    for a in attachments
                    if is_video_attachment(a)
                ]

                for attachment in video_attachments:
                    video_url = extract_video_url(
                        attachment
                    )

                    if not video_url:
                        continue

                    if video_url in seen:
                        continue

                    seen.add(video_url)

                    account = status.get(
                        "account",
                        {}
                    )

                    candidate = {
                        "source": "mastodon",
                        "instance": instance,
                        "status_id": status_id,
                        "status_url": status_url,
                        "author": (
                            account.get("display_name")
                            or account.get("username")
                            or ""
                        ),
                        "created_at": status.get(
                            "created_at"
                        ),
                        "caption": clean_html(
                            status.get("content", "")
                        ),
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
                        "video_url": video_url,
                        "duration": duration_from_attachment(
                            attachment
                        ),
                        "mime": (
                            attachment
                            .get("meta", {})
                            .get("original", {})
                            .get("mime")
                        ),
                    }

                    candidates.append(candidate)

    print()
    print("=" * 60)
    print("MASTODON VIDEO DISCOVERY RESULT")
    print("=" * 60)

    print(
        f"Unique video candidates: "
        f"{len(candidates)}"
    )

    valid_duration = []

    for candidate in candidates:
        duration = candidate.get("duration")

        if duration is None:
            continue

        if 15 <= duration <= 180:
            valid_duration.append(candidate)

    print(
        f"15–180 second candidates: "
        f"{len(valid_duration)}"
    )

    candidates.sort(
        key=lambda x: (
            x.get("favourites", 0)
            + x.get("reblogs", 0) * 2
            + x.get("replies", 0)
        ),
        reverse=True
    )

    print()
    print("TOP CANDIDATES")
    print("-" * 60)

    for index, candidate in enumerate(
        candidates[:20],
        start=1
    ):
        print(
            f"{index}. "
            f"{candidate.get('duration')} sec | "
            f"❤️ {candidate.get('favourites', 0)} | "
            f"🔁 {candidate.get('reblogs', 0)} | "
            f"💬 {candidate.get('replies', 0)}"
        )

        print(
            f"   {candidate.get('video_url')}"
        )

        print(
            f"   {candidate.get('caption', '')[:160]}"
        )

        print()

    with open(
        "mastodon_candidates.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            candidates,
            f,
            ensure_ascii=False,
            indent=2
        )

    with open(
        "mastodon_duration_candidates.json",
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            valid_duration,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        "Saved mastodon_candidates.json"
    )

    print(
        "Saved mastodon_duration_candidates.json"
    )


if __name__ == "__main__":
    main()
