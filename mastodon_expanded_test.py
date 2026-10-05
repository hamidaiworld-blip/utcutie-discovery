import hashlib
import html
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import requests


# ============================================================
# UTCUTIE MASTODON DISCOVERY — QUALITY/HARDENED VERSION
# ============================================================

INSTANCES = [
    "mastodon.social",
    "mastodon.online",
    "mastodon.world",
    "mastodon.art",
    "mastodon.green",
    "mstdn.social",
    "mstdn.party",
    "mastodon.cloud",
    "mastodon.scot",
    "mastodon.ie",
    "mastodon.xyz",
    "mastodon.gamedev.place",
]

FIXED_TAGS = [
    "cats",
    "cat",
    "kittens",
    "dogs",
    "dog",
    "puppy",
    "pets",
    "animals",
    "aww",
    "cuteanimals",
    "funnyanimals",
    "petsofthefediverse",
    "caturday",
    "dogsofthefediverse",
    "catsofthefediverse",
    "cutepets",
    "funnydogs",
    "funnycats",
    "wholesome",
    "adorable",
]

MIN_DURATION = 15
MAX_DURATION = 180
MAX_FILE_SIZE = 48 * 1024 * 1024

MAX_STATUS_PER_ENDPOINT = 25
MAX_TRENDING_TAGS_PER_INSTANCE = 15

MAX_RAW_CANDIDATES = 3000
MAX_DOWNLOAD_VALIDATION = 150
MAX_SELECTED = 20

MAX_VIDEOS_PER_ACCOUNT = 2
MAX_VIDEOS_PER_INSTANCE = 6

# Production-quality freshness policy.
# Videos older than this are allowed only as a fallback.
PREFERRED_MAX_AGE_DAYS = 14
HARD_MAX_AGE_DAYS = 90

REQUEST_TIMEOUT = 25
DOWNLOAD_TIMEOUT = 60

HISTORY_FILE = Path("history.json")

OUTPUT_CANDIDATES = Path(
    "mastodon_expanded_candidates.json"
)

OUTPUT_VALIDATED = Path(
    "mastodon_expanded_validated.json"
)

OUTPUT_SELECTED = Path(
    "mastodon_expanded_selected_candidates.json"
)

DOWNLOAD_DIR = Path(
    "mastodon_expanded_downloads"
)


# ============================================================
# HTTP
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": (
            "UTCutie/1.0 "
            "(pet-video discovery; Mastodon public API)"
        ),
        "Accept": "application/json",
    }
)


# ============================================================
# HISTORY
# ============================================================

def load_history():
    if not HISTORY_FILE.exists():
        return []

    try:
        with HISTORY_FILE.open(
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        return data if isinstance(data, list) else []

    except Exception as exc:
        print(
            f"WARNING: Could not read history.json: {exc}"
        )
        return []


def history_keys(history):
    keys = set()

    for item in history:
        if not isinstance(item, dict):
            continue

        for field in (
            "media_url",
            "status_url",
            "source_url",
            "sha256",
            "id",
        ):
            value = item.get(field)

            if value:
                keys.add(str(value))

    return keys


# ============================================================
# TEXT
# ============================================================

def clean_caption(raw):
    if not raw:
        return ""

    text = str(raw)

    text = re.sub(
        r"<script\b[^>]*>.*?</script>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    text = re.sub(
        r"<style\b[^>]*>.*?</style>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    text = re.sub(
        r"<(?:br|/p|/div|/li|/blockquote|/h[1-6])\s*/?>",
        "\n",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"<[^>]+>",
        "",
        text,
    )

    text = html.unescape(text)

    text = re.sub(
        r"https?://\S+|www\.\S+",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"(?<!\w)#[\w]+",
        "",
        text,
        flags=re.UNICODE,
    )

    lines = []

    for line in text.splitlines():
        line = re.sub(
            r"[ \t]+",
            " ",
            line,
        ).strip()

        if line:
            lines.append(line)

    text = "\n".join(lines)

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


def truncate_caption(text, max_length=900):
    if len(text) <= max_length:
        return text

    shortened = text[:max_length]

    positions = [
        shortened.rfind("\n"),
        shortened.rfind(". "),
        shortened.rfind(" "),
    ]

    cut = max(positions)

    if cut >= 200:
        shortened = shortened[:cut]

    return shortened.rstrip()


# ============================================================
# DATE / SCORING
# ============================================================

def parse_datetime(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except Exception:
        return None


def age_days(created_at):
    dt = parse_datetime(created_at)

    if not dt:
        return 9999

    now = datetime.now(timezone.utc)

    return max(
        0,
        (
            now - dt.astimezone(timezone.utc)
        ).total_seconds()
        / 86400,
    )


def recency_score(created_at):
    days = age_days(created_at)

    if days <= 1:
        return 100.0

    if days <= 3:
        return 90.0

    if days <= 7:
        return 80.0

    if days <= 14:
        return 65.0

    if days <= 30:
        return 40.0

    if days <= 60:
        return 20.0

    return 5.0


def engagement_score(status):
    import math

    favourites = int(
        status.get("favourites_count") or 0
    )

    reblogs = int(
        status.get("reblogs_count") or 0
    )

    replies = int(
        status.get("replies_count") or 0
    )

    raw = (
        favourites
        + reblogs * 2.5
        + replies * 0.75
    )

    if raw <= 0:
        return 0.0

    return min(
        100.0,
        math.log10(raw + 1) * 22.0,
    )


# ============================================================
# ANIMAL RELEVANCE
# ============================================================

ANIMAL_TERMS = [
    "cat",
    "cats",
    "kitten",
    "kittens",
    "kitty",
    "dog",
    "dogs",
    "puppy",
    "puppies",
    "pup",
    "pet",
    "pets",
    "animal",
    "animals",
    "rabbit",
    "rabbits",
    "bunny",
    "bunnies",
    "hamster",
    "bird",
    "birds",
    "parrot",
    "duck",
    "ducks",
    "chicken",
    "goat",
    "horse",
    "horses",
    "cow",
    "sheep",
    "fox",
    "otter",
    "seal",
    "penguin",
    "panda",
    "bear",
    "monkey",
    "squirrel",
]

FUN_TERMS = [
    "funny",
    "hilarious",
    "cute",
    "adorable",
    "aww",
    "silly",
    "goofy",
    "lol",
    "haha",
    "zoomies",
    "play",
    "playing",
    "sleeping",
    "sleepy",
    "wholesome",
    "heartwarming",
    "sweet",
]

NEGATIVE_TERMS = [
    "gore",
    "blood",
    "dead",
    "death",
    "killing",
    "kill",
    "injured",
    "injury",
    "abuse",
    "violence",
    "violent",
    "attack",
    "fighting",
    "fight",
    "war",
    "weapon",
    "weapons",
    "nsfw",
]


def animal_relevance_score(text):
    text = (text or "").lower()

    animal_hits = sum(
        1
        for term in ANIMAL_TERMS
        if re.search(
            rf"\b{re.escape(term)}\b",
            text,
        )
    )

    fun_hits = sum(
        1
        for term in FUN_TERMS
        if re.search(
            rf"\b{re.escape(term)}\b",
            text,
        )
    )

    negative_hits = sum(
        1
        for term in NEGATIVE_TERMS
        if re.search(
            rf"\b{re.escape(term)}\b",
            text,
        )
    )

    score = (
        animal_hits * 22
        + fun_hits * 6
        - negative_hits * 40
    )

    return max(
        0.0,
        min(100.0, score),
    )


def caption_quality_score(text):
    if not text:
        return 10.0

    length = len(text)

    score = 20.0

    if 20 <= length <= 250:
        score += 45

    elif 10 <= length <= 500:
        score += 30

    elif length > 500:
        score += 10

    if "\n" in text:
        score += 10

    alphanumeric = sum(
        char.isalnum()
        for char in text
    )

    if alphanumeric >= 15:
        score += 15

    return min(
        100.0,
        score,
    )


# ============================================================
# STATUS / MEDIA HELPERS
# ============================================================

def media_is_video(media):
    if not isinstance(media, dict):
        return False

    media_type = str(
        media.get("type", "")
    ).lower()

    if media_type in (
        "video",
        "gifv",
    ):
        return True

    url = str(
        media.get("url") or ""
    ).lower()

    return url.split("?")[0].endswith(
        (
            ".mp4",
            ".webm",
            ".mov",
            ".m4v",
            ".mkv",
        )
    )


def get_media_url(media):
    return (
        media.get("url")
        or media.get("remote_url")
        or media.get("preview_url")
    )


def account_key(status):
    account = status.get("account") or {}

    return str(
        account.get("acct")
        or account.get("url")
        or account.get("id")
        or "unknown"
    ).lower()


def status_url(status, instance):
    url = status.get("url")

    if url:
        return url

    account = status.get("account") or {}

    account_url = account.get("url")
    status_id = status.get("id")

    if account_url and status_id:
        return (
            f"{account_url}/{status_id}"
        )

    return (
        f"https://{instance}/@unknown/{status_id}"
    )


def canonical_url(url):
    if not url:
        return ""

    parsed = urlparse(url)

    if not parsed.netloc:
        return url.rstrip("/")

    return (
        f"{parsed.scheme.lower()}://"
        f"{parsed.netloc.lower()}"
        f"{parsed.path.rstrip('/')}"
    )


def media_key(url):
    if not url:
        return ""

    return url.split("?")[0].rstrip("/")


def canonical_content_key(candidate):
    """
    Prefer the federated status URL because the same post can
    appear on several Mastodon instances with different media
    cache URLs and different status IDs.
    """

    status = canonical_url(
        candidate.get("status_url")
    )

    if status:
        return f"status:{status}"

    return (
        f"media:"
        f"{media_key(candidate.get('media_url'))}"
    )


# ============================================================
# MASTODON API
# ============================================================

def api_get(instance, path, params=None):
    url = (
        f"https://{instance}{path}"
    )

    response = SESSION.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


def get_trending_tags(instance):
    try:
        data = api_get(
            instance,
            "/api/v1/trends/tags",
            {"limit": 20},
        )

        result = []

        if isinstance(data, list):
            for item in data:
                name = item.get("name")

                if name:
                    result.append(
                        str(name).lower()
                    )

        return result[
            :MAX_TRENDING_TAGS_PER_INSTANCE
        ]

    except Exception as exc:
        print(
            f"  TRENDING TAGS FAILED: "
            f"{instance} | {exc}"
        )

        return []


def get_tag_statuses(instance, tag):
    try:
        data = api_get(
            instance,
            (
                "/api/v1/timelines/tag/"
                f"{quote(tag, safe='')}"
            ),
            {
                "limit": MAX_STATUS_PER_ENDPOINT,
                "only_media": "true",
            },
        )

        return (
            data
            if isinstance(data, list)
            else []
        )

    except Exception as exc:
        print(
            f"  TAG FAILED: "
            f"{instance} #{tag} | {exc}"
        )

        return []


def get_public_media_statuses(instance):
    try:
        data = api_get(
            instance,
            "/api/v1/timelines/public",
            {
                "limit": MAX_STATUS_PER_ENDPOINT,
                "only_media": "true",
            },
        )

        return (
            data
            if isinstance(data, list)
            else []
        )

    except Exception as exc:
        print(
            f"  PUBLIC MEDIA FAILED: "
            f"{instance} | {exc}"
        )

        return []


# ============================================================
# CANDIDATE EXTRACTION
# ============================================================

def extract_candidates(
    statuses,
    instance,
    discovery_source,
):
    candidates = []

    for status in statuses:
        if not isinstance(status, dict):
            continue

        if status.get("sensitive"):
            continue

        visibility = status.get("visibility")

        if visibility not in (
            None,
            "public",
            "unlisted",
        ):
            continue

        media_attachments = (
            status.get("media_attachments")
            or []
        )

        caption = clean_caption(
            status.get("content", "")
        )

        tags = status.get("tags") or []

        tag_text = " ".join(
            str(tag.get("name", ""))
            for tag in tags
        )

        relevance_text = (
            f"{caption} {tag_text}"
        )

        relevance = (
            animal_relevance_score(
                relevance_text
            )
        )

        for media in media_attachments:
            if not media_is_video(media):
                continue

            media_url = get_media_url(media)

            if not media_url:
                continue

            candidate = {
                "source": "mastodon",
                "instance": instance,
                "discovery_source": discovery_source,
                "status_id": str(
                    status.get("id") or ""
                ),
                "status_url": status_url(
                    status,
                    instance,
                ),
                "created_at": status.get(
                    "created_at"
                ),
                "account": account_key(
                    status
                ),
                "account_name": (
                    status.get(
                        "account",
                        {},
                    ).get(
                        "display_name"
                    )
                    or status.get(
                        "account",
                        {},
                    ).get(
                        "username"
                    )
                    or ""
                ),
                "media_url": media_url,
                "media_type": media.get(
                    "type"
                ),
                "caption": caption,
                "caption_length": len(
                    caption
                ),
                "favourites_count": int(
                    status.get(
                        "favourites_count"
                    )
                    or 0
                ),
                "reblogs_count": int(
                    status.get(
                        "reblogs_count"
                    )
                    or 0
                ),
                "replies_count": int(
                    status.get(
                        "replies_count"
                    )
                    or 0
                ),
                "animal_relevance": relevance,
                "engagement": engagement_score(
                    status
                ),
                "recency": recency_score(
                    status.get(
                        "created_at"
                    )
                ),
                "quality": 0.0,
                "caption_quality": (
                    caption_quality_score(
                        caption
                    )
                ),
            }

            # Strong pre-validation gate.
            #
            # We allow an empty caption only when the
            # status has an explicitly animal-related tag.
            if relevance < 20:
                tag_relevance = (
                    animal_relevance_score(
                        tag_text
                    )
                )

                if tag_relevance < 20:
                    continue

            candidate[
                "pre_validation_score"
            ] = (
                candidate[
                    "animal_relevance"
                ]
                * 2.8
                + candidate[
                    "engagement"
                ]
                * 1.1
                + candidate[
                    "recency"
                ]
                + candidate[
                    "caption_quality"
                ]
                * 0.5
            )

            candidates.append(
                candidate
            )

    return candidates


# ============================================================
# DOWNLOAD / VIDEO VALIDATION
# ============================================================

def download_video(
    url,
    output_path,
):
    try:
        with SESSION.get(
            url,
            stream=True,
            timeout=DOWNLOAD_TIMEOUT,
        ) as response:

            response.raise_for_status()

            content_type = (
                response.headers.get(
                    "content-type"
                )
                or ""
            ).lower()

            if (
                "video" not in content_type
                and "octet-stream"
                not in content_type
            ):
                return (
                    False,
                    "not_video_content_type",
                )

            content_length = (
                response.headers.get(
                    "content-length"
                )
            )

            if content_length:
                try:
                    if (
                        int(content_length)
                        > MAX_FILE_SIZE
                    ):
                        return (
                            False,
                            "too_large",
                        )
                except Exception:
                    pass

            total = 0

            with output_path.open(
                "wb"
            ) as f:

                for chunk in response.iter_content(
                    chunk_size=1024 * 256
                ):
                    if not chunk:
                        continue

                    total += len(chunk)

                    if total > MAX_FILE_SIZE:
                        return (
                            False,
                            "too_large",
                        )

                    f.write(chunk)

        return True, "ok"

    except Exception as exc:
        return False, str(exc)


def ffprobe_video(path):
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,duration,width,height",
        "-of",
        "json",
        str(path),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return None

        data = json.loads(
            result.stdout
        )

        streams = (
            data.get("streams")
            or []
        )

        if not streams:
            return None

        stream = streams[0]

        duration = float(
            stream.get("duration")
            or 0
        )

        if duration <= 0:
            return None

        return {
            "duration": duration,
            "codec": stream.get(
                "codec_name"
            ),
            "width": int(
                stream.get("width")
                or 0
            ),
            "height": int(
                stream.get("height")
                or 0
            ),
        }

    except Exception:
        return None


def validate_candidate(
    candidate,
    index,
):
    media_url = candidate[
        "media_url"
    ]

    filename = (
        f"{index}_"
        f"{Path(media_url.split('?')[0]).name}"
    )

    filename = re.sub(
        r"[^a-zA-Z0-9._-]+",
        "_",
        filename,
    )

    if not filename.lower().endswith(
        (
            ".mp4",
            ".webm",
            ".mov",
            ".m4v",
            ".mkv",
        )
    ):
        filename += ".mp4"

    output_path = (
        DOWNLOAD_DIR / filename
    )

    ok, reason = download_video(
        media_url,
        output_path,
    )

    if not ok:
        candidate[
            "validation_error"
        ] = reason

        return None

    size = output_path.stat().st_size

    if (
        size <= 0
        or size > MAX_FILE_SIZE
    ):
        return None

    probe = ffprobe_video(
        output_path
    )

    if not probe:
        return None

    duration = probe[
        "duration"
    ]

    if duration < MIN_DURATION:
        return None

    if duration > MAX_DURATION:
        return None

    sha256 = hashlib.sha256()

    with output_path.open(
        "rb"
    ) as f:

        for chunk in iter(
            lambda: f.read(
                1024 * 1024
            ),
            b"",
        ):
            sha256.update(chunk)

    candidate[
        "duration"
    ] = round(
        duration,
        3,
    )

    candidate[
        "file_size"
    ] = size

    candidate[
        "sha256"
    ] = sha256.hexdigest()

    candidate[
        "codec"
    ] = probe[
        "codec"
    ]

    candidate[
        "width"
    ] = probe[
        "width"
    ]

    candidate[
        "height"
    ] = probe[
        "height"
    ]

    max_dimension = max(
        probe["width"],
        probe["height"],
    )

    if max_dimension >= 1080:
        actual_quality = 100

    elif max_dimension >= 720:
        actual_quality = 80

    elif max_dimension >= 480:
        actual_quality = 55

    else:
        actual_quality = 25

    candidate[
        "actual_quality"
    ] = actual_quality

    candidate[
        "age_days"
    ] = round(
        age_days(
            candidate[
                "created_at"
            ]
        ),
        2,
    )

    # Final score.
    candidate[
        "score"
    ] = (
        candidate[
            "animal_relevance"
        ]
        * 2.8
        + candidate[
            "engagement"
        ]
        * 1.1
        + candidate[
            "recency"
        ]
        + actual_quality
        + candidate[
            "caption_quality"
        ]
        * 0.5
    )

    return candidate


# ============================================================
# MAIN
# ============================================================

def main():
    print()
    print("=" * 70)
    print(
        "UTCUTIE MASTODON DISCOVERY "
        "— QUALITY HARDENED"
    )
    print("=" * 70)
    print()

    history = load_history()

    history_key_set = history_keys(
        history
    )

    print(
        f"Publication history entries: "
        f"{len(history)}"
    )

    print()

    if DOWNLOAD_DIR.exists():
        shutil.rmtree(
            DOWNLOAD_DIR
        )

    DOWNLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # TRENDING TAGS
    # --------------------------------------------------------

    instance_tags = {}
    all_trending_tags = set()

    for instance in INSTANCES:
        print(
            f"TRENDING TAGS: {instance}"
        )

        tags = get_trending_tags(
            instance
        )

        instance_tags[
            instance
        ] = tags

        print(
            f"  Trending tags discovered: "
            f"{len(tags)}"
        )

        all_trending_tags.update(
            tags
        )

    print()

    animal_words = (
        "cat",
        "dog",
        "pet",
        "animal",
        "kitten",
        "puppy",
        "rabbit",
        "bunny",
        "bird",
        "parrot",
        "hamster",
        "goat",
        "horse",
        "cow",
        "sheep",
        "fox",
        "otter",
        "panda",
        "penguin",
        "bear",
        "monkey",
        "squirrel",
        "cute",
        "funny",
        "aww",
        "caturday",
    )

    trending_animal_tags = sorted(
        tag
        for tag in all_trending_tags
        if any(
            word in tag.lower()
            for word in animal_words
        )
    )

    print(
        "Animal-related trending tags: "
        f"{len(trending_animal_tags)}"
    )

    print()

    # --------------------------------------------------------
    # COLLECT STATUSES
    # --------------------------------------------------------

    raw_statuses = []

    seen_status_ids = set()

    for instance in INSTANCES:
        print()
        print("=" * 60)
        print(
            f"INSTANCE: {instance}"
        )
        print("=" * 60)

        tags = list(
            FIXED_TAGS
        )

        tags.extend(
            instance_tags.get(
                instance,
                [],
            )
        )

        tags.extend(
            trending_animal_tags
        )

        unique_tags = []

        for tag in tags:
            tag = str(
                tag
            ).strip().lower()

            if (
                tag
                and tag not in unique_tags
            ):
                unique_tags.append(
                    tag
                )

        for tag in unique_tags:
            if (
                len(raw_statuses)
                >= MAX_RAW_CANDIDATES
            ):
                break

            print(
                f"TAG: #{tag}"
            )

            statuses = (
                get_tag_statuses(
                    instance,
                    tag,
                )
            )

            print(
                f"  statuses: "
                f"{len(statuses)}"
            )

            for status in statuses:
                status_id = str(
                    status.get(
                        "id"
                    )
                    or ""
                )

                if not status_id:
                    continue

                key = (
                    instance,
                    status_id,
                )

                if key in seen_status_ids:
                    continue

                seen_status_ids.add(
                    key
                )

                raw_statuses.append(
                    (
                        status,
                        instance,
                        f"tag:{tag}",
                    )
                )

        if (
            len(raw_statuses)
            < MAX_RAW_CANDIDATES
        ):
            print(
                "PUBLIC MEDIA TIMELINE"
            )

            statuses = (
                get_public_media_statuses(
                    instance
                )
            )

            print(
                f"  statuses: "
                f"{len(statuses)}"
            )

            for status in statuses:
                status_id = str(
                    status.get(
                        "id"
                    )
                    or ""
                )

                if not status_id:
                    continue

                key = (
                    instance,
                    status_id,
                )

                if key in seen_status_ids:
                    continue

                seen_status_ids.add(
                    key
                )

                raw_statuses.append(
                    (
                        status,
                        instance,
                        "public_media",
                    )
                )

    print()
    print(
        f"Raw unique statuses discovered: "
        f"{len(raw_statuses)}"
    )

    # --------------------------------------------------------
    # EXTRACT CANDIDATES
    # --------------------------------------------------------

    candidates = []

    for (
        status,
        instance,
        discovery_source,
    ) in raw_statuses:

        candidates.extend(
            extract_candidates(
                [status],
                instance,
                discovery_source,
            )
        )

    print(
        f"Raw relevant video candidates: "
        f"{len(candidates)}"
    )

    # --------------------------------------------------------
    # DEDUP BEFORE DOWNLOAD
    #
    # Same federated post may appear on several instances.
    # Use status URL first, then media URL.
    # --------------------------------------------------------

    unique_candidates = {}

    for candidate in candidates:
        key = canonical_content_key(
            candidate
        )

        existing = (
            unique_candidates.get(
                key
            )
        )

        if (
            existing is None
            or candidate[
                "pre_validation_score"
            ]
            > existing[
                "pre_validation_score"
            ]
        ):
            unique_candidates[
                key
            ] = candidate

    candidates = list(
        unique_candidates.values()
    )

    candidates.sort(
        key=lambda item: item[
            "pre_validation_score"
        ],
        reverse=True,
    )

    candidates = candidates[
        :MAX_DOWNLOAD_VALIDATION
    ]

    print(
        f"Unique candidates for validation: "
        f"{len(candidates)}"
    )

    with OUTPUT_CANDIDATES.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            candidates,
            f,
            ensure_ascii=False,
            indent=2,
        )

    # --------------------------------------------------------
    # ACTUAL VIDEO VALIDATION
    # --------------------------------------------------------

    validated = []

    for index, candidate in enumerate(
        candidates,
        start=1,
    ):
        print(
            f"[{index}/{len(candidates)}] "
            f"VALIDATE "
            f"{candidate['media_url']}"
        )

        result = validate_candidate(
            candidate,
            index,
        )

        if result:
            print(
                f"  VALID: "
                f"{result['duration']}s "
                f"score="
                f"{result['score']:.2f}"
            )

            validated.append(
                result
            )

        else:
            print(
                "  INVALID"
            )

    print()
    print(
        f"Validated videos: "
        f"{len(validated)}"
    )

    # --------------------------------------------------------
    # SHA DEDUP
    # --------------------------------------------------------

    unique_hashes = {}

    for candidate in validated:
        sha = candidate.get(
            "sha256"
        )

        if not sha:
            continue

        existing = (
            unique_hashes.get(
                sha
            )
        )

        if (
            existing is None
            or candidate[
                "score"
            ]
            > existing[
                "score"
            ]
        ):
            unique_hashes[
                sha
            ] = candidate

    validated = list(
        unique_hashes.values()
    )

    print(
        f"Unique validated videos: "
        f"{len(validated)}"
    )

    # --------------------------------------------------------
    # HISTORY FILTER
    # --------------------------------------------------------

    fresh = []

    for candidate in validated:
        identifiers = {
            candidate.get(
                "media_url"
            ),
            candidate.get(
                "status_url"
            ),
            candidate.get(
                "sha256"
            ),
        }

        if identifiers & history_key_set:
            continue

        fresh.append(
            candidate
        )

    print(
        f"Fresh videos after history: "
        f"{len(fresh)}"
    )

    # --------------------------------------------------------
    # FRESHNESS FILTER
    #
    # Prefer recent material.
    # Do not allow ancient material into the normal daily
    # selection when newer material is available.
    # --------------------------------------------------------

    preferred_fresh = [
        candidate
        for candidate in fresh
        if candidate.get(
            "age_days",
            9999,
        )
        <= PREFERRED_MAX_AGE_DAYS
    ]

    fallback_fresh = [
        candidate
        for candidate in fresh
        if (
            PREFERRED_MAX_AGE_DAYS
            < candidate.get(
                "age_days",
                9999,
            )
            <= HARD_MAX_AGE_DAYS
        )
    ]

    print(
        f"Preferred fresh videos "
        f"(<= {PREFERRED_MAX_AGE_DAYS} days): "
        f"{len(preferred_fresh)}"
    )

    print(
        f"Fallback videos "
        f"({PREFERRED_MAX_AGE_DAYS}–"
        f"{HARD_MAX_AGE_DAYS} days): "
        f"{len(fallback_fresh)}"
    )

    # --------------------------------------------------------
    # GLOBAL RANKING
    # --------------------------------------------------------

    preferred_fresh.sort(
        key=lambda item: item[
            "score"
        ],
        reverse=True,
    )

    fallback_fresh.sort(
        key=lambda item: item[
            "score"
        ],
        reverse=True,
    )

    ranked = (
        preferred_fresh
        + fallback_fresh
    )

    # --------------------------------------------------------
    # DIVERSITY-AWARE SELECTION
    # --------------------------------------------------------

    selected = []

    account_counts = {}
    instance_counts = {}
    selected_content_keys = set()

    # First pass.
    for candidate in ranked:
        content_key = (
            canonical_content_key(
                candidate
            )
        )

        if (
            content_key
            in selected_content_keys
        ):
            continue

        account = candidate[
            "account"
        ]

        instance = candidate[
            "instance"
        ]

        if (
            account_counts.get(
                account,
                0,
            )
            >= MAX_VIDEOS_PER_ACCOUNT
        ):
            continue

        if (
            instance_counts.get(
                instance,
                0,
            )
            >= MAX_VIDEOS_PER_INSTANCE
        ):
            continue

        selected.append(
            candidate
        )

        selected_content_keys.add(
            content_key
        )

        account_counts[
            account
        ] = (
            account_counts.get(
                account,
                0,
            )
            + 1
        )

        instance_counts[
            instance
        ] = (
            instance_counts.get(
                instance,
                0,
            )
            + 1
        )

        if (
            len(selected)
            >= MAX_SELECTED
        ):
            break

    # Second pass fills remaining slots.
    if len(selected) < MAX_SELECTED:
        for candidate in ranked:
            content_key = (
                canonical_content_key(
                    candidate
                )
            )

            if (
                content_key
                in selected_content_keys
            ):
                continue

            selected.append(
                candidate
            )

            selected_content_keys.add(
                content_key
            )

            if (
                len(selected)
                >= MAX_SELECTED
            ):
                break

    # --------------------------------------------------------
    # TELEGRAM CAPTIONS
    # --------------------------------------------------------

    for candidate in selected:
        candidate[
            "telegram_caption"
        ] = truncate_caption(
            candidate.get(
                "caption",
                "",
            ),
            900,
        )

    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    with OUTPUT_VALIDATED.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            validated,
            f,
            ensure_ascii=False,
            indent=2,
        )

    with OUTPUT_SELECTED.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            selected,
            f,
            ensure_ascii=False,
            indent=2,
        )

    # --------------------------------------------------------
    # REPORT
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print(
        "UTCUTIE MASTODON DISCOVERY "
        "— QUALITY HARDENED COMPLETE"
    )
    print("=" * 70)

    print(
        f"Publication history entries: "
        f"{len(history)}"
    )

    print(
        f"Raw unique statuses: "
        f"{len(raw_statuses)}"
    )

    print(
        f"Unique candidates: "
        f"{len(candidates)}"
    )

    print(
        f"Validated videos: "
        f"{len(validated)}"
    )

    print(
        f"Fresh videos after history: "
        f"{len(fresh)}"
    )

    print(
        f"Preferred fresh videos: "
        f"{len(preferred_fresh)}"
    )

    print(
        f"Selected videos: "
        f"{len(selected)}"
    )

    print()

    for index, candidate in enumerate(
        selected,
        start=1,
    ):
        print(
            f"{index}. "
            f"{candidate['duration']}s | "
            f"age={candidate['age_days']}d | "
            f"score={candidate['score']:.2f} | "
            f"{candidate['status_url']}"
        )

    print()
    print(
        f"Raw results: "
        f"{OUTPUT_CANDIDATES}"
    )

    print(
        f"Validated results: "
        f"{OUTPUT_VALIDATED}"
    )

    print(
        f"Selected results: "
        f"{OUTPUT_SELECTED}"
    )

    print()
    print(
        "IMPORTANT: history.json was NOT modified."
    )

    shutil.rmtree(
        DOWNLOAD_DIR,
        ignore_errors=True,
    )


if __name__ == "__main__":
    main()
