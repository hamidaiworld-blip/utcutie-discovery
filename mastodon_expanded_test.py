import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests


# ============================================================
# UTCUTIE EXPANDED MASTODON DISCOVERY
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
MAX_DOWNLOAD_VALIDATION = 100
MAX_SELECTED = 20

MAX_VIDEOS_PER_ACCOUNT = 2
MAX_VIDEOS_PER_INSTANCE = 6

REQUEST_TIMEOUT = 25
DOWNLOAD_TIMEOUT = 60

HISTORY_FILE = Path("history.json")
OUTPUT_CANDIDATES = Path("mastodon_expanded_candidates.json")
OUTPUT_VALIDATED = Path("mastodon_expanded_validated.json")
OUTPUT_SELECTED = Path("mastodon_expanded_selected_candidates.json")

DOWNLOAD_DIR = Path("mastodon_expanded_downloads")


# ============================================================
# HTTP SESSION
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
# HELPERS
# ============================================================

def load_history():
    if not HISTORY_FILE.exists():
        return []

    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

        return []

    except Exception as exc:
        print(f"WARNING: Could not read history.json: {exc}")
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

    text = re.sub(r"<[^>]+>", "", text)

    text = html.unescape(text)

    # Remove URLs.
    text = re.sub(
        r"https?://\S+|www\.\S+",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Remove hashtags but keep the surrounding sentence.
    text = re.sub(
        r"(?<!\w)#[\w]+",
        "",
        text,
        flags=re.UNICODE,
    )

    cleaned_lines = []

    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()

        if line:
            cleaned_lines.append(line)

    text = "\n".join(cleaned_lines)

    # Remove excessive blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def truncate_caption(text, max_length=900):
    if len(text) <= max_length:
        return text

    shortened = text[:max_length]

    # Prefer ending at a sentence/word boundary.
    candidates = [
        shortened.rfind("\n"),
        shortened.rfind(". "),
        shortened.rfind(" "),
    ]

    cut = max(candidates)

    if cut >= 200:
        shortened = shortened[:cut]

    return shortened.rstrip()


def extract_status_text(status):
    return clean_caption(status.get("content", ""))


def parse_datetime(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except Exception:
        return None


def recency_score(created_at):
    dt = parse_datetime(created_at)

    if not dt:
        return 0.0

    now = datetime.now(timezone.utc)

    age_hours = max(
        0,
        (now - dt.astimezone(timezone.utc)).total_seconds() / 3600,
    )

    if age_hours <= 6:
        return 100.0

    if age_hours <= 24:
        return 85.0

    if age_hours <= 72:
        return 65.0

    if age_hours <= 168:
        return 40.0

    if age_hours <= 336:
        return 20.0

    return 5.0


def engagement_score(status):
    favourites = int(status.get("favourites_count") or 0)
    reblogs = int(status.get("reblogs_count") or 0)
    replies = int(status.get("replies_count") or 0)

    raw = (
        favourites * 1.0
        + reblogs * 2.5
        + replies * 0.75
    )

    if raw <= 0:
        return 0.0

    # Logarithmic scaling prevents giant accounts from dominating.
    import math

    return min(100.0, math.log10(raw + 1) * 22.0)


def quality_score(media):
    width = int(media.get("meta", {}).get("original", {}).get("width") or 0)
    height = int(media.get("meta", {}).get("original", {}).get("height") or 0)

    score = 0.0

    if width >= 1080 or height >= 1080:
        score += 45

    elif width >= 720 or height >= 720:
        score += 35

    elif width >= 480 or height >= 480:
        score += 20

    else:
        score += 5

    bitrate = (
        media.get("meta", {})
        .get("original", {})
        .get("bitrate")
    )

    if bitrate:
        try:
            bitrate = int(bitrate)

            if bitrate >= 2_000_000:
                score += 30

            elif bitrate >= 1_000_000:
                score += 20

            elif bitrate >= 500_000:
                score += 10

        except Exception:
            pass

    return min(100.0, score)


def animal_relevance_score(text):
    text = (text or "").lower()

    strong = [
        "cat",
        "kitten",
        "kitty",
        "dog",
        "puppy",
        "pup",
        "pet",
        "pets",
        "animal",
        "animals",
        "rabbit",
        "bunny",
        "hamster",
        "guinea pig",
        "bird",
        "parrot",
        "duck",
        "chicken",
        "goat",
        "horse",
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

    funny = [
        "funny",
        "lol",
        "haha",
        "hilarious",
        "adorable",
        "cute",
        "silly",
        "fails",
        "fail",
        "zoomies",
        "derp",
        "play",
        "playing",
        "sleeping",
        "sleepy",
        "rescue",
        "wholesome",
        "heartwarming",
    ]

    negative = [
        "kill",
        "killing",
        "dead animal",
        "injury",
        "injured",
        "blood",
        "gore",
        "violence",
        "abuse",
        "attack",
        "fighting",
        "fight",
        "nsfw",
    ]

    score = 0.0

    for word in strong:
        if word in text:
            score += 12

    for word in funny:
        if word in text:
            score += 7

    for word in negative:
        if word in text:
            score -= 30

    return max(0.0, min(100.0, score))


def caption_quality_score(text):
    if not text:
        return 0.0

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

    # Avoid captions consisting mostly of symbols.
    alphanumeric = sum(ch.isalnum() for ch in text)

    if alphanumeric >= 15:
        score += 15

    return min(100.0, score)


def media_is_video(media):
    if not isinstance(media, dict):
        return False

    media_type = str(media.get("type", "")).lower()

    if media_type == "video":
        return True

    if media_type == "gifv":
        return True

    url = str(media.get("url") or "").lower()

    video_extensions = (
        ".mp4",
        ".webm",
        ".mov",
        ".m4v",
        ".mkv",
    )

    return url.split("?")[0].endswith(video_extensions)


def get_media_url(media):
    return (
        media.get("url")
        or media.get("remote_url")
        or media.get("preview_url")
    )


def account_key(status):
    account = status.get("account") or {}

    acct = (
        account.get("acct")
        or account.get("url")
        or account.get("id")
        or "unknown"
    )

    return str(acct).lower()


def status_url(status, instance):
    url = status.get("url")

    if url:
        return url

    account = status.get("account") or {}

    account_url = account.get("url")

    status_id = status.get("id")

    if account_url and status_id:
        return f"{account_url}/{status_id}"

    return f"https://{instance}/@unknown/{status_id}"


def canonical_media_key(url):
    if not url:
        return ""

    return url.split("?")[0].rstrip("/")


def safe_filename(value):
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", value)

    return value[:120] or "video.mp4"


# ============================================================
# MASTODON API
# ============================================================

def api_get(instance, path, params=None):
    url = f"https://{instance}{path}"

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

        tags = []

        if isinstance(data, list):
            for item in data:
                name = item.get("name")

                if name:
                    tags.append(str(name).lower())

        return tags[:MAX_TRENDING_TAGS_PER_INSTANCE]

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
            f"/api/v1/timelines/tag/{quote(tag, safe='')}",
            {
                "limit": MAX_STATUS_PER_ENDPOINT,
                "only_media": "true",
            },
        )

        return data if isinstance(data, list) else []

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

        return data if isinstance(data, list) else []

    except Exception as exc:
        print(
            f"  PUBLIC MEDIA FAILED: "
            f"{instance} | {exc}"
        )

        return []


# ============================================================
# CANDIDATE EXTRACTION
# ============================================================

def extract_candidates(statuses, instance, discovery_source):
    candidates = []

    for status in statuses:
        if not isinstance(status, dict):
            continue

        if status.get("sensitive"):
            continue

        visibility = status.get("visibility")

        if visibility not in (None, "public", "unlisted"):
            continue

        media_attachments = status.get("media_attachments") or []

        for media in media_attachments:
            if not media_is_video(media):
                continue

            media_url = get_media_url(media)

            if not media_url:
                continue

            caption = extract_status_text(status)

            relevance = animal_relevance_score(caption)

            # Do not throw away weakly-captioned animal videos here.
            # Some excellent videos have almost no caption.
            if relevance < 5:
                # Hashtag information can still establish relevance.
                tags = status.get("tags") or []

                tag_text = " ".join(
                    str(t.get("name", ""))
                    for t in tags
                )

                relevance = animal_relevance_score(
                    f"{caption} {tag_text}"
                )

            candidate = {
                "source": "mastodon",
                "instance": instance,
                "discovery_source": discovery_source,
                "status_id": str(status.get("id") or ""),
                "status_url": status_url(status, instance),
                "created_at": status.get("created_at"),
                "account": account_key(status),
                "account_name": (
                    status.get("account", {}).get("display_name")
                    or status.get("account", {}).get("username")
                    or ""
                ),
                "media_url": media_url,
                "media_type": media.get("type"),
                "caption": caption,
                "caption_length": len(caption),
                "favourites_count": int(
                    status.get("favourites_count") or 0
                ),
                "reblogs_count": int(
                    status.get("reblogs_count") or 0
                ),
                "replies_count": int(
                    status.get("replies_count") or 0
                ),
                "animal_relevance": relevance,
                "engagement": engagement_score(status),
                "recency": recency_score(
                    status.get("created_at")
                ),
                "quality": quality_score(media),
                "caption_quality": caption_quality_score(
                    caption
                ),
            }

            candidate["pre_validation_score"] = (
                candidate["animal_relevance"] * 2.0
                + candidate["engagement"]
                + candidate["recency"]
                + candidate["quality"]
                + candidate["caption_quality"]
            )

            candidates.append(candidate)

    return candidates


# ============================================================
# VIDEO VALIDATION
# ============================================================

def download_video(url, output_path):
    try:
        with SESSION.get(
            url,
            stream=True,
            timeout=DOWNLOAD_TIMEOUT,
        ) as response:
            response.raise_for_status()

            content_type = (
                response.headers.get("content-type") or ""
            ).lower()

            if (
                "video" not in content_type
                and "octet-stream" not in content_type
            ):
                return False, "not_video_content_type"

            content_length = response.headers.get(
                "content-length"
            )

            if content_length:
                try:
                    if int(content_length) > MAX_FILE_SIZE:
                        return False, "too_large"
                except Exception:
                    pass

            total = 0

            with output_path.open("wb") as f:
                for chunk in response.iter_content(
                    chunk_size=1024 * 256
                ):
                    if not chunk:
                        continue

                    total += len(chunk)

                    if total > MAX_FILE_SIZE:
                        return False, "too_large"

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

        data = json.loads(result.stdout)

        streams = data.get("streams") or []

        if not streams:
            return None

        stream = streams[0]

        duration = float(stream.get("duration") or 0)

        if duration <= 0:
            return None

        return {
            "duration": duration,
            "codec": stream.get("codec_name"),
            "width": int(stream.get("width") or 0),
            "height": int(stream.get("height") or 0),
        }

    except Exception:
        return None


def validate_candidate(candidate, index):
    media_url = candidate["media_url"]

    filename = safe_filename(
        f"{index}_{Path(media_url.split('?')[0]).name}"
    )

    if not filename.lower().endswith(
        (".mp4", ".webm", ".mov", ".m4v", ".mkv")
    ):
        filename += ".mp4"

    output_path = DOWNLOAD_DIR / filename

    ok, reason = download_video(
        media_url,
        output_path,
    )

    if not ok:
        candidate["validation_error"] = reason
        return None

    size = output_path.stat().st_size

    if size <= 0 or size > MAX_FILE_SIZE:
        return None

    probe = ffprobe_video(output_path)

    if not probe:
        return None

    duration = probe["duration"]

    if duration < MIN_DURATION:
        return None

    if duration > MAX_DURATION:
        return None

    sha256 = hashlib.sha256()

    with output_path.open("rb") as f:
        for chunk in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            sha256.update(chunk)

    candidate["duration"] = round(duration, 3)
    candidate["file_size"] = size
    candidate["sha256"] = sha256.hexdigest()
    candidate["codec"] = probe["codec"]
    candidate["width"] = probe["width"]
    candidate["height"] = probe["height"]

    # Refine quality using actual video dimensions.
    actual_quality = 0

    if max(probe["width"], probe["height"]) >= 1080:
        actual_quality = 100

    elif max(probe["width"], probe["height"]) >= 720:
        actual_quality = 80

    elif max(probe["width"], probe["height"]) >= 480:
        actual_quality = 55

    else:
        actual_quality = 25

    candidate["actual_quality"] = actual_quality

    candidate["score"] = (
        candidate["animal_relevance"] * 2.5
        + candidate["engagement"] * 1.15
        + candidate["recency"]
        + actual_quality
        + candidate["caption_quality"] * 0.5
    )

    return candidate


# ============================================================
# MAIN DISCOVERY
# ============================================================

def main():
    print()
    print("=" * 70)
    print("UTCUTIE EXPANDED MASTODON DISCOVERY")
    print("=" * 70)
    print()

    history = load_history()
    history_key_set = history_keys(history)

    print(
        f"Publication history entries: {len(history)}"
    )
    print()

    if DOWNLOAD_DIR.exists():
        shutil.rmtree(DOWNLOAD_DIR)

    DOWNLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # 1. Discover trending tags and combine with fixed tags.
    # --------------------------------------------------------

    instance_tags = {}

    all_trending_tags = set()

    for instance in INSTANCES:
        print(f"TRENDING TAGS: {instance}")

        tags = get_trending_tags(instance)

        instance_tags[instance] = tags

        print(
            f"  Trending tags discovered: {len(tags)}"
        )

        for tag in tags:
            all_trending_tags.add(tag)

    print()
    print(
        f"Unique trending tags across instances: "
        f"{len(all_trending_tags)}"
    )
    print()

    # --------------------------------------------------------
    # 2. Build tag pool.
    # --------------------------------------------------------

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
        "dog",
    )

    trending_animal_tags = sorted(
        tag
        for tag in all_trending_tags
        if any(word in tag.lower() for word in animal_words)
    )

    print(
        f"Animal-related trending tags selected: "
        f"{len(trending_animal_tags)}"
    )

    if trending_animal_tags:
        print(
            "Trending animal tags:",
            ", ".join(
                trending_animal_tags[:100]
            ),
        )

    print()

    # --------------------------------------------------------
    # 3. Collect statuses.
    # --------------------------------------------------------

    raw_statuses = []

    seen_status_ids = set()

    for instance in INSTANCES:
        print()
        print("=" * 60)
        print(f"INSTANCE: {instance}")
        print("=" * 60)

        tags = list(FIXED_TAGS)

        tags.extend(instance_tags.get(instance, []))

        tags.extend(trending_animal_tags)

        # Preserve order but deduplicate.
        unique_tags = []

        for tag in tags:
            tag = str(tag).strip().lower()

            if not tag:
                continue

            if tag not in unique_tags:
                unique_tags.append(tag)

        for tag in unique_tags:
            if len(raw_statuses) >= MAX_RAW_CANDIDATES:
                break

            print(f"TAG: #{tag}")

            statuses = get_tag_statuses(
                instance,
                tag,
            )

            print(
                f"  statuses: {len(statuses)}"
            )

            for status in statuses:
                status_id = str(
                    status.get("id") or ""
                )

                if not status_id:
                    continue

                key = (
                    instance,
                    status_id,
                )

                if key in seen_status_ids:
                    continue

                seen_status_ids.add(key)
                raw_statuses.append(
                    (
                        status,
                        instance,
                        f"tag:{tag}",
                    )
                )

        # Public media timeline gives us videos that aren't
        # necessarily discoverable through our fixed tags.
        if len(raw_statuses) < MAX_RAW_CANDIDATES:
            print("PUBLIC MEDIA TIMELINE")

            statuses = get_public_media_statuses(
                instance
            )

            print(
                f"  statuses: {len(statuses)}"
            )

            for status in statuses:
                status_id = str(
                    status.get("id") or ""
                )

                if not status_id:
                    continue

                key = (
                    instance,
                    status_id,
                )

                if key in seen_status_ids:
                    continue

                seen_status_ids.add(key)

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
    # 4. Convert statuses to video candidates.
    # --------------------------------------------------------

    candidates = []

    for status, instance, discovery_source in raw_statuses:
        extracted = extract_candidates(
            [status],
            instance,
            discovery_source,
        )

        candidates.extend(extracted)

    print(
        f"Raw video candidates: {len(candidates)}"
    )

    # Deduplicate by media URL.
    unique_candidates = {}

    for candidate in candidates:
        key = canonical_media_key(
            candidate["media_url"]
        )

        if not key:
            continue

        existing = unique_candidates.get(key)

        if (
            existing is None
            or candidate["pre_validation_score"]
            > existing["pre_validation_score"]
        ):
            unique_candidates[key] = candidate

    candidates = list(
        unique_candidates.values()
    )

    candidates.sort(
        key=lambda x: x["pre_validation_score"],
        reverse=True,
    )

    candidates = candidates[
        :MAX_DOWNLOAD_VALIDATION
    ]

    print(
        f"Candidates selected for actual download "
        f"validation: {len(candidates)}"
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
    # 5. Validate actual video files.
    # --------------------------------------------------------

    validated = []

    for index, candidate in enumerate(
        candidates,
        start=1,
    ):
        print(
            f"[{index}/{len(candidates)}] "
            f"VALIDATE {candidate['media_url']}"
        )

        result = validate_candidate(
            candidate,
            index,
        )

        if result:
            validated.append(result)

            print(
                f"  VALID: "
                f"{result['duration']}s "
                f"{result['file_size']} bytes "
                f"score={result['score']:.2f}"
            )

        else:
            print("  INVALID")

    print()
    print(
        f"Validated videos: {len(validated)}"
    )

    # --------------------------------------------------------
    # 6. Deduplicate by SHA-256.
    # --------------------------------------------------------

    unique_by_hash = {}

    for candidate in validated:
        sha = candidate.get("sha256")

        if not sha:
            continue

        existing = unique_by_hash.get(sha)

        if (
            existing is None
            or candidate["score"]
            > existing["score"]
        ):
            unique_by_hash[sha] = candidate

    validated = list(
        unique_by_hash.values()
    )

    print(
        f"Unique validated videos: "
        f"{len(validated)}"
    )

    # --------------------------------------------------------
    # 7. History filter.
    # --------------------------------------------------------

    fresh = []

    for candidate in validated:
        identifiers = {
            candidate.get("media_url"),
            candidate.get("status_url"),
            candidate.get("sha256"),
        }

        if identifiers & history_key_set:
            continue

        fresh.append(candidate)

    print(
        f"Fresh videos after history: "
        f"{len(fresh)}"
    )

    # --------------------------------------------------------
    # 8. Global ranking.
    # --------------------------------------------------------

    fresh.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    # --------------------------------------------------------
    # 9. Diversity-aware selection.
    # --------------------------------------------------------

    selected = []

    account_counts = {}
    instance_counts = {}

    # First pass: enforce diversity preferences.
    for candidate in fresh:
        account = candidate["account"]
        instance = candidate["instance"]

        if account_counts.get(account, 0) >= MAX_VIDEOS_PER_ACCOUNT:
            continue

        if instance_counts.get(instance, 0) >= MAX_VIDEOS_PER_INSTANCE:
            continue

        selected.append(candidate)

        account_counts[account] = (
            account_counts.get(account, 0) + 1
        )

        instance_counts[instance] = (
            instance_counts.get(instance, 0) + 1
        )

        if len(selected) >= MAX_SELECTED:
            break

    # Second pass: fill remaining positions.
    if len(selected) < MAX_SELECTED:
        selected_hashes = {
            item["sha256"]
            for item in selected
        }

        for candidate in fresh:
            if candidate["sha256"] in selected_hashes:
                continue

            selected.append(candidate)

            if len(selected) >= MAX_SELECTED:
                break

    # --------------------------------------------------------
    # 10. Prepare Telegram-safe captions.
    # --------------------------------------------------------

    for candidate in selected:
        caption = truncate_caption(
            candidate.get("caption", ""),
            900,
        )

        candidate["telegram_caption"] = caption

    # --------------------------------------------------------
    # 11. Output.
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

    print()
    print("=" * 70)
    print("UTCUTIE EXPANDED MASTODON DISCOVERY COMPLETE")
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
        f"Raw video candidates: "
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
            f"score={candidate['score']:.2f} | "
            f"{candidate['instance']} | "
            f"{candidate['status_url']}"
        )

    print()
    print(
        f"Raw results: {OUTPUT_CANDIDATES}"
    )

    print(
        f"Validated results: {OUTPUT_VALIDATED}"
    )

    print(
        f"Selected results: {OUTPUT_SELECTED}"
    )

    print()
    print(
        "IMPORTANT: history.json was NOT modified."
    )

    # Cleanup downloaded validation files.
    shutil.rmtree(
        DOWNLOAD_DIR,
        ignore_errors=True,
    )


if __name__ == "__main__":
    main()
