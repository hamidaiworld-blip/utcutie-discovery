import json
import re
import requests


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


def safe_dict(value):
    if isinstance(value, dict):
        return value

    return {}


def is_video_attachment(attachment):
    attachment = safe_dict(attachment)

    media_type = attachment.get("type", "")

    if media_type == "video":
        return True

    meta = safe_dict(
        attachment.get("meta")
    )

    original = safe_dict(
        meta.get("original")
    )

    mime = original.get("mime", "")

    if isinstance(mime, str) and mime.startswith("video/"):
        return True

    return False


def extract_video_url(attachment):
    attachment = safe_dict(attachment)

    url = attachment.get("url")

    if url:
        return url

    remote_url = attachment.get("remote_url")

    if remote_url:
        return remote_url

    return None


def duration_from_attachment(attachment):
    attachment = safe_dict(attachment)

    meta = safe_dict(
        attachment.get("meta")
    )

    original = safe_dict(
        meta.get("original")
    )

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
        "video_url": extract_video_url(
            attachment
        ),
        "duration": duration_from_attachment(
            attachment
        ),
        "mime": (
            safe_dict(
                safe_dict(
                    attachment.get("meta")
                ).get("original")
            ).get("mime")
        ),
    }


def engagement_score(candidate):
    try:
        favourites = int(
            candidate.get(
                "favourites",
                0
            ) or 0
        )
    except (TypeError, ValueError):
        favourites = 0

    try:
        reblogs = int(
            candidate.get(
                "reblogs",
                0
            ) or 0
        )
    except (TypeError, ValueError):
        reblogs = 0

    try:
        replies = int(
            candidate.get(
                "replies",
                0
            ) or 0
        )
    except (TypeError, ValueError):
        replies = 0

    return (
        favourites
        + reblogs * 2
        + replies
    )


def main():
    candidates = []
    seen = set()

    total_statuses = 0
    total_attachments = 0
    total_video_attachments = 0

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
                    list
                ):
                    continue

                total_attachments += len(
                    attachments
                )

                for attachment in attachments:

                    if not is_video_attachment(
                        attachment
                    ):
                        continue

                    total_video_attachments += 1

                    video_url = extract_video_url(
                        attachment
                    )

                    if not video_url:
                        continue

                    if video_url in seen:
                        continue

                    seen.add(video_url)

                    candidate = build_candidate(
                        instance,
                        status,
                        attachment
                    )

                    candidates.append(
                        candidate
                    )

    valid_duration = []

    for candidate in candidates:

        duration = candidate.get(
            "duration"
        )

        if duration is None:
            continue

        if 15 <= duration <= 180:
            valid_duration.append(
                candidate
            )

    candidates.sort(
        key=engagement_score,
        reverse=True
    )

    valid_duration.sort(
        key=engagement_score,
        reverse=True
    )

    print()
    print("=" * 60)
    print("MASTODON VIDEO DISCOVERY RESULT")
    print("=" * 60)

    print(
        f"Statuses retrieved: "
        f"{total_statuses}"
    )

    print(
        f"Media attachments: "
        f"{total_attachments}"
    )

    print(
        f"Video attachments: "
        f"{total_video_attachments}"
    )

    print(
        f"Unique video candidates: "
        f"{len(candidates)}"
    )

    print(
        f"15–180 second candidates: "
        f"{len(valid_duration)}"
    )

    print()
    print("TOP VIDEO CANDIDATES")
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

    print()
    print("VALID 15–180 SECOND VIDEOS")
    print("-" * 60)

    for index, candidate in enumerate(
        valid_duration[:20],
        start=1
    ):
        print(
            f"{index}. "
            f"{candidate.get('duration')} sec | "
            f"❤️ {candidate.get('favourites', 0)} | "
            f"🔁 {candidate.get('reblogs', 0)}"
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
