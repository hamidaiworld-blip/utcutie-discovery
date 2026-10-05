import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests


# ============================================================
# UTCUTIE MASTODON DISCOVERY
# QUALITY-HARDENED VERSION
# ============================================================

MAX_VIDEOS = 20

MIN_DURATION = 15
MAX_DURATION = 180
MAX_FILE_SIZE = 48 * 1024 * 1024

# Freshness policy
PREFERRED_DAYS = 14
FRESH_DAYS = 30
FALLBACK_DAYS = 90

# Hard content threshold
MIN_ANIMAL_RELEVANCE = 50

# Diversity
MAX_VIDEOS_PER_ACCOUNT = 2
MAX_VIDEOS_PER_INSTANCE = 8

REQUEST_TIMEOUT = 25
DOWNLOAD_TIMEOUT = 60

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


# ============================================================
# KEYWORDS
# ============================================================

ANIMAL_TERMS = {
    "cat": 25,
    "cats": 25,
    "kitten": 28,
    "kittens": 28,
    "kitty": 28,
    "kitties": 28,
    "dog": 25,
    "dogs": 25,
    "puppy": 28,
    "puppies": 28,
    "pup": 20,
    "pet": 18,
    "pets": 18,
    "animal": 15,
    "animals": 15,
    "rabbit": 25,
    "bunny": 25,
    "bunnies": 25,
    "hamster": 25,
    "guinea pig": 25,
    "bird": 20,
    "birds": 20,
    "parrot": 25,
    "parrots": 25,
    "duck": 20,
    "ducks": 20,
    "goose": 20,
    "geese": 20,
    "chicken": 20,
    "chickens": 20,
    "horse": 20,
    "horses": 20,
    "foal": 25,
    "cow": 18,
    "cows": 18,
    "goat": 20,
    "goats": 20,
    "sheep": 18,
    "lamb": 22,
    "pig": 20,
    "pigs": 20,
    "hedgehog": 25,
    "ferret": 25,
    "squirrel": 20,
    "fox": 15,
    "otter": 22,
    "seal": 22,
    "penguin": 22,
    "turtle": 20,
    "tortoise": 20,
    "frog": 20,
    "frogs": 20,
    "wildlife": 15,
}

PET_CONTEXT_TERMS = {
    "pet": 15,
    "pets": 15,
    "petlife": 15,
    "petlover": 15,
    "petlove": 15,
    "petcommunity": 15,
    "furbaby": 20,
    "fur baby": 20,
    "hooman": 12,
    "hoomans": 12,
    "paw": 10,
    "paws": 10,
    "pawfect": 15,
    "zoomies": 20,
    "treat": 8,
    "treats": 8,
    "walkies": 12,
    "walk": 5,
    "fetch": 15,
    "belly rub": 15,
    "belly rubs": 15,
    "cuddle": 15,
    "cuddles": 15,
    "snuggle": 15,
    "snuggles": 15,
    "playful": 18,
    "playtime": 18,
    "sleeping": 8,
    "sleepy": 8,
    "adopted": 12,
    "adoption": 12,
    "foster": 8,
    "rescue": 8,
}

ENTERTAINMENT_TERMS = {
    "funny": 20,
    "hilarious": 20,
    "lol": 10,
    "laugh": 10,
    "laughing": 10,
    "silly": 18,
    "adorable": 18,
    "cute": 18,
    "cutest": 18,
    "wholesome": 18,
    "sweet": 10,
    "heartwarming": 20,
    "heartwarming": 20,
    "playful": 15,
    "playing": 12,
    "play": 8,
    "zoomies": 20,
    "unexpected": 12,
    "surprise": 10,
    "goofy": 18,
    "chaos": 12,
    "derp": 18,
    "derpy": 18,
    "silly": 18,
    "loving": 12,
    "love": 8,
    "kiss": 10,
    "kisses": 10,
    "cuddle": 12,
    "cuddling": 12,
    "best friend": 12,
}

# Things that strongly suggest this is NOT the entertainment content
# we want on UTCutie.
HARD_NEGATIVE_TERMS = {
    "politics",
    "political",
    "election",
    "president",
    "government",
    "minister",
    "parliament",
    "senate",
    "congress",
    "war",
    "military",
    "army",
    "armed forces",
    "soldier",
    "soldiers",
    "weapon",
    "weapons",
    "missile",
    "nato",
    "football",
    "soccer",
    "nfl",
    "nba",
    "mlb",
    "nhl",
    "sports",
    "match",
    "game score",
    "gaming",
    "videogame",
    "video game",
    "twitch",
    "crypto",
    "bitcoin",
    "stock market",
    "business",
    "entrepreneur",
    "startup",
    "marketing",
    "self-help",
    "org chart",
    "anxiety",
    "productivity",
    "religion",
    "religious",
    "islam",
    "christian",
    "christianity",
    "bible",
    "quran",
    "sermon",
    "prayer",
    "campaign",
    "campaigning",
    "activism",
    "activist",
    "slaughter",
    "climate campaign",
    "fundraiser",
    "fundraising",
    "donate",
    "donation",
    "donations",
    "wishlist",
    "crowdfunding",
    "petition",
    "political campaign",
}

PROMOTIONAL_TERMS = {
    "donate",
    "donation",
    "donations",
    "wishlist",
    "fundraiser",
    "fundraising",
    "campaign",
    "campaigning",
    "join our campaign",
    "support our campaign",
    "subscribe",
    "follow us",
    "follow me",
    "buy now",
    "shop now",
    "sale",
    "discount",
    "sponsor",
    "sponsored",
    "promo",
    "promotion",
    "advertisement",
    "advertising",
    "link in bio",
    "call ",
    "contact us",
    "order now",
}

DISCOVERY_TAG_BONUS = {
    "cats": 15,
    "cat": 15,
    "kittens": 18,
    "dogs": 15,
    "dog": 15,
    "puppy": 18,
    "pets": 12,
    "aww": 15,
    "cuteanimals": 18,
    "funnyanimals": 20,
    "cutepets": 20,
    "funnydogs": 20,
    "funnycats": 20,
    "petsofthefediverse": 15,
    "dogsofthefediverse": 15,
    "catsofthefediverse": 15,
    "wholesome": 12,
    "adorable": 15,
    "caturday": 15,
}


# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "UTCutieDiscovery/1.0 "
            "(automated public Mastodon video discovery)"
        )
    }
)


# ============================================================
# GENERAL HELPERS
# ============================================================

def normalize_text(value):
    if not value:
        return ""

    value = html.unescape(str(value))
    value = re.sub(r"<script.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("\xa0", " ")

    return re.sub(r"\s+", " ", value).strip().lower()


def clean_caption(value):
    if not value:
        return ""

    text = html.unescape(str(value))

    text = re.sub(
        r"<script.*?</script>",
        "",
        text,
        flags=re.I | re.S,
    )

    text = re.sub(
        r"<style.*?</style>",
        "",
        text,
        flags=re.I | re.S,
    )

    # Preserve block-level breaks.
    text = re.sub(
        r"</?(?:p|div|br|li|blockquote|h[1-6])[^>]*>",
        "\n",
        text,
        flags=re.I,
    )

    text = re.sub(r"<[^>]+>", "", text)

    # Remove URLs.
    text = re.sub(
        r"https?://\S+|www\.\S+",
        "",
        text,
        flags=re.I,
    )

    # Remove hashtags.
    text = re.sub(
        r"(?<!\w)#[\w\u0080-\uffff-]+",
        "",
        text,
    )

    # Remove phone numbers.
    text = re.sub(
        r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)",
        "",
        text,
    )

    lines = []

    for raw_line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()

        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue

        # Drop obvious promotional fragments.
        lower = line.lower()

        if (
            lower.startswith("wishlist")
            or lower.startswith("link in bio")
            or lower.startswith("subscribe")
            or lower.startswith("follow us")
            or lower.startswith("follow me")
        ):
            continue

        lines.append(line)

    while lines and lines[-1] == "":
        lines.pop()

    # No more than one blank line between paragraphs.
    result = []
    previous_blank = False

    for line in lines:
        if line == "":
            if not previous_blank:
                result.append("")
            previous_blank = True
        else:
            result.append(line)
            previous_blank = False

    return "\n".join(result).strip()


def telegram_caption(value):
    text = clean_caption(value)

    # Leave room for the channel handle.
    max_source_length = 900

    if len(text) <= max_source_length:
        return text

    truncated = text[:max_source_length]

    # Prefer a complete line.
    if "\n" in truncated:
        truncated = truncated.rsplit("\n", 1)[0]

    if len(truncated.strip()) < 100:
        truncated = text[:max_source_length].rsplit(" ", 1)[0]

    return truncated.strip()


def normalize_status_url(url):
    """
    Canonicalize status URLs so federated copies of the same post
    collapse into one candidate.

    Examples:
      fed.brid.gy/r/https://bsky.app/...
      https://bsky.app/...

    both become the underlying canonical URL.

    Trailing slashes and fragments are removed.
    """
    if not url:
        return ""

    url = html.unescape(str(url)).strip()

    if url.startswith("https://fed.brid.gy/r/"):
        url = unquote(url[len("https://fed.brid.gy/r/"):])

    elif url.startswith("http://fed.brid.gy/r/"):
        url = unquote(url[len("http://fed.brid.gy/r/"):])

    parsed = urlparse(url)

    if not parsed.scheme or not parsed.netloc:
        return url.rstrip("/")

    path = parsed.path.rstrip("/")

    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def sha256_file(path):
    digest = hashlib.sha256()

    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
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
        "stream=codec_name,width,height,duration",
        "-of",
        "json",
        str(path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
        streams = data.get("streams", [])

        if not streams:
            return None

        stream = streams[0]

        duration = float(stream.get("duration") or 0)

        return {
            "duration": duration,
            "codec": stream.get("codec_name"),
            "width": int(stream.get("width") or 0),
            "height": int(stream.get("height") or 0),
        }

    except Exception:
        return None


# ============================================================
# MASTODON API
# ============================================================

def fetch_tag_statuses(instance, tag):
    url = f"https://{instance}/api/v1/timelines/tag/{tag}"

    try:
        response = SESSION.get(
            url,
            params={
                "limit": 25,
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            return []

        data = response.json()

        if not isinstance(data, list):
            return []

        return data

    except Exception:
        return []


def extract_video_candidates(statuses, instance, discovery_source):
    candidates = []

    for status in statuses:
        media_attachments = status.get("media_attachments") or []

        for media in media_attachments:
            media_type = media.get("type")

            if media_type != "video":
                continue

            media_url = media.get("url")

            if not media_url:
                continue

            account = status.get("account") or {}

            caption = status.get("content") or ""

            candidate = {
                "source": "mastodon",
                "instance": instance,
                "discovery_source": discovery_source,
                "status_id": str(status.get("id") or ""),
                "status_url": status.get("url") or "",
                "created_at": status.get("created_at") or "",
                "account": account.get("acct") or "",
                "account_name": account.get("display_name") or "",
                "media_url": media_url,
                "media_type": media_type,
                "caption": clean_caption(caption),
                "caption_length": len(clean_caption(caption)),
                "favourites_count": int(status.get("favourites_count") or 0),
                "reblogs_count": int(status.get("reblogs_count") or 0),
                "replies_count": int(status.get("replies_count") or 0),
            }

            candidates.append(candidate)

    return candidates


# ============================================================
# CONTENT RELEVANCE
# ============================================================

def count_term_hits(text, terms):
    score = 0
    hits = []

    normalized = normalize_text(text)

    for term, weight in terms.items():
        if term in normalized:
            score += weight
            hits.append(term)

    return score, hits


def content_analysis(candidate):
    caption = normalize_text(candidate.get("caption", ""))
    account_name = normalize_text(candidate.get("account_name", ""))
    account = normalize_text(candidate.get("account", ""))
    discovery = normalize_text(candidate.get("discovery_source", ""))

    combined = " ".join(
        [
            caption,
            account_name,
            account,
        ]
    )

    animal_score, animal_hits = count_term_hits(
        combined,
        ANIMAL_TERMS,
    )

    pet_score, pet_hits = count_term_hits(
        combined,
        PET_CONTEXT_TERMS,
    )

    entertainment_score, entertainment_hits = count_term_hits(
        combined,
        ENTERTAINMENT_TERMS,
    )

    negative_hits = []

    for term in HARD_NEGATIVE_TERMS:
        if term in combined:
            negative_hits.append(term)

    promotional_hits = []

    for term in PROMOTIONAL_TERMS:
        if term in combined:
            promotional_hits.append(term)

    tag_name = discovery.replace("tag:", "").strip()

    discovery_bonus = DISCOVERY_TAG_BONUS.get(tag_name, 0)

    # Strong animal evidence.
    relevance = (
        animal_score
        + min(pet_score, 30)
        + min(entertainment_score, 25)
        + discovery_bonus
    )

    # A generic animal discovery tag alone must NOT make a post qualify.
    if tag_name in {
        "animals",
        "pets",
        "wholesome",
        "adorable",
        "aww",
        "silentsunday",
        "worldanimalday",
    }:
        relevance -= 10

    # Strongly penalize content that looks unrelated to the channel.
    relevance -= min(len(negative_hits) * 30, 120)

    # Promotional content receives a significant penalty.
    relevance -= min(len(promotional_hits) * 18, 72)

    # A post with explicit pet/animal vocabulary gets a useful bonus.
    if animal_hits:
        relevance += 10

    # Strong pet-specific discovery tags are valuable evidence.
    if tag_name in {
        "cats",
        "cat",
        "kittens",
        "dogs",
        "dog",
        "puppy",
        "cuteanimals",
        "funnyanimals",
        "cutepets",
        "funnydogs",
        "funnycats",
        "petsofthefediverse",
        "dogsofthefediverse",
        "catsofthefediverse",
        "caturday",
    }:
        relevance += 15

    relevance = max(0, min(100, float(relevance)))

    return {
        "animal_relevance": relevance,
        "animal_hits": animal_hits,
        "pet_hits": pet_hits,
        "entertainment_hits": entertainment_hits,
        "negative_hits": negative_hits,
        "promotional_hits": promotional_hits,
        "discovery_bonus": discovery_bonus,
    }


def is_hard_reject(candidate, analysis):
    relevance = analysis["animal_relevance"]

    negative_hits = analysis["negative_hits"]
    promotional_hits = analysis["promotional_hits"]

    caption = normalize_text(candidate.get("caption", ""))

    # Generic/non-animal content must never survive.
    if relevance < MIN_ANIMAL_RELEVANCE:
        return True, "animal relevance below hard threshold"

    # Obvious non-UTCutie categories.
    if negative_hits:
        # If the post contains strong animal evidence AND only one
        # weak incidental negative word, don't necessarily reject.
        strong_negative = any(
            term in {
                "politics",
                "political",
                "election",
                "president",
                "government",
                "war",
                "military",
                "army",
                "weapon",
                "weapons",
                "football",
                "soccer",
                "nfl",
                "nba",
                "sports",
                "gaming",
                "religion",
                "religious",
                "islam",
                "christian",
                "campaign",
                "fundraising",
                "donate",
                "donation",
                "activism",
                "activist",
                "slaughter",
                "org chart",
                "anxiety",
            }
            for term in negative_hits
        )

        if strong_negative:
            return True, "non-entertainment category detected"

    # Campaign/fundraising content is not the intended channel content.
    if promotional_hits:
        if any(
            term in promotional_hits
            for term in {
                "donate",
                "donation",
                "donations",
                "wishlist",
                "fundraiser",
                "fundraising",
                "campaign",
                "join our campaign",
                "support our campaign",
                "petition",
            }
        ):
            return True, "fundraising/campaign content"

    # Caption must have actual animal evidence, not merely a generic tag.
    if not analysis["animal_hits"]:
        return True, "no explicit animal evidence"

    # Extremely generic captions are allowed only if the animal-specific
    # discovery source is strong.
    if len(caption) < 8:
        tag_name = candidate.get("discovery_source", "").replace(
            "tag:",
            "",
        )

        if tag_name not in {
            "cats",
            "cat",
            "kittens",
            "dogs",
            "dog",
            "puppy",
            "funnydogs",
            "funnycats",
            "cutepets",
            "cuteanimals",
        }:
            return True, "caption too generic"

    return False, ""


# ============================================================
# ENGAGEMENT / RECENCY / QUALITY
# ============================================================

def engagement_score(candidate):
    favourites = candidate.get("favourites_count", 0)
    reblogs = candidate.get("reblogs_count", 0)
    replies = candidate.get("replies_count", 0)

    # Logarithmic so large accounts don't completely dominate.
    raw = (
        favourites * 1.0
        + reblogs * 2.5
        + replies * 1.2
    )

    if raw <= 0:
        return 0.0

    import math

    return min(100.0, math.log1p(raw) * 14.0)


def calculate_age_days(created_at):
    try:
        value = datetime.fromisoformat(
            created_at.replace("Z", "+00:00")
        )

        now = datetime.now(timezone.utc)

        age = now - value

        return max(0.0, age.total_seconds() / 86400.0)

    except Exception:
        return 9999.0


def recency_score(age_days):
    if age_days <= 1:
        return 100.0

    if age_days <= 3:
        return 95.0

    if age_days <= 7:
        return 90.0

    if age_days <= 14:
        return 80.0

    if age_days <= 30:
        return 55.0

    if age_days <= 60:
        return 25.0

    if age_days <= 90:
        return 8.0

    return 0.0


def quality_score(metadata):
    width = metadata.get("width", 0)
    height = metadata.get("height", 0)

    pixels = width * height

    if pixels >= 1920 * 1080:
        return 100.0

    if pixels >= 1280 * 720:
        return 90.0

    if pixels >= 720 * 720:
        return 80.0

    if pixels >= 576 * 576:
        return 65.0

    return 45.0


def caption_quality_score(candidate, analysis):
    caption = candidate.get("caption", "").strip()

    if not caption:
        return 20.0

    score = 50.0

    length = len(caption)

    if 20 <= length <= 300:
        score += 25

    elif 10 <= length <= 500:
        score += 10

    if analysis["entertainment_hits"]:
        score += 15

    if analysis["promotional_hits"]:
        score -= 35

    if len(analysis["negative_hits"]) > 0:
        score -= 20

    return max(0.0, min(100.0, score))


def calculate_final_score(candidate):
    animal = candidate["animal_relevance"]
    engagement = candidate["engagement"]
    recency = candidate["recency"]
    quality = candidate["quality"]
    caption_quality = candidate["caption_quality"]

    # Animal relevance is the most important factor.
    score = (
        animal * 3.0
        + engagement * 1.0
        + recency * 2.2
        + quality * 0.6
        + caption_quality * 0.8
    )

    # Very fresh posts get a small additional advantage.
    age_days = candidate.get("age_days", 9999)

    if age_days <= 3:
        score += 25

    elif age_days <= 7:
        score += 15

    elif age_days <= 14:
        score += 8

    # Prefer shorter, snackable videos, without excluding longer ones.
    duration = candidate.get("duration", 0)

    if 15 <= duration <= 45:
        score += 12

    elif 45 < duration <= 90:
        score += 6

    return score


# ============================================================
# DIRECT MEDIA VALIDATION
# ============================================================

def download_and_validate(candidate, temp_dir):
    media_url = candidate["media_url"]

    extension = ".mp4"

    output_path = (
        Path(temp_dir)
        / f"{hashlib.md5(media_url.encode()).hexdigest()}{extension}"
    )

    try:
        with SESSION.get(
            media_url,
            stream=True,
            timeout=DOWNLOAD_TIMEOUT,
        ) as response:

            if response.status_code != 200:
                return None

            content_type = (
                response.headers.get("content-type") or ""
            ).lower()

            if (
                "video" not in content_type
                and "octet-stream" not in content_type
            ):
                return None

            content_length = response.headers.get("content-length")

            if content_length:
                try:
                    if int(content_length) > MAX_FILE_SIZE:
                        return None
                except ValueError:
                    pass

            total = 0

            with open(output_path, "wb") as handle:
                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):
                    if not chunk:
                        continue

                    total += len(chunk)

                    if total > MAX_FILE_SIZE:
                        return None

                    handle.write(chunk)

        metadata = run_ffprobe(output_path)

        if not metadata:
            return None

        duration = metadata["duration"]

        if duration < MIN_DURATION or duration > MAX_DURATION:
            return None

        digest = sha256_file(output_path)

        candidate["duration"] = round(duration, 3)
        candidate["file_size"] = total
        candidate["sha256"] = digest
        candidate["codec"] = metadata["codec"]
        candidate["width"] = metadata["width"]
        candidate["height"] = metadata["height"]
        candidate["actual_quality"] = quality_score(metadata)

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
# HISTORY
# ============================================================

def load_history():
    path = Path("history.json")

    if not path.exists():
        return []

    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            for key in (
                "history",
                "published",
                "entries",
                "items",
            ):
                value = data.get(key)

                if isinstance(value, list):
                    return value

        return []

    except Exception:
        return []


def history_keys(history):
    status_urls = set()
    media_urls = set()
    hashes = set()

    for item in history:
        if not isinstance(item, dict):
            continue

        status_url = normalize_status_url(
            item.get("status_url") or ""
        )

        media_url = item.get("media_url") or ""
        digest = item.get("sha256") or ""

        if status_url:
            status_urls.add(status_url)

        if media_url:
            media_urls.add(media_url)

        if digest:
            hashes.add(digest)

    return status_urls, media_urls, hashes


def is_in_history(candidate, history_sets):
    status_urls, media_urls, hashes = history_sets

    status_url = normalize_status_url(
        candidate.get("status_url") or ""
    )

    media_url = candidate.get("media_url") or ""
    digest = candidate.get("sha256") or ""

    if status_url and status_url in status_urls:
        return True

    if media_url and media_url in media_urls:
        return True

    if digest and digest in hashes:
        return True

    return False


# ============================================================
# CANONICAL DEDUPLICATION
# ============================================================

def candidate_preference_score(candidate):
    """
    Used only when multiple federated copies represent the same
    canonical post.

    Prefer:
      1. higher engagement
      2. better actual quality
      3. stronger recency
      4. cleaner caption
    """
    return (
        candidate.get("engagement", 0) * 2
        + candidate.get("actual_quality", 0)
        + candidate.get("recency", 0)
        + candidate.get("caption_quality", 0) * 0.5
    )


def deduplicate_canonical(candidates):
    by_status = {}
    without_status = []

    for candidate in candidates:
        key = normalize_status_url(
            candidate.get("status_url") or ""
        )

        if not key:
            without_status.append(candidate)
            continue

        existing = by_status.get(key)

        if existing is None:
            by_status[key] = candidate

        elif candidate_preference_score(candidate) > candidate_preference_score(existing):
            by_status[key] = candidate

    result = list(by_status.values())

    # Exact media dedup as a second layer.
    by_sha = {}

    for candidate in result:
        digest = candidate.get("sha256")

        if not digest:
            without_status.append(candidate)
            continue

        existing = by_sha.get(digest)

        if existing is None:
            by_sha[digest] = candidate

        elif candidate_preference_score(candidate) > candidate_preference_score(existing):
            by_sha[digest] = candidate

    # Keep candidates without SHA only if necessary.
    final = list(by_sha.values())

    seen_status = {
        normalize_status_url(
            item.get("status_url") or ""
        )
        for item in final
    }

    for candidate in without_status:
        key = normalize_status_url(
            candidate.get("status_url") or ""
        )

        if key and key in seen_status:
            continue

        final.append(candidate)

        if key:
            seen_status.add(key)

    return final


# ============================================================
# DIVERSITY SELECTION
# ============================================================

def select_with_diversity(candidates):
    selected = []

    account_counts = {}
    instance_counts = set()

    # --------------------------------------------------------
    # Pass 1:
    # quality + diversity
    # --------------------------------------------------------

    for candidate in candidates:
        if len(selected) >= MAX_VIDEOS:
            break

        account = candidate.get("account") or "unknown"
        instance = candidate.get("instance") or "unknown"

        if account_counts.get(account, 0) >= MAX_VIDEOS_PER_ACCOUNT:
            continue

        if instance_counts.count(instance) >= MAX_VIDEOS_PER_INSTANCE:
            continue

        selected.append(candidate)

        account_counts[account] = (
            account_counts.get(account, 0) + 1
        )

        instance_counts.append(instance)

    # --------------------------------------------------------
    # Pass 2:
    # fill remaining positions if necessary.
    # Quality still wins; diversity is a preference.
    # --------------------------------------------------------

    if len(selected) < MAX_VIDEOS:
        selected_keys = {
            normalize_status_url(
                item.get("status_url") or ""
            )
            for item in selected
        }

        for candidate in candidates:
            if len(selected) >= MAX_VIDEOS:
                break

            key = normalize_status_url(
                candidate.get("status_url") or ""
            )

            if key in selected_keys:
                continue

            selected.append(candidate)
            selected_keys.add(key)

    return selected


# ============================================================
# OUTPUT
# ============================================================

def write_json(filename, data):
    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            data,
            handle,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("UTCUTIE MASTODON DISCOVERY — QUALITY HARDENED")
    print("=" * 70)

    history = load_history()

    print(
        f"Publication history entries: {len(history)}"
    )

    history_sets = history_keys(history)

    raw_statuses = {}

    raw_candidates = []

    # --------------------------------------------------------
    # DISCOVERY
    # --------------------------------------------------------

    for instance in INSTANCES:
        print()
        print("=" * 60)
        print(f"INSTANCE: {instance}")
        print("=" * 60)

        for tag in TAGS:
            statuses = fetch_tag_statuses(
                instance,
                tag,
            )

            print(
                f"TAG: #{tag:<24} statuses: {len(statuses)}"
            )

            for status in statuses:
                status_id = str(status.get("id") or "")

                if not status_id:
                    continue

                # Keep the best/full status only once.
                if status_id not in raw_statuses:
                    raw_statuses[status_id] = (
                        status,
                        instance,
                        f"tag:{tag}",
                    )

                else:
                    existing = raw_statuses[status_id]

                    # Prefer the first source; duplicate federation
                    # discovery is expected.
                    _ = existing

    for status, instance, discovery_source in raw_statuses.values():
        raw_candidates.extend(
            extract_video_candidates(
                [status],
                instance,
                discovery_source,
            )
        )

    print()
    print(
        f"Raw unique statuses discovered: "
        f"{len(raw_statuses)}"
    )

    print(
        f"Raw relevant video candidates: "
        f"{len(raw_candidates)}"
    )

    # --------------------------------------------------------
    # FIRST DEDUP:
    # canonical status URL / media URL
    # --------------------------------------------------------

    preliminary = {}

    for candidate in raw_candidates:
        status_key = normalize_status_url(
            candidate.get("status_url") or ""
        )

        media_key = candidate.get("media_url") or ""

        key = status_key or f"media:{media_key}"

        if key not in preliminary:
            preliminary[key] = candidate

    candidates = list(preliminary.values())

    print(
        f"Unique candidates for validation: "
        f"{len(candidates)}"
    )

    # --------------------------------------------------------
    # CONTENT GATE BEFORE DOWNLOAD
    # --------------------------------------------------------

    content_passed = []

    rejected_counts = {}

    for candidate in candidates:
        analysis = content_analysis(candidate)

        candidate.update(
            {
                "animal_relevance": analysis[
                    "animal_relevance"
                ],
                "_animal_hits": analysis["animal_hits"],
                "_pet_hits": analysis["pet_hits"],
                "_entertainment_hits": analysis[
                    "entertainment_hits"
                ],
                "_negative_hits": analysis[
                    "negative_hits"
                ],
                "_promotional_hits": analysis[
                    "promotional_hits"
                ],
            }
        )

        rejected, reason = is_hard_reject(
            candidate,
            analysis,
        )

        if rejected:
            rejected_counts[reason] = (
                rejected_counts.get(reason, 0) + 1
            )
            continue

        content_passed.append(candidate)

    print()
    print(
        f"Passed strict content gate: "
        f"{len(content_passed)}"
    )

    if rejected_counts:
        print("Content gate rejections:")

        for reason, count in sorted(
            rejected_counts.items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            print(f"  {reason}: {count}")

    # --------------------------------------------------------
    # VALIDATE ACTUAL VIDEO MEDIA
    # --------------------------------------------------------

    validated = []

    temp_dir = tempfile.mkdtemp(
        prefix="utcutie_mastodon_"
    )

    try:
        for index, candidate in enumerate(
            content_passed,
            start=1,
        ):
            validated_candidate = download_and_validate(
                candidate,
                temp_dir,
            )

            if not validated_candidate:
                continue

            analysis = content_analysis(
                validated_candidate
            )

            # Re-check after media validation.
            rejected, _ = is_hard_reject(
                validated_candidate,
                analysis,
            )

            if rejected:
                continue

            validated_candidate["engagement"] = (
                engagement_score(
                    validated_candidate
                )
            )

            age_days = calculate_age_days(
                validated_candidate["created_at"]
            )

            validated_candidate["age_days"] = round(
                age_days,
                2,
            )

            validated_candidate["recency"] = (
                recency_score(age_days)
            )

            validated_candidate["quality"] = (
                validated_candidate.get(
                    "actual_quality",
                    0,
                )
            )

            validated_candidate["caption_quality"] = (
                caption_quality_score(
                    validated_candidate,
                    analysis,
                )
            )

            validated_candidate["pre_validation_score"] = (
                validated_candidate["animal_relevance"] * 3
                + validated_candidate["engagement"]
                + validated_candidate["recency"] * 2.2
                + validated_candidate["quality"] * 0.6
                + validated_candidate["caption_quality"] * 0.8
            )

            validated_candidate["telegram_caption"] = (
                telegram_caption(
                    validated_candidate["caption"]
                )
            )

            validated.append(
                validated_candidate
            )

        print()
        print(f"Validated videos: {len(validated)}")

    finally:
        shutil.rmtree(
            temp_dir,
            ignore_errors=True,
        )

    # --------------------------------------------------------
    # CANONICAL + SHA DEDUP AFTER VALIDATION
    # --------------------------------------------------------

    validated = deduplicate_canonical(
        validated
    )

    print(
        f"Unique validated videos: {len(validated)}"
    )

    # --------------------------------------------------------
    # HISTORY FILTER
    # --------------------------------------------------------

    fresh = []

    for candidate in validated:
        if is_in_history(
            candidate,
            history_sets,
        ):
            continue

        fresh.append(candidate)

    print(
        f"Fresh videos after history: {len(fresh)}"
    )

    # --------------------------------------------------------
    # FRESHNESS TIERS
    # --------------------------------------------------------

    preferred = [
        candidate
        for candidate in fresh
        if candidate.get("age_days", 9999)
        <= PREFERRED_DAYS
    ]

    recent_fallback = [
        candidate
        for candidate in fresh
        if (
            PREFERRED_DAYS
            < candidate.get("age_days", 9999)
            <= FRESH_DAYS
        )
    ]

    old_fallback = [
        candidate
        for candidate in fresh
        if (
            FRESH_DAYS
            < candidate.get("age_days", 9999)
            <= FALLBACK_DAYS
        )
    ]

    print(
        f"Preferred fresh videos (<= {PREFERRED_DAYS} days): "
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
    # SCORE
    # --------------------------------------------------------

    for candidate in fresh:
        candidate["score"] = calculate_final_score(
            candidate
        )

    preferred.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    recent_fallback.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    old_fallback.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    # --------------------------------------------------------
    # DAILY POOL
    #
    # Strong preference for fresh material.
    # Older content only enters when necessary.
    # --------------------------------------------------------

    ranking_pool = []

    ranking_pool.extend(preferred)

    ranking_pool.extend(recent_fallback)

    ranking_pool.extend(old_fallback)

    # Hard maximum age.
    ranking_pool = [
        candidate
        for candidate in ranking_pool
        if candidate.get("age_days", 9999)
        <= FALLBACK_DAYS
    ]

    # --------------------------------------------------------
    # FINAL SELECTION
    # --------------------------------------------------------

    selected = select_with_diversity(
        ranking_pool
    )

    # --------------------------------------------------------
    # REMOVE INTERNAL SCORING FIELDS FROM OUTPUT
    # --------------------------------------------------------

    public_candidates = []

    for candidate in selected:
        cleaned = dict(candidate)

        for key in list(cleaned.keys()):
            if key.startswith("_"):
                del cleaned[key]

        public_candidates.append(cleaned)

    # --------------------------------------------------------
    # WRITE OUTPUT FILES
    # --------------------------------------------------------

    write_json(
        "mastodon_expanded_candidates.json",
        candidates,
    )

    write_json(
        "mastodon_expanded_validated.json",
        validated,
    )

    write_json(
        "mastodon_expanded_selected_candidates.json",
        public_candidates,
    )

    # --------------------------------------------------------
    # REPORT
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print(
        "UTCUTIE MASTODON DISCOVERY — QUALITY HARDENED COMPLETE"
    )
    print("=" * 70)

    print(
        f"Publication history entries: {len(history)}"
    )

    print(
        f"Raw unique statuses: {len(raw_statuses)}"
    )

    print(
        f"Unique candidates: {len(candidates)}"
    )

    print(
        f"Passed strict content gate: "
        f"{len(content_passed)}"
    )

    print(
        f"Validated videos: {len(validated)}"
    )

    print(
        f"Fresh videos after history: {len(fresh)}"
    )

    print(
        f"Preferred fresh videos: {len(preferred)}"
    )

    print(
        f"Selected videos: {len(public_candidates)}"
    )

    print()

    # Show the actual selected pool in a compact form.
    for index, candidate in enumerate(
        public_candidates,
        start=1,
    ):
        print("-" * 70)

        print(
            f"{index:02d}. "
            f"{candidate.get('account_name') or candidate.get('account')}"
        )

        print(
            f"    age: {candidate.get('age_days')} days | "
            f"duration: {candidate.get('duration')} sec | "
            f"score: {candidate.get('score'):.1f}"
        )

        print(
            f"    animal relevance: "
            f"{candidate.get('animal_relevance')}"
        )

        print(
            f"    discovery: "
            f"{candidate.get('discovery_source')}"
        )

        print(
            f"    status: "
            f"{candidate.get('status_url')}"
        )

        caption = (
            candidate.get("telegram_caption")
            or ""
        ).replace("\n", " ")

        print(
            f"    caption: {caption[:180]}"
        )

    print()
    print(
        "Raw results: "
        "mastodon_expanded_candidates.json"
    )

    print(
        "Validated results: "
        "mastodon_expanded_validated.json"
    )

    print(
        "Selected results: "
        "mastodon_expanded_selected_candidates.json"
    )

    print()
    print(
        "IMPORTANT: history.json was NOT modified."
    )

    print()
    print("Post job cleanup.")


if __name__ == "__main__":
    main()
