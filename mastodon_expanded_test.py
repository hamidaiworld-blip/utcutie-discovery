import hashlib
import html
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests


# ============================================================
# UTCutie Mastodon / Fediverse Discovery
# ============================================================

MAX_VIDEOS = 20

MIN_DURATION = 15
MAX_DURATION = 180

MAX_FILE_SIZE = 48 * 1024 * 1024

PREFERRED_DAYS = 14
FRESH_DAYS = 30
FALLBACK_DAYS = 90

MIN_ANIMAL_RELEVANCE = 50

MAX_VIDEOS_PER_ACCOUNT = 2
MAX_VIDEOS_PER_INSTANCE = 8

REQUEST_TIMEOUT = 25

HISTORY_FILE = Path("history.json")

OUTPUT_CANDIDATES = Path("mastodon_expanded_candidates.json")
OUTPUT_VALIDATED = Path("mastodon_expanded_validated.json")
OUTPUT_SELECTED = Path("mastodon_expanded_selected_candidates.json")


INSTANCES = [
    "mastodon.social",
    "mastodon.online",
    "mastodon.world",
    "mstdn.party",
    "mastodon.cloud",
    "mastodon.scot",
    "mastodon.ie",
    "mastodon.xyz",
    "mastodon.gamedev.place",
]


TAGS = [
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
    "silentsunday",
    "worldanimalday",
]


ANIMAL_TERMS = {
    "cat",
    "cats",
    "kitten",
    "kittens",
    "kitty",
    "kitties",
    "dog",
    "dogs",
    "puppy",
    "puppies",
    "pup",
    "pet",
    "pets",
    "animal",
    "animals",
    "bird",
    "birds",
    "parrot",
    "parrots",
    "parakeet",
    "cockatiel",
    "duck",
    "ducks",
    "goose",
    "geese",
    "chicken",
    "chickens",
    "rabbit",
    "rabbits",
    "bunny",
    "bunnies",
    "hamster",
    "hamsters",
    "guinea pig",
    "guinea pigs",
    "mouse",
    "mice",
    "rat",
    "rats",
    "horse",
    "horses",
    "pony",
    "ponies",
    "cow",
    "cows",
    "calf",
    "sheep",
    "goat",
    "goats",
    "pig",
    "pigs",
    "foal",
    "deer",
    "fox",
    "wolf",
    "wolves",
    "bear",
    "panda",
    "monkey",
    "monkeys",
    "otter",
    "seal",
    "dolphin",
    "turtle",
    "turtles",
    "tortoise",
    "snake",
    "snakes",
    "lizard",
    "frog",
    "frogs",
    "hedgehog",
    "hedgehogs",
    "chihuahua",
    "labrador",
    "retriever",
    "husky",
    "corgi",
    "golden retriever",
    "poodle",
}


PET_CONTEXT_TERMS = {
    "pet",
    "pets",
    "petlife",
    "petlover",
    "petlove",
    "petcommunity",
    "fur",
    "furry",
    "fluffy",
    "paw",
    "paws",
    "tail",
    "whiskers",
    "zoomies",
    "walk",
    "walking",
    "play",
    "playing",
    "playtime",
    "sleeping",
    "sleepy",
    "cuddle",
    "cuddling",
    "hug",
    "hugging",
    "kiss",
    "kissing",
    "belly rub",
    "bellyrub",
    "treat",
    "toy",
    "toys",
}


ENTERTAINMENT_TERMS = {
    "funny",
    "hilarious",
    "lol",
    "lmao",
    "laugh",
    "laughing",
    "cute",
    "adorable",
    "aww",
    "amazing",
    "silly",
    "goofy",
    "fun",
    "funniest",
    "comedy",
    "meme",
    "memes",
    "fails",
    "fail",
    "reaction",
    "reacts",
    "unexpected",
    "watch",
    "watching",
    "zoomies",
    "chaos",
    "derp",
    "wholesome",
    "sweet",
    "heartwarming",
    "wholesome",
    "playful",
    "play",
    "playing",
}


HARD_NEGATIVE_TERMS = {
    "politics",
    "political",
    "election",
    "government",
    "senate",
    "congress",
    "president",
    "minister",
    "war",
    "military",
    "army",
    "weapon",
    "weapons",
    "soldier",
    "soldiers",
    "armed",
    "battle",
    "conflict",
    "bomb",
    "bombing",
    "missile",
    "terror",
    "terrorism",
    "religion",
    "religious",
    "islam",
    "christian",
    "christianity",
    "campaign",
    "activism",
    "activist",
    "protest",
    "protests",
    "fundraiser",
    "fundraising",
    "donate",
    "donation",
    "donations",
    "petition",
    "ngo",
    "organization",
    "awareness",
    "climate",
    "climatechange",
    "environmental",
    "slaughter",
    "factory farming",
    "farming policy",
    "research",
    "study",
    "university",
    "academic",
    "lecture",
    "conference",
    "sports",
    "football",
    "soccer",
    "basketball",
    "baseball",
    "hockey",
    "tennis",
    "formula 1",
    "f1",
    "business",
    "marketing",
    "finance",
    "crypto",
    "stock",
    "stocks",
    "investment",
    "job",
    "jobs",
    "career",
    "anxiety",
    "depression",
    "therapy",
    "mental health",
    "infographic",
    "diagram",
    "chart",
    "tutorial",
    "course",
    "webinar",
    "podcast",
}


PROMOTIONAL_TERMS = {
    "buy now",
    "shop now",
    "order now",
    "discount",
    "sale",
    "offer",
    "promo",
    "promotion",
    "sponsor",
    "sponsored",
    "affiliate",
    "affiliate link",
    "link in bio",
    "wishlist",
    "subscribe",
    "follow us",
    "check out my",
    "visit our",
    "visit my",
    "donate",
    "donation",
    "fundraiser",
    "fundraising",
}


DISCOVERY_TAG_BONUS = {
    "cats": 10,
    "cat": 10,
    "kittens": 10,
    "dogs": 10,
    "dog": 10,
    "puppy": 10,
    "pets": 10,
    "animals": 8,
    "aww": 12,
    "cuteanimals": 12,
    "funnyanimals": 15,
    "petsofthefediverse": 12,
    "caturday": 12,
    "dogsofthefediverse": 12,
    "catsofthefediverse": 12,
    "cutepets": 15,
    "funnydogs": 15,
    "funnycats": 15,
    "wholesome": 8,
    "adorable": 8,
}


# ============================================================
# Generic helpers
# ============================================================

def normalize_text(value):
    if not value:
        return ""

    value = html.unescape(str(value))
    value = re.sub(r"\s+", " ", value)
    return value.strip().lower()


def clean_caption(raw_html):
    """
    Convert Mastodon HTML into clean plain text.

    Important:
    Caption cleaning must NEVER be allowed to break publication.
    """

    if not raw_html:
        return ""

    text = str(raw_html)

    text = re.sub(
        r"<(script|style)[^>]*>.*?</\1>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    text = re.sub(
        r"</?(p|div|br|li|blockquote|h[1-6])[^>]*>",
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

    # Remove hashtags while preserving the surrounding text.
    text = re.sub(
        r"(?<!\w)#[\w\u0080-\uffff]+",
        "",
        text,
        flags=re.UNICODE,
    )

    # Remove obvious phone numbers.
    text = re.sub(
        r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)",
        "",
        text,
    )

    # Remove obvious promotional fragments.
    promotional_patterns = [
        r"\bwishlist\b.*",
        r"\blink\s+in\s+bio\b.*",
        r"\bsubscribe\b.*",
        r"\bfollow\s+us\b.*",
        r"\bfollow\s+me\b.*",
    ]

    for pattern in promotional_patterns:
        text = re.sub(
            pattern,
            "",
            text,
            flags=re.IGNORECASE,
        )

    lines = []

    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line)
        line = line.strip()

        if not line:
            continue

        lines.append(line)

    # Remove duplicated consecutive lines.
    cleaned = []

    for line in lines:
        if not cleaned or line != cleaned[-1]:
            cleaned.append(line)

    return "\n".join(cleaned).strip()


def telegram_caption(source_caption):
    """
    Keep the source caption reasonably short so @utcutie can
    safely be appended later.
    """

    text = clean_caption(source_caption)

    if not text:
        return ""

    max_source_chars = 900

    if len(text) <= max_source_chars:
        return text

    truncated = text[:max_source_chars]

    # Prefer a natural line boundary.
    newline_pos = truncated.rfind("\n")

    if newline_pos >= 400:
        truncated = truncated[:newline_pos]
    else:
        space_pos = truncated.rfind(" ")

        if space_pos >= 400:
            truncated = truncated[:space_pos]

    return truncated.rstrip(" .,-:;") + "…"


def normalize_status_url(url):
    """
    Canonicalize Mastodon status URLs enough to deduplicate
    cross-instance mirrors.
    """

    if not url:
        return ""

    url = url.strip()

    parsed = urlparse(url)

    if not parsed.scheme or not parsed.netloc:
        return url

    path = parsed.path.rstrip("/")

    # Remove common trailing activity fragments.
    path = re.sub(r"/activity$", "", path)

    return f"{parsed.scheme}://{parsed.netloc}{path}"


def sha256_file(path):
    digest = hashlib.sha256()

    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def run_ffprobe(path):
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type,duration,width,height",
        "-of",
        "json",
        str(path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=20,
    )

    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
    except Exception:
        return None

    streams = data.get("streams") or []

    if not streams:
        return None

    stream = streams[0]

    if stream.get("codec_type") != "video":
        return None

    try:
        duration = float(stream.get("duration") or 0)
    except Exception:
        duration = 0

    if duration <= 0:
        return None

    return {
        "duration": duration,
        "width": stream.get("width"),
        "height": stream.get("height"),
    }


# ============================================================
# Mastodon API
# ============================================================

def mastodon_get(instance, endpoint, params):
    url = f"https://{instance}{endpoint}"

    try:
        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": "UTCutieDiscovery/1.0",
                "Accept": "application/json",
            },
        )
    except Exception:
        return []

    if response.status_code != 200:
        return []

    try:
        return response.json()
    except Exception:
        return []


def fetch_hashtag(instance, tag, limit=40):
    return mastodon_get(
        instance,
        f"/api/v1/timelines/tag/{tag}",
        {
            "limit": limit,
            "local": "false",
        },
    )


# ============================================================
# Candidate extraction
# ============================================================

def extract_media_candidates(status, instance, tag):
    media_attachments = status.get("media_attachments") or []

    if not media_attachments:
        return []

    status_url = status.get("url") or ""

    account = status.get("account") or {}

    account_name = (
        account.get("acct")
        or account.get("username")
        or ""
    )

    created_at = status.get("created_at") or ""

    caption_source = (
        status.get("content")
        or status.get("spoiler_text")
        or ""
    )

    caption = clean_caption(caption_source)

    tags = []

    for item in status.get("tags") or []:
        name = item.get("name")

        if name:
            tags.append(str(name).lower())

    results = []

    for media in media_attachments:
        media_type = media.get("type")

        if media_type != "video":
            continue

        media_url = (
            media.get("url")
            or media.get("remote_url")
            or ""
        )

        preview_url = media.get("preview_url") or ""

        if not media_url:
            continue

        results.append(
            {
                "instance": instance,
                "discovery_tag": tag,
                "status_id": str(status.get("id") or ""),
                "status_url": status_url,
                "canonical_status_url": normalize_status_url(status_url),
                "account": account_name,
                "created_at": created_at,
                "caption": caption,
                "caption_raw": caption_source,
                "tags": tags,
                "media_url": media_url,
                "preview_url": preview_url,
                "media_type": media_type,
                "favourites": int(
                    status.get("favourites_count") or 0
                ),
                "reblogs": int(
                    status.get("reblogs_count") or 0
                ),
                "replies": int(
                    status.get("replies_count") or 0
                ),
            }
        )

    return results


# ============================================================
# Content analysis
# ============================================================

def word_hits(text, terms):
    normalized = normalize_text(text)

    hits = []

    for term in terms:
        term_normalized = normalize_text(term)

        if not term_normalized:
            continue

        pattern = r"(?<!\w)" + re.escape(term_normalized) + r"(?!\w)"

        if re.search(pattern, normalized, flags=re.IGNORECASE):
            hits.append(term)

    return hits


def content_analysis(candidate):
    caption = normalize_text(
        candidate.get("caption") or ""
    )

    tags = candidate.get("tags") or []

    tag_text = " ".join(
        normalize_text(tag)
        for tag in tags
    )

    combined = f"{caption} {tag_text}".strip()

    animal_hits = word_hits(
        combined,
        ANIMAL_TERMS,
    )

    pet_hits = word_hits(
        combined,
        PET_CONTEXT_TERMS,
    )

    entertainment_hits = word_hits(
        combined,
        ENTERTAINMENT_TERMS,
    )

    negative_hits = word_hits(
        combined,
        HARD_NEGATIVE_TERMS,
    )

    promotional_hits = word_hits(
        combined,
        PROMOTIONAL_TERMS,
    )

    discovery_bonus = 0

    for tag in tags:
        discovery_bonus += DISCOVERY_TAG_BONUS.get(
            str(tag).lower(),
            0,
        )

    animal_score = 0

    if animal_hits:
        animal_score += min(70, 25 * len(animal_hits))

    if pet_hits:
        animal_score += min(30, 10 * len(pet_hits))

    animal_score += min(20, discovery_bonus)

    animal_score = min(100, animal_score)

    entertainment_score = 0

    if entertainment_hits:
        entertainment_score += min(
            60,
            15 * len(entertainment_hits),
        )

    if animal_hits and entertainment_hits:
        entertainment_score += 25

    if len(caption.strip()) >= 20:
        entertainment_score += 10

    entertainment_score = min(
        100,
        entertainment_score,
    )

    return {
        "animal_hits": animal_hits,
        "pet_hits": pet_hits,
        "entertainment_hits": entertainment_hits,
        "negative_hits": negative_hits,
        "promotional_hits": promotional_hits,
        "animal_relevance": animal_score,
        "entertainment_score": entertainment_score,
    }


def is_hard_reject(analysis):
    animal_relevance = analysis["animal_relevance"]

    if animal_relevance < MIN_ANIMAL_RELEVANCE:
        return True, "animal relevance below hard threshold"

    if not analysis["animal_hits"] and not analysis["pet_hits"]:
        return True, "no explicit animal evidence"

    # Strongly non-entertainment content should not enter
    # the publishing pool even when an animal is mentioned.
    negative_hits = set(analysis["negative_hits"])

    strong_non_entertainment = {
        "politics",
        "political",
        "election",
        "government",
        "president",
        "war",
        "military",
        "army",
        "weapon",
        "weapons",
        "soldier",
        "soldiers",
        "battle",
        "terrorism",
        "terror",
        "sports",
        "football",
        "soccer",
        "basketball",
        "tennis",
        "campaign",
        "fundraising",
        "donation",
        "religion",
        "religious",
        "islam",
        "christianity",
        "anxiety",
        "depression",
        "therapy",
        "mental health",
        "infographic",
        "diagram",
        "chart",
        "tutorial",
        "course",
        "webinar",
    }

    if negative_hits.intersection(strong_non_entertainment):
        return True, "non-entertainment category detected"

    # Excessive promotional content is not suitable for
    # the entertainment feed.
    if len(analysis["promotional_hits"]) >= 2:
        return True, "too promotional"

    return False, ""


# ============================================================
# Scoring
# ============================================================

def engagement_score(candidate):
    favourites = candidate.get("favourites", 0)
    reblogs = candidate.get("reblogs", 0)
    replies = candidate.get("replies", 0)

    raw = (
        favourites
        + reblogs * 3
        + replies * 2
    )

    if raw <= 0:
        return 0

    # Smooth logarithmic score.
    import math

    score = math.log10(raw + 1) * 18

    return min(100, round(score, 2))


def recency_days(candidate):
    created_at = candidate.get("created_at")

    if not created_at:
        return 9999

    try:
        value = created_at.replace("Z", "+00:00")

        created = datetime.fromisoformat(value)

        if created.tzinfo is None:
            created = created.replace(
                tzinfo=timezone.utc,
            )

        now = datetime.now(timezone.utc)

        seconds = (
            now - created.astimezone(timezone.utc)
        ).total_seconds()

        return max(0, seconds / 86400)

    except Exception:
        return 9999


def recency_score(days):
    if days <= 1:
        return 100

    if days <= 3:
        return 95

    if days <= 7:
        return 90

    if days <= 14:
        return 82

    if days <= 30:
        return 68

    if days <= 60:
        return 45

    if days <= 90:
        return 25

    return 0


def quality_score(candidate, media_info):
    score = 0

    width = media_info.get("width") or 0
    height = media_info.get("height") or 0
    duration = media_info.get("duration") or 0

    if width >= 1080 or height >= 1080:
        score += 35
    elif width >= 720 or height >= 720:
        score += 25
    elif width >= 480 or height >= 480:
        score += 15

    if duration >= 20:
        score += 10

    if duration <= 120:
        score += 10

    if candidate.get("preview_url"):
        score += 5

    return min(100, score)


def caption_quality_score(candidate, analysis):
    caption = (
        candidate.get("caption")
        or ""
    ).strip()

    score = 0

    if caption:
        score += 25

    if 20 <= len(caption) <= 300:
        score += 25
    elif len(caption) > 300:
        score += 10

    if analysis["entertainment_hits"]:
        score += 25

    if analysis["promotional_hits"]:
        score -= 25

    if analysis["negative_hits"]:
        score -= 10

    return max(0, min(100, score))


def score_candidate(candidate, analysis, media_info):
    days = recency_days(candidate)

    engagement = engagement_score(candidate)

    recency = recency_score(days)

    quality = quality_score(
        candidate,
        media_info,
    )

    caption_quality = caption_quality_score(
        candidate,
        analysis,
    )

    animal_relevance = analysis[
        "animal_relevance"
    ]

    # Animal relevance is deliberately weighted heavily.
    total = (
        animal_relevance * 2.5
        + engagement * 1.0
        + recency * 1.25
        + quality * 0.75
        + caption_quality * 0.5
    )

    candidate["animal_relevance"] = animal_relevance
    candidate["engagement_score"] = engagement
    candidate["recency_days"] = round(days, 2)
    candidate["recency_score"] = recency
    candidate["quality_score"] = quality
    candidate["caption_quality_score"] = caption_quality
    candidate["total_score"] = round(total, 2)

    candidate["analysis"] = analysis
    candidate["media_info"] = media_info

    return candidate


# ============================================================
# Media validation
# ============================================================

def validate_media(candidate, temp_dir):
    media_url = candidate.get("media_url")

    if not media_url:
        return None

    suffix = ".mp4"

    output_path = (
        Path(temp_dir)
        / f"{hashlib.sha1(media_url.encode()).hexdigest()}{suffix}"
    )

    try:
        with requests.get(
            media_url,
            stream=True,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": "UTCutieDiscovery/1.0",
            },
        ) as response:

            if response.status_code != 200:
                return None

            content_type = (
                response.headers.get(
                    "content-type",
                    "",
                )
                .lower()
            )

            if (
                "video" not in content_type
                and "octet-stream" not in content_type
            ):
                return None

            content_length = response.headers.get(
                "content-length"
            )

            if content_length:
                try:
                    if int(content_length) > MAX_FILE_SIZE:
                        return None
                except Exception:
                    pass

            total = 0

            with open(output_path, "wb") as handle:
                for chunk in response.iter_content(
                    chunk_size=1024 * 256
                ):
                    if not chunk:
                        continue

                    total += len(chunk)

                    if total > MAX_FILE_SIZE:
                        return None

                    handle.write(chunk)

        info = run_ffprobe(output_path)

        if not info:
            return None

        duration = info["duration"]

        if duration < MIN_DURATION:
            return None

        if duration > MAX_DURATION:
            return None

        digest = sha256_file(output_path)

        candidate["duration"] = round(
            duration,
            3,
        )

        candidate["file_size"] = output_path.stat().st_size

        candidate["sha256"] = digest

        candidate["media_info"] = info

        return candidate

    except Exception:
        return None
    finally:
        try:
            if output_path.exists():
                output_path.unlink()
        except Exception:
            pass


# ============================================================
# History
# ============================================================

def load_history():
    if not HISTORY_FILE.exists():
        return []

    try:
        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8",
        ) as handle:
            data = json.load(handle)

        if isinstance(data, list):
            return data

        return []

    except Exception:
        return []


def history_keys(history):
    keys = set()

    for item in history:
        if not isinstance(item, dict):
            continue

        for key in (
            "status_url",
            "canonical_status_url",
            "media_url",
            "sha256",
        ):
            value = item.get(key)

            if value:
                keys.add(str(value))

    return keys


def is_in_history(candidate, keys):
    candidates = {
        candidate.get("status_url"),
        candidate.get("canonical_status_url"),
        candidate.get("media_url"),
        candidate.get("sha256"),
    }

    candidates.discard(None)
    candidates.discard("")

    return bool(candidates.intersection(keys))


# ============================================================
# Canonical deduplication
# ============================================================

def deduplicate_canonical(candidates):
    result = []

    seen_statuses = set()
    seen_media = set()
    seen_hashes = set()

    for candidate in sorted(
        candidates,
        key=lambda item: item.get(
            "total_score",
            0,
        ),
        reverse=True,
    ):

        canonical_status = (
            candidate.get(
                "canonical_status_url"
            )
            or normalize_status_url(
                candidate.get("status_url")
            )
        )

        media_url = candidate.get("media_url")
        digest = candidate.get("sha256")

        if (
            canonical_status
            and canonical_status in seen_statuses
        ):
            continue

        if media_url and media_url in seen_media:
            continue

        if digest and digest in seen_hashes:
            continue

        if canonical_status:
            seen_statuses.add(
                canonical_status
            )

        if media_url:
            seen_media.add(media_url)

        if digest:
            seen_hashes.add(digest)

        result.append(candidate)

    return result


# ============================================================
# Diversity selection
# ============================================================

def select_with_diversity(candidates, max_items=MAX_VIDEOS):
    """
    Prefer diversity while never allowing a single account or
    instance to dominate the daily queue.

    IMPORTANT:
    These counters MUST be dictionaries, not sets.
    """

    account_counts = {}
    instance_counts = {}

    selected = []

    remaining = list(candidates)

    # --------------------------------------------------------
    # Pass 1:
    # Enforce both diversity limits.
    # --------------------------------------------------------

    for candidate in remaining:
        if len(selected) >= max_items:
            break

        account = (
            candidate.get("account")
            or "unknown-account"
        )

        instance = (
            candidate.get("instance")
            or "unknown-instance"
        )

        if (
            account_counts.get(account, 0)
            >= MAX_VIDEOS_PER_ACCOUNT
        ):
            continue

        if (
            instance_counts.get(instance, 0)
            >= MAX_VIDEOS_PER_INSTANCE
        ):
            continue

        selected.append(candidate)

        account_counts[account] = (
            account_counts.get(account, 0) + 1
        )

        instance_counts[instance] = (
            instance_counts.get(instance, 0) + 1
        )

    # --------------------------------------------------------
    # Pass 2:
    # If diversity limits prevent reaching the target,
    # fill remaining positions using the best candidates.
    #
    # This means diversity is a preference, NOT a hard
    # requirement that forces the queue below available
    # quality.
    # --------------------------------------------------------

    if len(selected) < max_items:

        selected_keys = {
            (
                item.get("sha256")
                or item.get("media_url")
                or item.get("canonical_status_url")
            )
            for item in selected
        }

        for candidate in remaining:
            if len(selected) >= max_items:
                break

            key = (
                candidate.get("sha256")
                or candidate.get("media_url")
                or candidate.get(
                    "canonical_status_url"
                )
            )

            if key in selected_keys:
                continue

            selected.append(candidate)
            selected_keys.add(key)

    return selected[:max_items]


# ============================================================
# JSON serialization
# ============================================================

def write_json(path, data):
    with open(
        path,
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            data,
            handle,
            ensure_ascii=False,
            indent=2,
        )


def printable_candidate(candidate):
    result = dict(candidate)

    # Keep JSON compact and avoid internal analysis bloat.
    return result


# ============================================================
# Main discovery pipeline
# ============================================================

def main():

    raw_candidates = []

    seen_status_ids = set()

    print("Starting UTCutie Mastodon discovery...")
    print(
        f"Instances: {len(INSTANCES)}"
    )
    print(
        f"Hashtags: {len(TAGS)}"
    )

    # --------------------------------------------------------
    # DISCOVERY
    # --------------------------------------------------------

    for instance in INSTANCES:

        instance_statuses = 0

        for tag in TAGS:

            statuses = fetch_hashtag(
                instance,
                tag,
                limit=40,
            )

            instance_statuses += len(statuses)

            for status in statuses:

                status_id = str(
                    status.get("id") or ""
                )

                if status_id:
                    # The same status can appear under
                    # several hashtags on one instance.
                    local_key = (
                        instance,
                        status_id,
                    )

                    if local_key in seen_status_ids:
                        continue

                    seen_status_ids.add(local_key)

                extracted = extract_media_candidates(
                    status,
                    instance,
                    tag,
                )

                raw_candidates.extend(
                    extracted
                )

        print(
            f"{instance}: "
            f"{instance_statuses} statuses, "
            f"{len(raw_candidates)} cumulative "
            f"video candidates"
        )

    # Save raw candidates.
    write_json(
        OUTPUT_CANDIDATES,
        raw_candidates,
    )

    print()
    print(
        f"Raw unique statuses discovered: "
        f"{len(seen_status_ids)}"
    )

    print(
        f"Raw relevant video candidates: "
        f"{len(raw_candidates)}"
    )

    # --------------------------------------------------------
    # Canonical candidate dedup BEFORE media validation.
    # --------------------------------------------------------

    preliminary = []

    seen_preliminary = set()

    for candidate in raw_candidates:

        canonical = (
            candidate.get(
                "canonical_status_url"
            )
            or candidate.get("status_url")
            or candidate.get("media_url")
        )

        if canonical in seen_preliminary:
            continue

        seen_preliminary.add(canonical)

        preliminary.append(candidate)

    print(
        f"Unique candidates for validation: "
        f"{len(preliminary)}"
    )

    # --------------------------------------------------------
    # STRICT CONTENT GATE
    # --------------------------------------------------------

    gated = []

    rejection_counts = {
        "animal relevance below hard threshold": 0,
        "no explicit animal evidence": 0,
        "non-entertainment category detected": 0,
        "too promotional": 0,
    }

    for candidate in preliminary:

        analysis = content_analysis(
            candidate
        )

        rejected, reason = is_hard_reject(
            analysis
        )

        if rejected:
            rejection_counts[reason] = (
                rejection_counts.get(reason, 0)
                + 1
            )
            continue

        candidate["analysis"] = analysis

        gated.append(candidate)

    print()
    print(
        f"Passed strict content gate: "
        f"{len(gated)}"
    )

    print(
        "Content gate rejections:"
    )

    for reason, count in rejection_counts.items():
        if count:
            print(
                f"  {reason}: {count}"
            )

    # --------------------------------------------------------
    # MEDIA VALIDATION
    # --------------------------------------------------------

    validated = []

    with tempfile.TemporaryDirectory() as temp_dir:

        for index, candidate in enumerate(
            gated,
            start=1,
        ):

            validated_candidate = (
                validate_media(
                    candidate,
                    temp_dir,
                )
            )

            if not validated_candidate:
                continue

            analysis = candidate.get(
                "analysis"
            ) or content_analysis(
                candidate
            )

            validated_candidate = (
                score_candidate(
                    validated_candidate,
                    analysis,
                    validated_candidate.get(
                        "media_info"
                    )
                    or {},
                )
            )

            validated.append(
                validated_candidate
            )

            print(
                f"Validated media "
                f"{len(validated)} "
                f"(checked {index}/{len(gated)})"
            )

    # --------------------------------------------------------
    # Deduplicate validated media again using SHA/status/media.
    # --------------------------------------------------------

    validated = deduplicate_canonical(
        validated
    )

    write_json(
        OUTPUT_VALIDATED,
        [
            printable_candidate(item)
            for item in validated
        ],
    )

    print()
    print(
        f"Validated videos: "
        f"{len(gated)}"
    )

    print(
        f"Unique validated videos: "
        f"{len(validated)}"
    )

    # --------------------------------------------------------
    # HISTORY FILTER
    # --------------------------------------------------------

    history = load_history()

    history_key_set = history_keys(
        history
    )

    fresh = [
        candidate
        for candidate in validated
        if not is_in_history(
            candidate,
            history_key_set,
        )
    ]

    print(
        f"Fresh videos after history: "
        f"{len(fresh)}"
    )

    # --------------------------------------------------------
    # Freshness tiers
    #
    # <=14 days: preferred
    # 14-30 days: recent fallback
    # 30-90 days: old fallback
    #
    # >90 days is excluded.
    # --------------------------------------------------------

    preferred = [
        candidate
        for candidate in fresh
        if candidate.get(
            "recency_days",
            9999,
        ) <= PREFERRED_DAYS
    ]

    recent_fallback = [
        candidate
        for candidate in fresh
        if (
            PREFERRED_DAYS
            < candidate.get(
                "recency_days",
                9999,
            )
            <= FRESH_DAYS
        )
    ]

    old_fallback = [
        candidate
        for candidate in fresh
        if (
            FRESH_DAYS
            < candidate.get(
                "recency_days",
                9999,
            )
            <= FALLBACK_DAYS
        )
    ]

    print(
        f"Preferred fresh videos "
        f"(<= {PREFERRED_DAYS} days): "
        f"{len(preferred)}"
    )

    print(
        f"Recent fallback videos "
        f"({PREFERRED_DAYS}-{FRESH_DAYS} days): "
        f"{len(recent_fallback)}"
    )

    print(
        f"Old fallback videos "
        f"({FRESH_DAYS}-{FALLBACK_DAYS} days): "
        f"{len(old_fallback)}"
    )

    # --------------------------------------------------------
    # Build ranking pool.
    #
    # We NEVER force 20.
    # Quality > quota.
    # --------------------------------------------------------

    ranking_pool = (
        preferred
        + recent_fallback
        + old_fallback
    )

    ranking_pool.sort(
        key=lambda item: item.get(
            "total_score",
            0,
        ),
        reverse=True,
    )

    selected = select_with_diversity(
        ranking_pool,
        MAX_VIDEOS,
    )

    # --------------------------------------------------------
    # Final safety check.
    # --------------------------------------------------------

    final_selected = []

    for candidate in selected:

        if (
            candidate.get(
                "animal_relevance",
                0,
            )
            < MIN_ANIMAL_RELEVANCE
        ):
            continue

        if (
            candidate.get(
                "duration",
                0,
            )
            < MIN_DURATION
        ):
            continue

        if (
            candidate.get(
                "duration",
                0,
            )
            > MAX_DURATION
        ):
            continue

        if (
            candidate.get(
                "recency_days",
                9999,
            )
            > FALLBACK_DAYS
        ):
            continue

        final_selected.append(
            candidate
        )

    # Re-sort after final safety filtering.
    final_selected.sort(
        key=lambda item: item.get(
            "total_score",
            0,
        ),
        reverse=True,
    )

    final_selected = final_selected[
        :MAX_VIDEOS
    ]

    write_json(
        OUTPUT_SELECTED,
        [
            printable_candidate(item)
            for item in final_selected
        ],
    )

    # --------------------------------------------------------
    # Output summary
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("UTCUTIE DISCOVERY COMPLETE")
    print("=" * 70)

    print(
        f"Raw candidates: "
        f"{len(raw_candidates)}"
    )

    print(
        f"Validated videos: "
        f"{len(gated)}"
    )

    print(
        f"Unique validated videos: "
        f"{len(validated)}"
    )

    print(
        f"Fresh videos: "
        f"{len(fresh)}"
    )

    print(
        f"Preferred fresh videos: "
        f"{len(preferred)}"
    )

    print(
        f"Recent fallback videos: "
        f"{len(recent_fallback)}"
    )

    print(
        f"Old fallback videos: "
        f"{len(old_fallback)}"
    )

    print(
        f"SELECTED UNIQUE VIDEOS: "
        f"{len(final_selected)}"
    )

    print(
        f"Published-history entries: "
        f"{len(history)}"
    )

    print()
    print("SELECTED VIDEOS")
    print("-" * 70)

    for number, candidate in enumerate(
        final_selected,
        start=1,
    ):

        caption = (
            candidate.get("caption")
            or ""
        )

        preview_caption = caption.replace(
            "\n",
            " | ",
        )

        if len(preview_caption) > 160:
            preview_caption = (
                preview_caption[:157]
                + "..."
            )

        print(
            f"{number}. "
            f"{candidate.get('account', 'unknown')} | "
            f"{candidate.get('instance', '')}"
        )

        print(
            f"   Age: "
            f"{candidate.get('recency_days', 0)} days | "
            f"Duration: "
            f"{candidate.get('duration', 0)} sec"
        )

        print(
            f"   Animal relevance: "
            f"{candidate.get('animal_relevance', 0)} | "
            f"Engagement: "
            f"{candidate.get('engagement_score', 0)} | "
            f"Total: "
            f"{candidate.get('total_score', 0)}"
        )

        print(
            f"   Caption: "
            f"{preview_caption}"
        )

        print(
            f"   Media: "
            f"{candidate.get('media_url', '')}"
        )

        print()

    print(
        "Publication history was NOT modified."
    )

    print()
    print(
        "Output files:"
    )

    print(
        f"  {OUTPUT_CANDIDATES}"
    )

    print(
        f"  {OUTPUT_VALIDATED}"
    )

    print(
        f"  {OUTPUT_SELECTED}"
    )


if __name__ == "__main__":
    main()
