import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests


# ============================================================
# CONFIG
# ============================================================

INSTANCES = [
    "https://mastodon.social",
    "https://mastodon.online",
    "https://mastodon.world",
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

REQUEST_TIMEOUT = 30

HISTORY_FILE = Path("history.json")
CANDIDATES_FILE = Path("mastodon_candidates.json")
VALIDATED_FILE = Path("validated_candidates.json")
SELECTED_FILE = Path("selected_candidates.json")


# ============================================================
# ANIMAL RELEVANCE
# ============================================================

ANIMAL_KEYWORDS = {
    "cat": 5,
    "cats": 5,
    "kitten": 5,
    "kittens": 5,
    "dog": 5,
    "dogs": 5,
    "puppy": 5,
    "puppies": 5,
    "pet": 4,
    "pets": 4,
    "animal": 4,
    "animals": 4,
    "puppy": 5,
    "pup": 5,
    "kitty": 5,
    "kitties": 5,
    "feline": 5,
    "canine": 5,
    "bird": 4,
    "birds": 4,
    "parrot": 5,
    "parrots": 5,
    "hamster": 5,
    "hamsters": 5,
    "rabbit": 5,
    "rabbits": 5,
    "bunny": 5,
    "bunnies": 5,
    "guinea": 4,
    "pig": 3,
    "pigs": 3,
    "horse": 4,
    "horses": 4,
    "cow": 4,
    "cows": 4,
    "goat": 4,
    "goats": 4,
    "sheep": 4,
    "duck": 4,
    "ducks": 4,
    "chicken": 4,
    "chickens": 4,
    "fox": 4,
    "foxes": 4,
    "bear": 4,
    "bears": 4,
    "wildlife": 4,
    "zoo": 3,
    "animalvideo": 5,
    "animalvideos": 5,
    "cuteanimal": 5,
    "cuteanimals": 5,
    "funnyanimal": 5,
    "funnyanimals": 5,
    "petsofthefediverse": 5,
}


# ============================================================
# HELPERS
# ============================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_text(text):
    if not text:
        return ""

    text = re.sub(r"<[^>]+>", " ", text)
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokenize(text):
    return set(re.findall(r"[a-z0-9]+", normalize_text(text)))


def animal_relevance(text):
    tokens = tokenize(text)

    score = 0

    for keyword, value in ANIMAL_KEYWORDS.items():
        if keyword in tokens:
            score += value

    return score


def engagement_score(favourites, reblogs, replies):
    favourites = max(0, int(favourites or 0))
    reblogs = max(0, int(reblogs or 0))
    replies = max(0, int(replies or 0))

    score = 0.0

    score += min(40.0, favourites ** 0.5)
    score += min(30.0, reblogs ** 0.5 * 1.5)
    score += min(15.0, replies ** 0.5)

    return round(score, 3)


def recency_score(created_at):
    if not created_at:
        return 0.0

    try:
        created = datetime.fromisoformat(
            created_at.replace("Z", "+00:00")
        )

        age_hours = (
            datetime.now(timezone.utc) - created
        ).total_seconds() / 3600

        if age_hours < 0:
            age_hours = 0

        if age_hours <= 6:
            return 30.0

        if age_hours <= 24:
            return 25.0

        if age_hours <= 72:
            return 18.0

        if age_hours <= 168:
            return 10.0

        if age_hours <= 720:
            return 4.0

        return 1.0

    except Exception:
        return 0.0


def quality_score(width, height):
    try:
        width = int(width or 0)
        height = int(height or 0)
    except Exception:
        return 0.0

    pixels = width * height

    if pixels >= 1920 * 1080:
        return 25.0

    if pixels >= 1280 * 720:
        return 22.0

    if pixels >= 854 * 480:
        return 16.0

    if pixels >= 640 * 360:
        return 10.0

    if pixels > 0:
        return 5.0

    return 0.0


def caption_fingerprint(text):
    normalized = normalize_text(text)

    if not normalized:
        return ""

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()


def load_json(path, default):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# MASTODON DISCOVERY
# ============================================================

def discover_candidates():
    candidates = []

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 "
                "UTCutie-Mastodon-Discovery/1.0"
            )
        }
    )

    for instance in INSTANCES:
        print()
        print("=" * 70)
        print(f"INSTANCE: {instance}")
        print("=" * 70)

        for hashtag in HASHTAGS:
            url = (
                f"{instance}/api/v1/timelines/tag/"
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
                    timeout=REQUEST_TIMEOUT,
                )

                print(
                    f"{instance} #{hashtag}: "
                    f"HTTP {response.status_code}"
                )

                if response.status_code != 200:
                    continue

                statuses = response.json()

                if not isinstance(statuses, list):
                    continue

                for status in statuses:
                    if not isinstance(status, dict):
                        continue

                    media = status.get("media_attachments")

                    if not isinstance(media, list):
                        continue

                    for attachment in media:
                        if not isinstance(attachment, dict):
                            continue

                        media_type = attachment.get("type")

                        if media_type != "video":
                            continue

                        media_url = attachment.get("url")

                        if not media_url:
                            continue

                        account = status.get("account")

                        if not isinstance(account, dict):
                            account = {}

                        candidate = {
                            "status_id": status.get("id"),
                            "status_url": status.get("url"),
                            "instance": instance,
                            "created_at": status.get("created_at"),
                            "caption": status.get("content", ""),
                            "account": account.get("acct"),
                            "account_display_name": (
                                account.get("display_name")
                            ),
                            "media_url": media_url,
                            "media_preview_url": (
                                attachment.get("preview_url")
                            ),
                            "media_type": media_type,
                            "width": attachment.get("meta", {})
                            .get("original", {})
                            .get("width")
                            if isinstance(
                                attachment.get("meta"),
                                dict
                            )
                            else None,
                            "height": attachment.get("meta", {})
                            .get("original", {})
                            .get("height")
                            if isinstance(
                                attachment.get("meta"),
                                dict
                            )
                            else None,
                            "favourites": status.get(
                                "favourites_count",
                                0
                            ),
                            "reblogs": status.get(
                                "reblogs_count",
                                0
                            ),
                            "replies": status.get(
                                "replies_count",
                                0
                            ),
                            "hashtag": hashtag,
                        }

                        candidates.append(candidate)

            except Exception as exc:
                print(
                    f"ERROR {instance} #{hashtag}: "
                    f"{type(exc).__name__}: {exc}"
                )

    return candidates


# ============================================================
# DEDUPLICATION
# ============================================================

def deduplicate_candidates(candidates):
    unique = []
    seen = set()

    for candidate in candidates:
        media_url = candidate.get("media_url")
        status_url = candidate.get("status_url")

        key = media_url or status_url

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)
        unique.append(candidate)

    return unique


# ============================================================
# VIDEO VALIDATION
# ============================================================

def download_and_validate(candidate):
    media_url = candidate.get("media_url")

    if not media_url:
        return None

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".video",
            delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)

        print()
        print(
            "Downloading:",
            candidate.get("status_url")
        )

        response = requests.get(
            media_url,
            stream=True,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "UTCutie-Mastodon-Discovery/1.0"
                )
            },
        )

        if response.status_code != 200:
            print(
                "  HTTP failure:",
                response.status_code
            )
            return None

        content_type = (
            response.headers.get("content-type", "")
            .lower()
        )

        if (
            "video" not in content_type
            and "octet-stream" not in content_type
        ):
            print(
                "  Not a video content type:",
                content_type
            )
            return None

        content_length = response.headers.get(
            "content-length"
        )

        if content_length:
            try:
                if int(content_length) > MAX_FILE_SIZE:
                    print("  File too large.")
                    return None
            except ValueError:
                pass

        total_bytes = 0

        with temp_path.open("wb") as output:
            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):
                if not chunk:
                    continue

                total_bytes += len(chunk)

                if total_bytes > MAX_FILE_SIZE:
                    print("  File exceeded 48 MB.")
                    return None

                output.write(chunk)

        if total_bytes == 0:
            print("  Empty file.")
            return None

        probe_command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-show_entries",
            "stream=width,height,codec_type",
            "-of",
            "json",
            str(temp_path),
        ]

        probe = subprocess.run(
            probe_command,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if probe.returncode != 0:
            print("  ffprobe failed.")
            return None

        try:
            metadata = json.loads(probe.stdout)
        except Exception:
            print("  Invalid ffprobe output.")
            return None

        format_data = metadata.get("format")

        if not isinstance(format_data, dict):
            format_data = {}

        streams = metadata.get("streams")

        if not isinstance(streams, list):
            streams = []

        duration = format_data.get("duration")

        if duration is None:
            print("  Duration unavailable.")
            return None

        duration = float(duration)

        if duration < MIN_DURATION:
            print(
                f"  Too short: {duration:.2f}s"
            )
            return None

        if duration > MAX_DURATION:
            print(
                f"  Too long: {duration:.2f}s"
            )
            return None

        width = 0
        height = 0
        has_video_stream = False

        for stream in streams:
            if not isinstance(stream, dict):
                continue

            if stream.get("codec_type") != "video":
                continue

            has_video_stream = True

            try:
                width = int(stream.get("width") or 0)
            except Exception:
                width = 0

            try:
                height = int(stream.get("height") or 0)
            except Exception:
                height = 0

            break

        if not has_video_stream:
            print("  No video stream.")
            return None

        if width <= 0 or height <= 0:
            print("  Invalid video dimensions.")
            return None

        file_hash = hashlib.sha256()

        with temp_path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)

                if not chunk:
                    break

                file_hash.update(chunk)

        sha256 = file_hash.hexdigest()

        result = dict(candidate)

        result["duration"] = round(duration, 3)
        result["file_size"] = total_bytes
        result["file_size_mb"] = round(
            total_bytes / (1024 * 1024),
            3
        )
        result["width"] = width
        result["height"] = height
        result["sha256"] = sha256

        return result

    except requests.RequestException as exc:
        print(
            "  Download error:",
            type(exc).__name__,
            exc
        )
        return None

    except subprocess.TimeoutExpired:
        print("  ffprobe timeout.")
        return None

    except Exception as exc:
        print(
            "  Validation error:",
            type(exc).__name__,
            exc
        )
        return None

    finally:
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


# ============================================================
# HISTORY
# ============================================================

def history_keys(history):
    keys = set()

    if not isinstance(history, list):
        return keys

    for item in history:
        if not isinstance(item, dict):
            continue

        for field in (
            "sha256",
            "media_url",
            "status_url",
        ):
            value = item.get(field)

            if value:
                keys.add(
                    f"{field}:{value}"
                )

    return keys


def already_seen(candidate, keys):
    checks = [
        (
            "sha256",
            candidate.get("sha256")
        ),
        (
            "media_url",
            candidate.get("media_url")
        ),
        (
            "status_url",
            candidate.get("status_url")
        ),
    ]

    for field, value in checks:
        if value and f"{field}:{value}" in keys:
            return True

    return False


# ============================================================
# SCORING
# ============================================================

def score_candidate(candidate):
    text = (
        candidate.get("caption", "")
        + " "
        + candidate.get("account_display_name", "")
        + " "
        + candidate.get("account", "")
        + " "
        + candidate.get("hashtag", "")
    )

    relevance = animal_relevance(text)

    engagement = engagement_score(
        candidate.get("favourites", 0),
        candidate.get("reblogs", 0),
        candidate.get("replies", 0),
    )

    recency = recency_score(
        candidate.get("created_at")
    )

    quality = quality_score(
        candidate.get("width"),
        candidate.get("height"),
    )

    total = (
        relevance * 2
        + engagement
        + recency
        + quality
    )

    result = dict(candidate)

    result["animal_relevance"] = relevance
    result["engagement_score"] = engagement
    result["recency_score"] = recency
    result["quality_score"] = quality
    result["total_score"] = round(total, 3)

    return result


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("UTCutie Mastodon Video Discovery")
    print("=" * 70)

    print()
    print("Starting discovery...")

    candidates = discover_candidates()

    print()
    print(
        f"RAW VIDEO CANDIDATES: {len(candidates)}"
    )

    candidates = deduplicate_candidates(
        candidates
    )

    print(
        f"UNIQUE VIDEO CANDIDATES: {len(candidates)}"
    )

    save_json(
        CANDIDATES_FILE,
        candidates
    )

    print()
    print("Starting media validation...")

    validated = []

    for index, candidate in enumerate(
        candidates,
        start=1
    ):
        print(
            f"[{index}/{len(candidates)}]"
        )

        result = download_and_validate(
            candidate
        )

        if result is None:
            continue

        scored = score_candidate(result)

        validated.append(scored)

    print()
    print(
        f"VALIDATED VIDEOS: {len(validated)}"
    )

    save_json(
        VALIDATED_FILE,
        validated
    )

    history = load_json(
        HISTORY_FILE,
        []
    )

    if not isinstance(history, list):
        history = []

    seen_keys = history_keys(history)

    fresh = []

    for candidate in validated:
        if already_seen(
            candidate,
            seen_keys
        ):
            continue

        fresh.append(candidate)

    print(
        f"FRESH VIDEOS AFTER HISTORY FILTER: "
        f"{len(fresh)}"
    )

    # Deduplicate by actual downloaded file hash.
    hash_seen = set()
    unique_fresh = []

    for candidate in fresh:
        sha256 = candidate.get("sha256")

        if not sha256:
            continue

        if sha256 in hash_seen:
            continue

        hash_seen.add(sha256)
        unique_fresh.append(candidate)

    fresh = unique_fresh

    # Highest quality candidates first.
    fresh.sort(
        key=lambda item: (
            item.get("total_score", 0),
            item.get("animal_relevance", 0),
            item.get("engagement_score", 0),
            item.get("quality_score", 0),
        ),
        reverse=True,
    )

    selected = fresh[:MAX_SELECTED]

    print()
    print("=" * 70)
    print(
        f"SELECTED: {len(selected)}"
    )
    print("=" * 70)

    for index, candidate in enumerate(
        selected,
        start=1
    ):
        print()
        print(
            f"{index}. "
            f"score={candidate.get('total_score')} "
            f"duration={candidate.get('duration')}s "
            f"size={candidate.get('file_size_mb')}MB"
        )

        print(
            "   URL:",
            candidate.get("status_url")
        )

        print(
            "   Caption:",
            normalize_text(
                candidate.get("caption", "")
            )[:200]
        )

    save_json(
        SELECTED_FILE,
        selected
    )

    # Add selected items to persistent history.
    history_entries = list(history)

    for candidate in selected:
        history_entries.append(
            {
                "selected_at": now_iso(),
                "sha256": candidate.get("sha256"),
                "media_url": candidate.get("media_url"),
                "status_url": candidate.get("status_url"),
                "duration": candidate.get("duration"),
                "file_size": candidate.get("file_size"),
                "total_score": candidate.get("total_score"),
            }
        )

    save_json(
        HISTORY_FILE,
        history_entries
    )

    print()
    print("=" * 70)
    print("DISCOVERY COMPLETE")
    print("=" * 70)
    print(
        f"Raw candidates: {len(candidates)}"
    )
    print(
        f"Validated videos: {len(validated)}"
    )
    print(
        f"Fresh videos: {len(fresh)}"
    )
    print(
        f"Selected videos: {len(selected)}"
    )
    print(
        f"History entries: {len(history_entries)}"
    )


if __name__ == "__main__":
    main()
