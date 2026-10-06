import hashlib
import html
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

# Freshness policy.
PRIMARY_DAYS = 14
SECONDARY_DAYS = 30
EMERGENCY_DAYS = 60

# Minimum quality/relevance gates.
MIN_CONTENT_VALUE = 30
EMERGENCY_MIN_CONTENT_VALUE = 55
EMERGENCY_MIN_SCORE = 75

REQUEST_TIMEOUT = 30

# Telegram video captions have a 1024-character limit.
# Leave room for the final @utcutie line.
MAX_CAPTION_LENGTH = 900

HISTORY_FILE = Path("history.json")
CANDIDATES_FILE = Path("mastodon_candidates.json")
VALIDATED_FILE = Path("validated_candidates.json")
SELECTED_FILE = Path("selected_candidates.json")

# Diversity controls.
#
# These are NOT hard quotas.
# They only prevent the ranking from filling the entire
# daily selection with videos from one account/source.
MAX_VIDEOS_PER_ACCOUNT = 2
MAX_VIDEOS_PER_INSTANCE = 8


# ============================================================
# ANIMAL RELEVANCE
# ============================================================

ANIMAL_KEYWORDS = {
    "cat": 5,
    "cats": 5,
    "kitten": 5,
    "kittens": 5,
    "kitty": 5,
    "kitties": 5,
    "feline": 5,

    "dog": 5,
    "dogs": 5,
    "puppy": 5,
    "puppies": 5,
    "pup": 5,
    "canine": 5,

    "pet": 4,
    "pets": 4,
    "animal": 4,
    "animals": 4,

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
    return datetime.now(
        timezone.utc
    ).isoformat()


# ============================================================
# CAPTION CLEANING
# ============================================================

def clean_caption(raw_caption):
    """
    Convert Mastodon HTML into clean plain text.

    Rules:

    1. Remove script/style blocks.
    2. Preserve paragraph/line boundaries.
    3. Remove remaining HTML.
    4. Decode HTML entities.
    5. Remove URLs.
    6. Remove hashtags.
    7. Preserve meaningful line breaks.
    8. Remove empty hashtag-only lines.
    9. Collapse excessive blank lines.

    Example:

        <p><a href="...">#Dog</a> #Pets</p>
        <p>Sunday afternoon</p>

    becomes:

        Sunday afternoon
    """

    if not raw_caption:
        return ""

    text = str(raw_caption)

    # --------------------------------------------------------
    # Remove script/style blocks.
    # --------------------------------------------------------

    text = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    # --------------------------------------------------------
    # Convert common block-level HTML into line breaks.
    # --------------------------------------------------------

    text = re.sub(
        r"</?(p|div|br|li|blockquote|h[1-6])\b[^>]*>",
        "\n",
        text,
        flags=re.IGNORECASE
    )

    # --------------------------------------------------------
    # Remove remaining HTML tags.
    # --------------------------------------------------------

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    # --------------------------------------------------------
    # Decode HTML entities.
    # --------------------------------------------------------

    text = html.unescape(text)

    # --------------------------------------------------------
    # Remove URLs.
    # --------------------------------------------------------

    text = re.sub(
        r"https?://\S+",
        "",
        text,
        flags=re.IGNORECASE
    )

    # --------------------------------------------------------
    # Remove hashtags.
    #
    # Supports normal Unicode word characters too.
    # Examples:
    #
    # #Dog
    # #DogsOfMastodon
    # #Ú¯Ø±Ø¨Ù
    # --------------------------------------------------------

    text = re.sub(
        r"(?<!\w)#[\w]+",
        "",
        text,
        flags=re.UNICODE
    )

    # --------------------------------------------------------
    # Clean each line individually.
    #
    # This deliberately preserves line boundaries instead of
    # flattening the entire caption into one paragraph.
    # --------------------------------------------------------

    lines = []

    for line in text.splitlines():

        line = re.sub(
            r"[ \t]+",
            " ",
            line
        ).strip()

        # Remove lines that contain nothing after hashtag/URL
        # cleaning.
        if not line:
            continue

        lines.append(line)

    # --------------------------------------------------------
    # Rebuild caption.
    # --------------------------------------------------------

    text = "\n".join(lines)

    # --------------------------------------------------------
    # Collapse excessive blank lines.
    # --------------------------------------------------------

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


def telegram_caption(raw_caption):
    """
    Produce the Telegram-ready source caption.

    @utcutie is intentionally appended later by the
    publishing workflow.
    """

    text = clean_caption(
        raw_caption
    )

    if not text:
        return ""

    if len(text) <= MAX_CAPTION_LENGTH:
        return text

    # --------------------------------------------------------
    # Prefer a natural boundary.
    # --------------------------------------------------------

    shortened = text[
        :MAX_CAPTION_LENGTH
    ]

    last_newline = shortened.rfind(
        "\n"
    )

    last_space = shortened.rfind(
        " "
    )

    # Prefer a paragraph/line boundary.
    if last_newline >= int(
        MAX_CAPTION_LENGTH * 0.75
    ):
        shortened = shortened[
            :last_newline
        ]

    elif last_space >= int(
        MAX_CAPTION_LENGTH * 0.75
    ):
        shortened = shortened[
            :last_space
        ]

    return shortened.rstrip()


# ============================================================
# TEXT / RELEVANCE
# ============================================================

def normalize_text(text):

    if not text:
        return ""

    text = clean_caption(
        text
    )

    return text.lower()


def tokenize(text):

    return set(
        re.findall(
            r"[a-z0-9]+",
            normalize_text(text)
        )
    )


def animal_relevance(text):

    tokens = tokenize(
        text
    )

    score = 0

    for keyword, value in ANIMAL_KEYWORDS.items():

        if keyword in tokens:
            score += value

    return score


# ============================================================
# ENGAGEMENT
# ============================================================

def engagement_score(
    favourites,
    reblogs,
    replies
):

    favourites = max(
        0,
        int(favourites or 0)
    )

    reblogs = max(
        0,
        int(reblogs or 0)
    )

    replies = max(
        0,
        int(replies or 0)
    )

    score = 0.0

    score += min(
        40.0,
        favourites ** 0.5
    )

    score += min(
        30.0,
        reblogs ** 0.5 * 1.5
    )

    score += min(
        15.0,
        replies ** 0.5
    )

    return round(
        score,
        3
    )


# ============================================================
# RECENCY
# ============================================================

def recency_score(created_at):

    if not created_at:
        return 0.0

    try:

        created = datetime.fromisoformat(
            created_at.replace(
                "Z",
                "+00:00"
            )
        )

        age_hours = (
            datetime.now(
                timezone.utc
            ) - created
        ).total_seconds() / 3600

        age_hours = max(
            0,
            age_hours
        )

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


# ============================================================
# VIDEO QUALITY
# ============================================================

def quality_score(
    width,
    height
):

    try:

        width = int(
            width or 0
        )

        height = int(
            height or 0
        )

    except Exception:

        return 0.0

    pixels = (
        width * height
    )

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


# ============================================================
# CAPTION QUALITY
# ============================================================

def caption_quality_score(
    caption
):

    text = str(
        caption or ""
    ).strip()

    if not text:
        return 0.0

    score = 0.0

    # A short meaningful caption is preferable to an empty one.
    if len(text) >= 10:
        score += 2.0

    if len(text) >= 30:
        score += 1.0

    # Preserve captions that actually contain multiple words.
    words = re.findall(
        r"\S+",
        text
    )

    if len(words) >= 4:
        score += 1.0

    # Avoid rewarding captions that are essentially just symbols.
    alphanumeric = re.findall(
        r"[A-Za-z0-9\u0600-\u06FF]",
        text
    )

    if len(alphanumeric) >= 10:
        score += 1.0

    return min(
        5.0,
        score
    )


# ============================================================
# JSON
# ============================================================

def load_json(
    path,
    default
):

    if not path.exists():
        return default

    try:

        with path.open(
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return default


def save_json(
    path,
    data
):

    with path.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# DISCOVERY
# ============================================================

def discover_candidates():

    candidates = []

    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 "
            "UTCutie-Mastodon-Discovery/3.0"
        )
    })

    for instance in INSTANCES:

        print()
        print("=" * 70)
        print(
            f"INSTANCE: {instance}"
        )
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
                    timeout=REQUEST_TIMEOUT
                )

                print(
                    f"{instance} #{hashtag}: "
                    f"HTTP {response.status_code}"
                )

                if response.status_code != 200:
                    continue

                statuses = response.json()

                if not isinstance(
                    statuses,
                    list
                ):
                    continue

                for status in statuses:

                    if not isinstance(
                        status,
                        dict
                    ):
                        continue

                    media = status.get(
                        "media_attachments"
                    )

                    if not isinstance(
                        media,
                        list
                    ):
                        continue

                    for attachment in media:

                        if not isinstance(
                            attachment,
                            dict
                        ):
                            continue

                        if attachment.get(
                            "type"
                        ) != "video":
                            continue

                        media_url = attachment.get(
                            "url"
                        )

                        if not media_url:
                            continue

                        account = status.get(
                            "account"
                        )

                        if not isinstance(
                            account,
                            dict
                        ):
                            account = {}

                        meta = attachment.get(
                            "meta"
                        )

                        if not isinstance(
                            meta,
                            dict
                        ):
                            meta = {}

                        original = meta.get(
                            "original"
                        )

                        if not isinstance(
                            original,
                            dict
                        ):
                            original = {}

                        raw_caption = status.get(
                            "content",
                            ""
                        )

                        clean = telegram_caption(
                            raw_caption
                        )

                        candidate = {

                            "status_id": status.get(
                                "id"
                            ),

                            "status_url": status.get(
                                "url"
                            ),

                            "instance": instance,

                            "created_at": status.get(
                                "created_at"
                            ),

                            "caption": clean,

                            "account": account.get(
                                "acct"
                            ),

                            "account_display_name": (
                                account.get(
                                    "display_name"
                                )
                            ),

                            "media_url": media_url,

                            "media_preview_url": (
                                attachment.get(
                                    "preview_url"
                                )
                            ),

                            "media_type": (
                                attachment.get(
                                    "type"
                                )
                            ),

                            "width": original.get(
                                "width"
                            ),

                            "height": original.get(
                                "height"
                            ),

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

                            # These are the post's ACTUAL Mastodon tags.
                            # The discovery hashtag is deliberately kept
                            # separate and is never treated as evidence.
                            "status_tags": [
                                str(tag.get("name", "")).strip().lower()
                                for tag in (status.get("tags") or [])
                                if isinstance(tag, dict)
                                and tag.get("name")
                            ],
                        }

                        candidates.append(
                            candidate
                        )

            except Exception as exc:

                print(
                    f"ERROR {instance} "
                    f"#{hashtag}: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

    return candidates


# ============================================================
# ============================================================
# CANONICAL POST DEDUPLICATION
# ============================================================

def normalize_status_url(url):
    if not url:
        return ""

    value = str(url).strip()

    # brid.gy mirrors: keep the underlying source post URL.
    if "/r/https://" in value:
        value = value.split("/r/", 1)[1]

    value = value.split("?", 1)[0].split("#", 1)[0].rstrip("/")

    return value


def canonical_status_key(candidate):
    status_url = normalize_status_url(
        candidate.get("status_url")
    )

    if status_url:
        return f"status:{status_url}"

    media_url = str(
        candidate.get("media_url") or ""
    ).split("?", 1)[0]

    if media_url:
        return f"media:{media_url}"

    return ""


def candidate_quality_key(candidate):
    width = int(candidate.get("width") or 0)
    height = int(candidate.get("height") or 0)
    pixels = width * height

    # Prefer higher resolution, then smaller files when resolution is equal.
    file_size = int(candidate.get("file_size") or 0)

    return (
        pixels,
        -file_size,
        float(candidate.get("favourites") or 0),
        float(candidate.get("reblogs") or 0),
    )


def deduplicate_candidates(candidates):
    best = {}

    for candidate in candidates:
        key = canonical_status_key(candidate)

        if not key:
            continue

        current = best.get(key)

        if current is None:
            best[key] = candidate
            continue

        if candidate_quality_key(candidate) > candidate_quality_key(current):
            best[key] = candidate

    unique = list(best.values())

    return unique


# ============================================================
# CONTENT / RELEVANCE GATE
# ============================================================

ANIMAL_TERMS = {
    "cat", "cats", "kitten", "kittens", "kitty", "kitties",
    "feline", "dog", "dogs", "puppy", "puppies", "pup", "canine",
    "pet", "pets", "animal", "animals",
    "bird", "birds", "parrot", "parrots", "parakeet", "cockatiel",
    "duck", "ducks", "goose", "geese", "chicken", "chickens",
    "rabbit", "rabbits", "bunny", "bunnies", "hamster", "hamsters",
    "raccoon", "raccoons", "tiger", "tigers", "lion", "lions",
    "guinea", "horse", "horses", "pony", "ponies",
    "cow", "cows", "calf", "sheep", "goat", "goats",
    "deer", "fox", "foxes", "wolf", "wolves", "bear", "bears",
    "panda", "monkey", "monkeys", "otter", "seal", "dolphin",
    "turtle", "turtles", "snake", "snakes", "lizard", "frog",
    "frogs", "hedgehog", "hedgehogs", "chihuahua", "labrador",
    "retriever", "husky", "corgi", "poodle", "wildlife",
}

CONTEXT_TERMS = {
    "pet", "pets", "paw", "paws", "tail", "whiskers", "zoomies",
    "play", "playing", "playtime", "sleeping", "sleepy",
    "cuddle", "cuddling", "hug", "hugging", "kiss", "kissing",
    "treat", "toy", "toys", "fetch", "leash", "walk", "walking",
    "run", "running", "funny", "hilarious", "cute", "adorable",
    "aww", "silly", "goofy", "laugh", "laughing", "meme",
    "reaction", "unexpected", "chaos", "derp", "wholesome",
    "sweet", "heartwarming", "playful", "surprise", "happy",
    "joy", "love", "friendship", "hideandseek", "justforlaughs",
}

ADVOCACY_TERMS = {
    "rescue", "rescued", "rescuing", "adopt", "adopted", "adoption",
    "shelter", "foster", "fostering", "animal rights",
    "animal-rights", "meat farm", "meatfarm", "slaughter",
    "campaign", "donate", "donation", "fundraiser", "fundraising",
    "sanctuary", "save animals", "save the animals",
}

IRRELEVANT_TERMS = {
    "org chart", "orgchart", "hierarchy", "sociopath", "leadership",
    "management", "manager", "workplace", "corporate", "company",
    "career", "linkedin", "audit", "business strategy",
    "football", "soccer", "basketball", "baseball", "hockey",
    "politics", "election", "government",
}

def text_tokens(text):
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))

def contains_phrase(text, phrase):
    return phrase.lower() in str(text or "").lower()

def content_gate(candidate):
    caption = str(candidate.get("caption") or "")
    actual_tags = {
        str(x).lower().strip()
        for x in (candidate.get("status_tags") or [])
        if x
    }

    caption_tokens = text_tokens(caption)

    # Hashtags/tags are discovery signals, never sufficient animal evidence.
    # Generic tags such as pets/animals are especially weak and cannot qualify.
    generic_animal_tags = {
        "pet", "pets", "animal", "animals", "cuteanimals",
        "funnyanimals", "petsofthefediverse"
    }

    caption_animal_hits = {
        term for term in ANIMAL_TERMS
        if term in caption_tokens
    }

    specific_tag_animal_hits = {
        term for term in ANIMAL_TERMS
        if term not in generic_animal_tags
        and term in actual_tags
    }

    caption_context_hits = {
        term for term in CONTEXT_TERMS
        if term in caption_tokens
    }

    text = caption.lower()

    advocacy_hits = {
        term for term in ADVOCACY_TERMS
        if contains_phrase(text, term)
    }

    irrelevant_hits = {
        term for term in IRRELEVANT_TERMS
        if contains_phrase(text, term)
    }

    if len(advocacy_hits) >= 2:
        return False, 0, "rescue/advocacy content"

    if "meat farm" in text or "animal rights" in text:
        return False, 0, "advocacy campaign content"

    # Explicit non-animal subject matter is rejected before scoring.
    if irrelevant_hits and not caption_animal_hits:
        return False, 0, "irrelevant non-animal content"

    # Primary rule: the caption itself must identify an animal.
    # A specific animal hashtag may supplement a caption that clearly describes
    # an animal/pet context, but tags alone can never pass the gate.
    if not caption_animal_hits:
        if not specific_tag_animal_hits or not caption_context_hits:
            return False, 0, "no animal evidence"

    animal_hits = caption_animal_hits | specific_tag_animal_hits
    score = min(60, len(animal_hits) * 18)

    if caption_context_hits:
        score += min(25, len(caption_context_hits) * 5)

    if caption_animal_hits:
        score += 15

    return True, min(100, score), "passed"

def download_and_validate(
    candidate
):

    media_url = candidate.get(
        "media_url"
    )

    if not media_url:
        return None

    temp_path = None

    try:

        with tempfile.NamedTemporaryFile(
            suffix=".video",
            delete=False
        ) as temp_file:

            temp_path = Path(
                temp_file.name
            )

        print()
        print(
            "Downloading media:",
            media_url
        )
        print(
            "Source post:",
            candidate.get(
                "status_url"
            )
        )

        response = requests.get(
            media_url,
            stream=True,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "UTCutie-Mastodon-Discovery/3.0"
                )
            }
        )

        if response.status_code != 200:

            print(
                "  HTTP failure:",
                response.status_code
            )

            return None

        content_type = (
            response.headers.get(
                "content-type",
                ""
            ).lower()
        )

        if (
            "video" not in content_type
            and "octet-stream"
            not in content_type
        ):

            print(
                "  Not a video content type:",
                content_type
            )

            return None

        content_length = (
            response.headers.get(
                "content-length"
            )
        )

        if content_length:

            try:

                if int(
                    content_length
                ) > MAX_FILE_SIZE:

                    print(
                        "  File too large."
                    )

                    return None

            except ValueError:
                pass

        total_bytes = 0

        with temp_path.open(
            "wb"
        ) as output:

            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):

                if not chunk:
                    continue

                total_bytes += len(
                    chunk
                )

                if total_bytes > MAX_FILE_SIZE:

                    print(
                        "  File exceeded 48 MB."
                    )

                    return None

                output.write(
                    chunk
                )

        if total_bytes == 0:

            print(
                "  Empty file."
            )

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
            timeout=30
        )

        if probe.returncode != 0:

            print(
                "  ffprobe failed."
            )

            return None

        try:

            metadata = json.loads(
                probe.stdout
            )

        except Exception:

            print(
                "  Invalid ffprobe output."
            )

            return None

        format_data = metadata.get(
            "format"
        )

        if not isinstance(
            format_data,
            dict
        ):
            format_data = {}

        streams = metadata.get(
            "streams"
        )

        if not isinstance(
            streams,
            list
        ):
            streams = []

        duration = format_data.get(
            "duration"
        )

        if duration is None:

            print(
                "  Duration unavailable."
            )

            return None

        duration = float(
            duration
        )

        if duration < MIN_DURATION:

            print(
                f"  Too short: "
                f"{duration:.2f}s"
            )

            return None

        if duration > MAX_DURATION:

            print(
                f"  Too long: "
                f"{duration:.2f}s"
            )

            return None

        width = 0
        height = 0
        has_video_stream = False

        for stream in streams:

            if not isinstance(
                stream,
                dict
            ):
                continue

            if stream.get(
                "codec_type"
            ) != "video":
                continue

            has_video_stream = True

            try:

                width = int(
                    stream.get(
                        "width"
                    ) or 0
                )

            except Exception:

                width = 0

            try:

                height = int(
                    stream.get(
                        "height"
                    ) or 0
                )

            except Exception:

                height = 0

            break

        if not has_video_stream:

            print(
                "  No video stream."
            )

            return None

        if (
            width <= 0
            or height <= 0
        ):

            print(
                "  Invalid video dimensions."
            )

            return None

        # ----------------------------------------------------
        # SHA-256
        # ----------------------------------------------------

        file_hash = hashlib.sha256()

        with temp_path.open(
            "rb"
        ) as f:

            while True:

                chunk = f.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                file_hash.update(
                    chunk
                )

        sha256 = file_hash.hexdigest()

        result = dict(
            candidate
        )

        result["duration"] = round(
            duration,
            3
        )

        result["file_size"] = (
            total_bytes
        )

        result["file_size_mb"] = round(
            total_bytes
            / (1024 * 1024),
            3
        )

        result["width"] = width
        result["height"] = height

        result["sha256"] = sha256

        # Final caption cleanup.
        result["caption"] = telegram_caption(
            result.get(
                "caption",
                ""
            )
        )

        return result

    except requests.RequestException as exc:

        print(
            "  Download error:",
            type(exc).__name__,
            exc
        )

        return None

    except subprocess.TimeoutExpired:

        print(
            "  ffprobe timeout."
        )

        return None

    except Exception as exc:

        print(
            "  Validation error:",
            type(exc).__name__,
            exc
        )

        return None

    finally:

        if (
            temp_path
            and temp_path.exists()
        ):

            try:

                temp_path.unlink()

            except Exception:

                pass


# ============================================================
# HISTORY
#
# IMPORTANT:
# Discovery READS history.json.
# Discovery NEVER writes to it.
#
# Successful publication is recorded by the publishing
# workflow only after Telegram confirms success.
# ============================================================

def history_keys(
    history
):

    keys = set()

    if not isinstance(
        history,
        list
    ):
        return keys

    for item in history:

        if not isinstance(
            item,
            dict
        ):
            continue

        for field in (
            "sha256",
            "media_url",
            "status_url",
        ):

            value = item.get(
                field
            )

            if value:

                if field == "status_url":
                    value = normalize_status_url(value)

                keys.add(
                    f"{field}:{value}"
                )

    return keys


def already_seen(
    candidate,
    keys
):

    checks = [

        (
            "sha256",
            candidate.get(
                "sha256"
            )
        ),

        (
            "media_url",
            candidate.get(
                "media_url"
            )
        ),

        (
            "status_url",
            candidate.get(
                "status_url"
            )
        ),
    ]

    for field, value in checks:

        if (
            value
            and f"{field}:{value}" in keys
        ):

            return True

    return False


# ============================================================
# SHA-256 DEDUPLICATION
# ============================================================

def deduplicate_by_sha256(
    candidates
):

    unique = []

    seen_hashes = set()

    for candidate in candidates:

        sha256 = candidate.get(
            "sha256"
        )

        if not sha256:
            continue

        if sha256 in seen_hashes:

            print(
                "  Removing duplicate media:",
                candidate.get(
                    "status_url"
                )
            )

            continue

        seen_hashes.add(
            sha256
        )

        unique.append(
            candidate
        )

    return unique


# ============================================================
# ============================================================
# SCORING


def freshness_days(created_at):
    if not created_at:
        return 9999.0
    try:
        created = datetime.fromisoformat(
            str(created_at).replace("Z", "+00:00")
        )
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_seconds = (
            datetime.now(timezone.utc) - created
        ).total_seconds()
        return max(0.0, age_seconds / 86400.0)
    except Exception:
        return 9999.0


def freshness_tier(days):
    if days <= PRIMARY_DAYS:
        return "primary"
    if days <= SECONDARY_DAYS:
        return "secondary"
    if days <= EMERGENCY_DAYS:
        return "emergency"
    return "reject"


# ============================================================

def score_candidate(candidate):
    caption = str(candidate.get("caption") or "")
    tags = " ".join(candidate.get("status_tags") or [])

    relevance_text = f"{caption} {tags}"

    relevance = animal_relevance(relevance_text)

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

    caption_quality = caption_quality_score(
        caption
    )

    days = freshness_days(
        candidate.get("created_at")
    )

    tier = freshness_tier(days)

    # Penalize inefficient huge files without rejecting them.
    file_size_mb = float(
        candidate.get("file_size_mb") or 0
    )
    duration = float(
        candidate.get("duration") or 0
    )

    efficiency_penalty = 0

    if duration > 0 and file_size_mb > 35 and duration < 30:
        efficiency_penalty = 4

    # Relevance is dominant; fresh content gets a meaningful bonus.
    total = (
        relevance * 3.0
        + engagement * 0.9
        + recency * 1.2
        + quality * 1.0
        + caption_quality
        - efficiency_penalty
    )

    result = dict(candidate)

    result["animal_relevance"] = round(relevance, 3)
    result["engagement_score"] = round(engagement, 3)
    result["recency_score"] = round(recency, 3)
    result["quality_score"] = round(quality, 3)
    result["caption_quality_score"] = round(caption_quality, 3)
    result["freshness_days"] = round(days, 3)
    result["freshness_tier"] = tier
    result["total_score"] = round(total, 3)

    return result


# ============================================================
# DIVERSE FINAL SELECTION
# ============================================================

def select_diverse_candidates(candidates):
    selected = []
    account_counts = {}
    instance_counts = {}
    seen_keys = set()

    for candidate in candidates:
        if len(selected) >= MAX_SELECTED:
            break

        key = canonical_status_key(candidate)

        if not key or key in seen_keys:
            continue

        account = (
            candidate.get("account")
            or candidate.get("account_display_name")
            or "unknown-account"
        )

        instance = (
            candidate.get("instance")
            or "unknown-instance"
        )

        if account_counts.get(account, 0) >= MAX_VIDEOS_PER_ACCOUNT:
            continue

        if instance_counts.get(instance, 0) >= MAX_VIDEOS_PER_INSTANCE:
            continue

        selected.append(candidate)
        seen_keys.add(key)

        account_counts[account] = (
            account_counts.get(account, 0) + 1
        )

        instance_counts[instance] = (
            instance_counts.get(instance, 0) + 1
        )

    # Diversity is a preference. If the pool is smaller, use all remaining
    # unique candidates rather than manufacturing a quota.
    if len(selected) < MAX_SELECTED:
        for candidate in candidates:
            if len(selected) >= MAX_SELECTED:
                break

            key = canonical_status_key(candidate)

            if not key or key in seen_keys:
                continue

            selected.append(candidate)
            seen_keys.add(key)

    return selected


# DIVERSE FINAL SELECTION
# ============================================================

def select_diverse_candidates(
    candidates
):

    selected = []

    account_counts = {}
    instance_counts = {}

    # --------------------------------------------------------
    # First pass:
    #
    # Take the highest-ranked candidates while respecting
    # diversity limits.
    # --------------------------------------------------------

    for candidate in candidates:

        if len(selected) >= MAX_SELECTED:
            break

        account = (
            candidate.get(
                "account"
            )
            or candidate.get(
                "account_display_name"
            )
            or "unknown-account"
        )

        instance = (
            candidate.get(
                "instance"
            )
            or "unknown-instance"
        )

        account_count = account_counts.get(
            account,
            0
        )

        instance_count = instance_counts.get(
            instance,
            0
        )

        if (
            account_count
            >= MAX_VIDEOS_PER_ACCOUNT
        ):
            continue

        if (
            instance_count
            >= MAX_VIDEOS_PER_INSTANCE
        ):
            continue

        selected.append(
            candidate
        )

        account_counts[
            account
        ] = account_count + 1

        instance_counts[
            instance
        ] = instance_count + 1

    # --------------------------------------------------------
    # Second pass:
    #
    # If diversity limits prevented us from reaching 20,
    # fill remaining positions with the highest-ranked
    # candidates not already selected.
    #
    # This means diversity is a preference, NOT a quota.
    # --------------------------------------------------------

    if len(selected) < MAX_SELECTED:

        selected_ids = {
            candidate.get(
                "sha256"
            )
            for candidate in selected
        }

        for candidate in candidates:

            if len(selected) >= MAX_SELECTED:
                break

            candidate_id = candidate.get(
                "sha256"
            )

            if candidate_id in selected_ids:
                continue

            selected.append(
                candidate
            )

            selected_ids.add(
                candidate_id
            )

    return selected


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("UTCutie Mastodon Video Discovery")
    print("=" * 70)
    print()

    print("Starting discovery...")
    raw_candidates = discover_candidates()

    print()
    print(f"RAW VIDEO CANDIDATES: {len(raw_candidates)}")

    # Canonical post dedup happens BEFORE expensive media validation.
    candidates = deduplicate_candidates(raw_candidates)

    print(
        f"UNIQUE CANONICAL POST CANDIDATES: {len(candidates)}"
    )

    save_json(
        CANDIDATES_FILE,
        candidates
    )

    # Content gate before download: this removes false positives such as
    # business/workplace posts and rescue campaigns without wasting bandwidth.
    gated = []
    rejected_reasons = {}

    for candidate in candidates:
        accepted, content_value, reason = content_gate(candidate)

        candidate = dict(candidate)
        candidate["content_value"] = content_value

        if not accepted:
            rejected_reasons[reason] = (
                rejected_reasons.get(reason, 0) + 1
            )
            continue

        gated.append(candidate)

    print()
    print(
        f"CONTENT-GATE PASSED: {len(gated)}"
    )

    if rejected_reasons:
        print("CONTENT-GATE REJECTIONS:")
        for reason, count in sorted(
            rejected_reasons.items(),
            key=lambda item: item[1],
            reverse=True
        ):
            print(f"  {reason}: {count}")

    print()
    print("Starting media validation...")

    validated = []

    for index, candidate in enumerate(
        gated,
        start=1
    ):
        print(
            f"[{index}/{len(gated)}]"
        )

        result = download_and_validate(
            candidate
        )

        if result is None:
            continue

        scored = score_candidate(
            result
        )

        # Re-run the content gate after caption cleanup/media validation.
        accepted, content_value, reason = content_gate(
            scored
        )

        if not accepted:
            print(
                "  Rejected after validation:",
                reason
            )
            continue

        scored["content_value"] = content_value

        days = scored.get(
            "freshness_days",
            9999
        )

        tier = scored.get(
            "freshness_tier",
            "reject"
        )

        if tier == "reject":
            print("  Too old.")
            continue

        if tier == "emergency":
            if (
                content_value < EMERGENCY_MIN_CONTENT_VALUE
                or scored.get("total_score", 0) < EMERGENCY_MIN_SCORE
            ):
                print(
                    "  Emergency-age candidate is not strong enough."
                )
                continue

        elif content_value < MIN_CONTENT_VALUE:
            print(
                "  Content value too low."
            )
            continue

        validated.append(scored)

    print()
    print(
        f"VALIDATED VIDEOS: {len(validated)}"
    )

    # Final canonical post dedup after validation. If different media copies
    # of the same post survived, retain the best one only.
    best_by_key = {}

    for candidate in validated:
        key = canonical_status_key(candidate)

        if not key:
            continue

        current = best_by_key.get(key)

        if current is None:
            best_by_key[key] = candidate
            continue

        candidate_rank = (
            candidate.get("quality_score", 0),
            candidate.get("content_value", 0),
            candidate.get("total_score", 0),
            -candidate.get("file_size", 10**18),
        )

        current_rank = (
            current.get("quality_score", 0),
            current.get("content_value", 0),
            current.get("total_score", 0),
            -current.get("file_size", 10**18),
        )

        if candidate_rank > current_rank:
            best_by_key[key] = candidate

    validated = list(best_by_key.values())

    save_json(
        VALIDATED_FILE,
        validated
    )

    print(
        f"UNIQUE VALIDATED VIDEOS: {len(validated)}"
    )

    history = load_json(
        HISTORY_FILE,
        []
    )

    if not isinstance(history, list):
        history = []

    seen_keys = history_keys(history)

    # Also compare normalized canonical status URLs against history.
    historical_statuses = {
        normalize_status_url(item.get("status_url"))
        for item in history
        if isinstance(item, dict)
        and item.get("status_url")
    }

    fresh = []

    for candidate in validated:
        if already_seen(candidate, seen_keys):
            continue

        canonical = normalize_status_url(
            candidate.get("status_url")
        )

        if canonical and canonical in historical_statuses:
            continue

        fresh.append(candidate)

    print(
        f"FRESH VIDEOS AFTER HISTORY FILTER: {len(fresh)}"
    )

    # Rank freshness tiers separately. We never let an old mediocre video
    # outrank a fresh good one merely because it has more engagement.
    primary = sorted(
        [
            x for x in fresh
            if x.get("freshness_tier") == "primary"
        ],
        key=lambda x: (
            x.get("total_score", 0),
            x.get("content_value", 0),
            x.get("quality_score", 0),
            x.get("engagement_score", 0),
        ),
        reverse=True,
    )

    secondary = sorted(
        [
            x for x in fresh
            if x.get("freshness_tier") == "secondary"
        ],
        key=lambda x: (
            x.get("total_score", 0),
            x.get("content_value", 0),
            x.get("quality_score", 0),
            x.get("engagement_score", 0),
        ),
        reverse=True,
    )

    emergency = sorted(
        [
            x for x in fresh
            if x.get("freshness_tier") == "emergency"
        ],
        key=lambda x: (
            x.get("total_score", 0),
            x.get("content_value", 0),
            x.get("quality_score", 0),
            x.get("engagement_score", 0),
        ),
        reverse=True,
    )

    print(
        f"PRIMARY (0-{PRIMARY_DAYS} days): {len(primary)}"
    )
    print(
        f"SECONDARY ({PRIMARY_DAYS + 1}-{SECONDARY_DAYS} days): {len(secondary)}"
    )
    print(
        f"EMERGENCY ({SECONDARY_DAYS + 1}-{EMERGENCY_DAYS} days): {len(emergency)}"
    )

    selected = select_diverse_candidates(
        primary + secondary + emergency
    )

    # One last absolute canonical-status guarantee.
    final_selected = []
    final_keys = set()

    for candidate in selected:
        key = canonical_status_key(candidate)

        if not key or key in final_keys:
            continue

        final_keys.add(key)
        final_selected.append(candidate)

        if len(final_selected) >= MAX_SELECTED:
            break

    save_json(
        SELECTED_FILE,
        final_selected
    )

    print()
    print("=" * 70)
    print(
        f"SELECTED UNIQUE VIDEOS: {len(final_selected)}"
    )
    print("=" * 70)

    for index, candidate in enumerate(
        final_selected,
        start=1
    ):
        print()
        print(
            f"{index}. "
            f"score={candidate.get('total_score')} "
            f"content={candidate.get('content_value')} "
            f"age={candidate.get('freshness_days')}d "
            f"duration={candidate.get('duration')}s "
            f"size={candidate.get('file_size_mb')}MB"
        )

        print(
            "   Account:",
            candidate.get("account")
        )

        print(
            "   Instance:",
            candidate.get("instance")
        )

        print(
            "   URL:",
            candidate.get("status_url")
        )

        print(
            "   SHA256:",
            candidate.get("sha256")
        )

        print(
            "   Caption:",
            candidate.get("caption", "")[:300]
        )

    print()
    print(
        "Publication history was NOT modified."
    )

    print()
    print("=" * 70)
    print("DISCOVERY COMPLETE")
    print("=" * 70)
    print(
        f"Raw candidates: {len(raw_candidates)}"
    )
    print(
        f"Canonical candidates: {len(candidates)}"
    )
    print(
        f"Content-gate passed: {len(gated)}"
    )
    print(
        f"Validated videos: {len(validated)}"
    )
    print(
        f"Fresh videos: {len(fresh)}"
    )
    print(
        f"Selected unique videos: {len(final_selected)}"
    )
    print(
        f"Published-history entries: {len(history)}"
    )


if __name__ == "__main__":
    main()
