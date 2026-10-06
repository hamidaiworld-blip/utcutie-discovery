import hashlib
import html
import json
import math
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests


# ============================================================
# CONFIG
# ============================================================

MAX_VIDEOS = 20

MIN_DURATION = 15
MAX_DURATION = 180
MAX_FILE_SIZE = 48 * 1024 * 1024

# Freshness policy:
# 0-14 days = preferred
# 15-30 days = fallback
# >30 days = reject
PREFERRED_DAYS = 14
FALLBACK_DAYS = 30

MAX_VIDEOS_PER_ACCOUNT = 2
MAX_VIDEOS_PER_INSTANCE = 8

REQUEST_TIMEOUT = 25

# Minimum overall content value required after validation.
MIN_CONTENT_VALUE = 45

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
# CONTENT DICTIONARIES
# ============================================================

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
    "poodle",
    "felines",
}


PET_CONTEXT_TERMS = {
    "pet",
    "pets",
    "petlife",
    "petlover",
    "petlove",
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
    "treat",
    "toys",
    "toy",
    "fetch",
    "leash",
    "puppy",
    "kitten",
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
    "fail",
    "fails",
    "reaction",
    "reacts",
    "unexpected",
    "watch",
    "zoomies",
    "chaos",
    "derp",
    "wholesome",
    "sweet",
    "heartwarming",
    "playful",
    "play",
    "playing",
    "surprise",
    "surprised",
    "happy",
    "joy",
    "lovely",
    "love",
    "friendship",
}


ACTIVITY_TERMS = {
    "play",
    "playing",
    "playtime",
    "toy",
    "toys",
    "chase",
    "chasing",
    "zoomies",
    "sleep",
    "sleeping",
    "sleepy",
    "cuddle",
    "cuddling",
    "hug",
    "hugging",
    "kiss",
    "kissing",
    "walk",
    "walking",
    "run",
    "running",
    "fetch",
    "eat",
    "eating",
    "dinner",
    "breakfast",
    "bath",
    "bathing",
    "jump",
    "jumping",
    "dance",
    "dancing",
    "sing",
    "singing",
    "talk",
    "talking",
    "lick",
    "licking",
    "steal",
    "stole",
    "friend",
    "friends",
    "family",
}


HEARTWARMING_TERMS = {
    "love",
    "lovely",
    "sweet",
    "wholesome",
    "heartwarming",
    "precious",
    "adorable",
    "happy",
    "joy",
    "friend",
    "friends",
    "family",
    "best friend",
    "old dog",
    "old cat",
    "beautiful",
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
    "church",
    "mosque",
    "campaign",
    "activism",
    "activist",
    "protest",
    "protests",
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
    "seminar",
    "infographic",
    "diagram",
    "chart",
    "tutorial",
    "course",
    "webinar",
    "podcast",
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
    "follow me",
    "check out my",
    "visit our",
    "visit my",
    "donate",
    "donation",
    "donations",
    "fundraiser",
    "fundraising",
    "support our",
    "support us",
    "go fund me",
    "gofundme",
    "patreon",
    "venmo",
    "paypal",
    "cashapp",
}


RESCUE_CAMPAIGN_TERMS = {
    "rescue",
    "rescued",
    "animal rescue",
    "cat rescue",
    "dog rescue",
    "pet rescue",
    "foster",
    "fostered",
    "adoption",
    "adopt",
    "adoptable",
    "shelter",
    "shelter dog",
    "shelter cat",
    "rehoming",
    "rehomed",
    "fundraiser",
    "fundraising",
    "donate",
    "donation",
    "donations",
    "wishlist",
    "volunteer",
    "volunteers",
    "nonprofit",
    "non-profit",
    "501c3",
}


ART_PRODUCT_TERMS = {
    "art",
    "artist",
    "artwork",
    "portrait",
    "painting",
    "painted",
    "drawing",
    "illustration",
    "illustrated",
    "sketch",
    "commission",
    "custom",
    "customized",
    "foiled",
    "foil",
    "print",
    "prints",
    "poster",
    "posters",
    "sticker",
    "stickers",
    "merch",
    "merchandise",
    "shirt",
    "t-shirt",
    "mug",
    "calendar",
    "book",
    "etsy",
    "gallery",
    "design",
    "designer",
    "craft",
    "crafts",
    "product",
    "products",
    "store",
    "shop",
    "unboxing",
    "unbox",
    "package",
    "packaging",
    "haul",
}


# ============================================================
# TEXT HELPERS
# ============================================================

def normalize_text(value):
    if not value:
        return ""

    value = html.unescape(str(value))

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip().lower()


def word_hits(text, terms):
    normalized = normalize_text(text)

    hits = []

    for term in terms:
        term = normalize_text(term)

        if not term:
            continue

        pattern = (
            r"(?<!\w)"
            + re.escape(term)
            + r"(?!\w)"
        )

        if re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE,
        ):
            hits.append(term)

    return hits


def clean_caption(raw_html):
    if not raw_html:
        return ""

    text = str(raw_html)

    # Remove scripts/styles.
    text = re.sub(
        r"<(script|style)[^>]*>.*?</\1>",
        "",
        text,
        flags=re.I | re.S,
    )

    # Preserve logical line breaks.
    text = re.sub(
        r"</?(p|div|br|li|blockquote|h[1-6])[^>]*>",
        "\n",
        text,
        flags=re.I,
    )

    # Remove remaining HTML.
    text = re.sub(
        r"<[^>]+>",
        "",
        text,
    )

    text = html.unescape(text)

    # Remove URLs.
    text = re.sub(
        r"https?://\S+|www\.\S+",
        "",
        text,
        flags=re.I,
    )

    # Remove hashtags.
    text = re.sub(
        r"(?<!\w)#[\w\u0080-\uffff]+",
        "",
        text,
        flags=re.UNICODE,
    )

    # Remove phone numbers.
    text = re.sub(
        r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)",
        "",
        text,
    )

    # Remove common social/promo fragments.
    promo_patterns = [
        r"\bwishlist\b.*",
        r"\blink\s+in\s+bio\b.*",
        r"\bsubscribe\b.*",
        r"\bfollow\s+us\b.*",
        r"\bfollow\s+me\b.*",
    ]

    for pattern in promo_patterns:
        text = re.sub(
            pattern,
            "",
            text,
            flags=re.I,
        )

    # Remove music licensing boilerplate.
    music_patterns = [
        r'["“”]rainbows["“”]\s+kevin\s+macleod.*',
        r"\bkevin\s+macleod\b.*",
        r"\bincompetech\.com\b.*",
        r"\blicensed under creative commons\b.*",
        r"\bcreative commons\b.*",
        r"\bcreativecommons\.org\b.*",
        r"\bmusic by\b.*",
        r"\bsong by\b.*",
        r"\bmusic:\s*.*",
        r"\baudio:\s*.*",
    ]

    for pattern in music_patterns:
        text = re.sub(
            pattern,
            "",
            text,
            flags=re.I,
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

    # Remove duplicate consecutive lines.
    cleaned = []

    for line in lines:
        if not cleaned or line != cleaned[-1]:
            cleaned.append(line)

    # Maximum three consecutive logical lines are enough for
    # a Telegram pet caption in this system.
    return "\n".join(cleaned).strip()


def telegram_caption(source_caption):
    text = clean_caption(
        source_caption
    )

    if not text:
        return ""

    limit = 900

    if len(text) <= limit:
        return text

    text = text[:limit]

    newline = text.rfind("\n")

    if newline >= 400:
        text = text[:newline]
    else:
        space = text.rfind(" ")

        if space >= 400:
            text = text[:space]

    return text.rstrip(
        " .,-:;"
    ) + "…"


def normalize_status_url(url):
    if not url:
        return ""

    url = url.strip()

    parsed = urlparse(url)

    if not parsed.scheme or not parsed.netloc:
        return url

    path = parsed.path.rstrip("/")

    path = re.sub(
        r"/activity$",
        "",
        path,
    )

    return (
        f"{parsed.scheme}://"
        f"{parsed.netloc}"
        f"{path}"
    )


# ============================================================
# FILE / VIDEO HELPERS
# ============================================================

def sha256_file(path):
    digest = hashlib.sha256()

    with open(
        path,
        "rb",
    ) as handle:

        while True:
            chunk = handle.read(
                1024 * 1024
            )

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

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    try:
        data = json.loads(
            result.stdout
        )
    except Exception:
        return None

    streams = (
        data.get("streams")
        or []
    )

    if not streams:
        return None

    stream = streams[0]

    if stream.get(
        "codec_type"
    ) != "video":
        return None

    try:
        duration = float(
            stream.get(
                "duration"
            )
            or 0
        )
    except Exception:
        return None

    if duration <= 0:
        return None

    return {
        "duration": duration,
        "width": stream.get(
            "width"
        ),
        "height": stream.get(
            "height"
        ),
    }


# ============================================================
# MASTODON API
# ============================================================

def mastodon_get(
    instance,
    endpoint,
    params,
):
    url = (
        f"https://{instance}"
        f"{endpoint}"
    )

    try:
        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent":
                    "UTCutieDiscovery/1.0",
                "Accept":
                    "application/json",
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


def fetch_hashtag(
    instance,
    tag,
    limit=40,
):
    return mastodon_get(
        instance,
        f"/api/v1/timelines/tag/{tag}",
        {
            "limit": limit,
            "local": "false",
        },
    )


def extract_media_candidates(
    status,
    instance,
    tag,
):
    attachments = (
        status.get(
            "media_attachments"
        )
        or []
    )

    if not attachments:
        return []

    account = (
        status.get("account")
        or {}
    )

    account_name = (
        account.get("acct")
        or account.get("username")
        or ""
    )

    caption_raw = (
        status.get("content")
        or status.get("spoiler_text")
        or ""
    )

    caption = clean_caption(
        caption_raw
    )

    tags = []

    for item in (
        status.get("tags")
        or []
    ):
        name = item.get("name")

        if name:
            tags.append(
                str(name).lower()
            )

    results = []

    for media in attachments:

        if media.get(
            "type"
        ) != "video":
            continue

        media_url = (
            media.get("url")
            or media.get(
                "remote_url"
            )
            or ""
        )

        if not media_url:
            continue

        status_url = (
            status.get("url")
            or ""
        )

        results.append(
            {
                "instance": instance,
                "discovery_tag": tag,
                "status_id": str(
                    status.get(
                        "id"
                    )
                    or ""
                ),
                "status_url": status_url,
                "canonical_status_url":
                    normalize_status_url(
                        status_url
                    ),
                "account": account_name,
                "created_at":
                    status.get(
                        "created_at"
                    )
                    or "",
                "caption": caption,
                "caption_raw":
                    caption_raw,
                "tags": tags,
                "media_url": media_url,
                "preview_url":
                    media.get(
                        "preview_url"
                    )
                    or "",
                "media_type": "video",
                "favourites": int(
                    status.get(
                        "favourites_count"
                    )
                    or 0
                ),
                "reblogs": int(
                    status.get(
                        "reblogs_count"
                    )
                    or 0
                ),
                "replies": int(
                    status.get(
                        "replies_count"
                    )
                    or 0
                ),
            }
        )

    return results


# ============================================================
# CONTENT ANALYSIS
# ============================================================

def content_analysis(candidate):
    caption = normalize_text(
        candidate.get(
            "caption"
        )
        or ""
    )

    raw_caption = normalize_text(
        candidate.get(
            "caption_raw"
        )
        or ""
    )

    tags = [
        normalize_text(tag)
        for tag in (
            candidate.get(
                "tags"
            )
            or []
        )
    ]

    tag_text = " ".join(tags)

    caption_animal_hits = (
        word_hits(
            caption,
            ANIMAL_TERMS,
        )
    )

    caption_pet_hits = (
        word_hits(
            caption,
            PET_CONTEXT_TERMS,
        )
    )

    caption_entertainment_hits = (
        word_hits(
            caption,
            ENTERTAINMENT_TERMS,
        )
    )

    activity_hits = word_hits(
        caption,
        ACTIVITY_TERMS,
    )

    heartwarming_hits = word_hits(
        caption,
        HEARTWARMING_TERMS,
    )

    tag_animal_hits = word_hits(
        tag_text,
        ANIMAL_TERMS,
    )

    tag_pet_hits = word_hits(
        tag_text,
        PET_CONTEXT_TERMS,
    )

    tag_entertainment_hits = (
        word_hits(
            tag_text,
            ENTERTAINMENT_TERMS,
        )
    )

    negative_hits = word_hits(
        caption,
        HARD_NEGATIVE_TERMS,
    )

    negative_tag_hits = word_hits(
        tag_text,
        HARD_NEGATIVE_TERMS,
    )

    promotional_hits = word_hits(
        raw_caption,
        PROMOTIONAL_TERMS,
    )

    rescue_hits = word_hits(
        raw_caption,
        RESCUE_CAMPAIGN_TERMS,
    )

    rescue_tag_hits = word_hits(
        tag_text,
        RESCUE_CAMPAIGN_TERMS,
    )

    art_hits = word_hits(
        raw_caption,
        ART_PRODUCT_TERMS,
    )

    art_tag_hits = word_hits(
        tag_text,
        ART_PRODUCT_TERMS,
    )

    # Hashtags alone can never produce 100 relevance.
    animal_relevance = 0

    animal_relevance += min(
        55,
        len(caption_animal_hits) * 25,
    )

    animal_relevance += min(
        20,
        len(caption_pet_hits) * 10,
    )

    animal_relevance += min(
        15,
        len(tag_animal_hits) * 5,
    )

    animal_relevance += min(
        10,
        len(tag_pet_hits) * 5,
    )

    animal_relevance = min(
        100,
        animal_relevance,
    )

    entertainment_score = 0

    entertainment_score += min(
        60,
        len(
            caption_entertainment_hits
        ) * 20,
    )

    entertainment_score += min(
        20,
        len(
            tag_entertainment_hits
        ) * 5,
    )

    entertainment_score += min(
        30,
        len(activity_hits) * 10,
    )

    entertainment_score += min(
        20,
        len(heartwarming_hits) * 10,
    )

    entertainment_score = min(
        100,
        entertainment_score,
    )

    return {
        "caption_animal_hits":
            caption_animal_hits,
        "caption_pet_hits":
            caption_pet_hits,
        "tag_animal_hits":
            tag_animal_hits,
        "tag_pet_hits":
            tag_pet_hits,
        "caption_entertainment_hits":
            caption_entertainment_hits,
        "tag_entertainment_hits":
            tag_entertainment_hits,
        "activity_hits":
            activity_hits,
        "heartwarming_hits":
            heartwarming_hits,
        "negative_hits":
            negative_hits,
        "negative_tag_hits":
            negative_tag_hits,
        "promotional_hits":
            promotional_hits,
        "rescue_hits":
            rescue_hits,
        "rescue_tag_hits":
            rescue_tag_hits,
        "art_hits":
            art_hits,
        "art_tag_hits":
            art_tag_hits,
        "animal_relevance":
            animal_relevance,
        "entertainment_score":
            entertainment_score,
    }


def is_hard_reject(
    candidate,
    analysis,
):
    caption_animal = analysis[
        "caption_animal_hits"
    ]

    caption_pet = analysis[
        "caption_pet_hits"
    ]

    tag_animal = analysis[
        "tag_animal_hits"
    ]

    tag_pet = analysis[
        "tag_pet_hits"
    ]

    # --------------------------------------------------------
    # Non-entertainment subjects.
    # --------------------------------------------------------

    if analysis[
        "negative_hits"
    ]:
        return (
            True,
            "non-entertainment category",
        )

    # --------------------------------------------------------
    # Fundraising / rescue / solicitation.
    # --------------------------------------------------------

    promotional = set(
        analysis[
            "promotional_hits"
        ]
    )

    rescue = set(
        analysis[
            "rescue_hits"
        ]
    )

    if (
        "donate" in promotional
        or "donation" in promotional
        or "donations" in promotional
        or "fundraiser" in promotional
        or "fundraising" in promotional
        or "wishlist" in promotional
        or "gofundme" in promotional
        or "paypal" in promotional
        or "venmo" in promotional
        or "cashapp" in promotional
    ):
        return (
            True,
            "fundraising/solicitation",
        )

    if (
        rescue
        and promotional
    ):
        return (
            True,
            "rescue solicitation",
        )

    # --------------------------------------------------------
    # Art / product / unboxing.
    # --------------------------------------------------------

    art = set(
        analysis[
            "art_hits"
        ]
    )

    art_tags = set(
        analysis[
            "art_tag_hits"
        ]
    )

    product_context = (
        art
        | art_tags
    )

    if (
        "unboxing" in product_context
        or "unbox" in product_context
        or "haul" in product_context
        or "product" in product_context
        or "products" in product_context
        or "merch" in product_context
        or "merchandise" in product_context
    ):
        return (
            True,
            "product/unboxing content",
        )

    if (
        "portrait" in art
        or "artwork" in art
        or "painting" in art
        or "illustration" in art
        or "drawing" in art
        or "commission" in art
        or "foiled" in art
    ):
        return (
            True,
            "art content",
        )

    if (
        "custom" in art
        and (
            "art" in art
            or "portrait" in art
            or "design" in art
            or "print" in art
        )
    ):
        return (
            True,
            "custom art/product content",
        )

    # --------------------------------------------------------
    # Animal must appear in caption/context.
    #
    # Hashtag-only animal posts are not reliable enough.
    # --------------------------------------------------------

    if (
        not caption_animal
        and not caption_pet
    ):
        if (
            tag_animal
            or tag_pet
        ):
            return (
                True,
                "animal evidence only in hashtags",
            )

        return (
            True,
            "no animal evidence",
        )

    # --------------------------------------------------------
    # Reject content that is technically about an animal but
    # has no meaningful pet-life / entertainment / wholesome
    # context.
    #
    # Exception: an explicit animal caption is enough if it
    # clearly identifies the subject and the video is fresh.
    # The final content-value gate handles the borderline cases.
    # --------------------------------------------------------

    return False, ""


# ============================================================
# RECENCY
# ============================================================

def recency_days(candidate):
    created_at = candidate.get(
        "created_at"
    )

    if not created_at:
        return 9999

    try:
        value = created_at.replace(
            "Z",
            "+00:00",
        )

        created = datetime.fromisoformat(
            value
        )

        if created.tzinfo is None:
            created = created.replace(
                tzinfo=timezone.utc
            )

        now = datetime.now(
            timezone.utc
        )

        return max(
            0,
            (
                now
                - created.astimezone(
                    timezone.utc
                )
            ).total_seconds()
            / 86400,
        )

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

    if days <= 21:
        return 65

    if days <= 30:
        return 45

    return 0


# ============================================================
# SCORING
# ============================================================

def engagement_score(candidate):
    favourites = candidate.get(
        "favourites",
        0,
    )

    reblogs = candidate.get(
        "reblogs",
        0,
    )

    replies = candidate.get(
        "replies",
        0,
    )

    raw = (
        favourites
        + reblogs * 3
        + replies * 2
    )

    if raw <= 0:
        return 0

    return min(
        100,
        round(
            math.log10(
                raw + 1
            ) * 18,
            2,
        ),
    )


def quality_score(
    candidate,
    media_info,
):
    width = (
        media_info.get(
            "width"
        )
        or 0
    )

    height = (
        media_info.get(
            "height"
        )
        or 0
    )

    duration = (
        media_info.get(
            "duration"
        )
        or 0
    )

    longest_side = max(
        width,
        height,
    )

    shortest_side = min(
        width,
        height,
    )

    score = 0

    # Resolution quality.
    if longest_side >= 1920:
        score += 40
    elif longest_side >= 1440:
        score += 35
    elif longest_side >= 1080:
        score += 30
    elif longest_side >= 720:
        score += 20
    elif longest_side >= 480:
        score += 10

    # Penalize extremely low-resolution footage.
    if shortest_side < 480:
        score -= 20

    # Reasonable duration.
    if 20 <= duration <= 120:
        score += 15
    elif 15 <= duration <= 180:
        score += 8

    if candidate.get(
        "preview_url"
    ):
        score += 5

    return max(
        0,
        min(100, score),
    )


def caption_quality_score(
    candidate,
    analysis,
):
    caption = (
        candidate.get(
            "caption"
        )
        or ""
    ).strip()

    score = 0

    if caption:
        score += 20

    if 20 <= len(caption) <= 300:
        score += 20

    elif len(caption) > 300:
        score += 10

    if analysis[
        "caption_entertainment_hits"
    ]:
        score += 25

    if analysis[
        "activity_hits"
    ]:
        score += 20

    if analysis[
        "heartwarming_hits"
    ]:
        score += 15

    if analysis[
        "promotional_hits"
    ]:
        score -= 50

    if analysis[
        "rescue_hits"
    ]:
        score -= 50

    return max(
        0,
        min(100, score),
    )


def content_value_score(
    analysis,
):
    animal = analysis[
        "animal_relevance"
    ]

    entertainment = analysis[
        "entertainment_score"
    ]

    activity = min(
        100,
        len(
            analysis[
                "activity_hits"
            ]
        ) * 20,
    )

    heartwarming = min(
        100,
        len(
            analysis[
                "heartwarming_hits"
            ]
        ) * 20,
    )

    # Stronger requirement than simply "animal + hashtags".
    return round(
        animal * 0.45
        + entertainment * 0.30
        + activity * 0.15
        + heartwarming * 0.10,
        2,
    )


def score_candidate(
    candidate,
    analysis,
    media_info,
):
    days = recency_days(
        candidate
    )

    engagement = engagement_score(
        candidate
    )

    recency = recency_score(
        days
    )

    quality = quality_score(
        candidate,
        media_info,
    )

    caption_quality = (
        caption_quality_score(
            candidate,
            analysis,
        )
    )

    animal = analysis[
        "animal_relevance"
    ]

    entertainment = analysis[
        "entertainment_score"
    ]

    activity_bonus = min(
        30,
        len(
            analysis["activity_hits"]
        ) * 10,
    )

    heartwarming_bonus = min(
        20,
        len(
            analysis[
                "heartwarming_hits"
            ]
        ) * 5,
    )

    content_value = (
        content_value_score(
            analysis
        )
    )

    total = (
        animal * 1.6
        + entertainment * 1.15
        + activity_bonus * 1.0
        + heartwarming_bonus * 0.8
        + engagement * 0.8
        + recency * 1.4
        + quality * 0.9
        + caption_quality * 0.6
    )

    # Freshness is deliberately stronger than before.
    if days <= PREFERRED_DAYS:
        total += 25

    elif days <= FALLBACK_DAYS:
        total -= 15

    candidate[
        "animal_relevance"
    ] = animal

    candidate[
        "entertainment_score"
    ] = entertainment

    candidate[
        "engagement_score"
    ] = engagement

    candidate[
        "recency_days"
    ] = round(
        days,
        2,
    )

    candidate[
        "recency_score"
    ] = recency

    candidate[
        "quality_score"
    ] = quality

    candidate[
        "caption_quality_score"
    ] = caption_quality

    candidate[
        "content_value_score"
    ] = content_value

    candidate[
        "total_score"
    ] = round(
        total,
        2,
    )

    candidate[
        "analysis"
    ] = analysis

    candidate[
        "media_info"
    ] = media_info

    return candidate


# ============================================================
# MEDIA VALIDATION
# ============================================================

def validate_media(
    candidate,
    temp_dir,
):
    media_url = candidate.get(
        "media_url"
    )

    if not media_url:
        return None

    filename = (
        hashlib.sha1(
            media_url.encode()
        ).hexdigest()
        + ".mp4"
    )

    output_path = (
        Path(temp_dir)
        / filename
    )

    try:
        with requests.get(
            media_url,
            stream=True,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent":
                    "UTCutieDiscovery/1.0"
            },
        ) as response:

            if response.status_code != 200:
                return None

            content_type = (
                response.headers.get(
                    "content-type",
                    "",
                ).lower()
            )

            if (
                "video" not in content_type
                and "octet-stream"
                not in content_type
            ):
                return None

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
                        return None
                except Exception:
                    pass

            total = 0

            with open(
                output_path,
                "wb",
            ) as handle:

                for chunk in response.iter_content(
                    chunk_size=1024 * 256
                ):

                    if not chunk:
                        continue

                    total += len(chunk)

                    if (
                        total
                        > MAX_FILE_SIZE
                    ):
                        return None

                    handle.write(chunk)

        info = run_ffprobe(
            output_path
        )

        if not info:
            return None

        duration = info[
            "duration"
        ]

        if duration < MIN_DURATION:
            return None

        if duration > MAX_DURATION:
            return None

        candidate[
            "duration"
        ] = round(
            duration,
            3,
        )

        candidate[
            "file_size"
        ] = output_path.stat().st_size

        candidate[
            "sha256"
        ] = sha256_file(
            output_path
        )

        candidate[
            "media_info"
        ] = info

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
    if not HISTORY_FILE.exists():
        return []

    try:
        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8",
        ) as handle:

            data = json.load(
                handle
            )

        return (
            data
            if isinstance(
                data,
                list,
            )
            else []
        )

    except Exception:
        return []


def history_keys(history):
    keys = set()

    for item in history:

        if not isinstance(
            item,
            dict,
        ):
            continue

        for key in (
            "status_url",
            "canonical_status_url",
            "media_url",
            "sha256",
        ):

            value = item.get(
                key
            )

            if value:
                keys.add(
                    str(value)
                )

    return keys


def is_in_history(
    candidate,
    keys,
):
    values = {
        candidate.get(
            "status_url"
        ),
        candidate.get(
            "canonical_status_url"
        ),
        candidate.get(
            "media_url"
        ),
        candidate.get(
            "sha256"
        ),
    }

    values.discard(None)
    values.discard("")

    return bool(
        values.intersection(
            keys
        )
    )


# ============================================================
# DEDUPLICATION
# ============================================================

def deduplicate_canonical(
    candidates,
):
    result = []

    seen_statuses = set()
    seen_media = set()
    seen_hashes = set()

    candidates = sorted(
        candidates,
        key=lambda x: x.get(
            "total_score",
            0,
        ),
        reverse=True,
    )

    for candidate in candidates:

        status = (
            candidate.get(
                "canonical_status_url"
            )
            or normalize_status_url(
                candidate.get(
                    "status_url"
                )
            )
        )

        media = candidate.get(
            "media_url"
        )

        digest = candidate.get(
            "sha256"
        )

        if (
            status
            and status in seen_statuses
        ):
            continue

        if (
            media
            and media in seen_media
        ):
            continue

        if (
            digest
            and digest in seen_hashes
        ):
            continue

        if status:
            seen_statuses.add(
                status
            )

        if media:
            seen_media.add(
                media
            )

        if digest:
            seen_hashes.add(
                digest
            )

        result.append(
            candidate
        )

    return result


# ============================================================
# DIVERSITY
# ============================================================

def select_with_diversity(
    candidates,
    max_items=MAX_VIDEOS,
):
    account_counts = {}
    instance_counts = {}

    selected = []

    # First pass: respect diversity limits.
    for candidate in candidates:

        if len(selected) >= max_items:
            break

        account = (
            candidate.get(
                "account"
            )
            or "unknown-account"
        )

        instance = (
            candidate.get(
                "instance"
            )
            or "unknown-instance"
        )

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

        account_counts[account] = (
            account_counts.get(
                account,
                0,
            )
            + 1
        )

        instance_counts[instance] = (
            instance_counts.get(
                instance,
                0,
            )
            + 1
        )

    # Second pass only fills remaining slots with candidates
    # that were not already selected.
    if len(selected) < max_items:

        selected_keys = {
            (
                item.get("sha256")
                or item.get("media_url")
                or item.get(
                    "canonical_status_url"
                )
            )
            for item in selected
        }

        for candidate in candidates:

            if len(selected) >= max_items:
                break

            key = (
                candidate.get("sha256")
                or candidate.get(
                    "media_url"
                )
                or candidate.get(
                    "canonical_status_url"
                )
            )

            if key in selected_keys:
                continue

            selected.append(
                candidate
            )

            selected_keys.add(
                key
            )

    return selected[:max_items]


# ============================================================
# JSON
# ============================================================

def write_json(
    path,
    data,
):
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


# ============================================================
# MAIN
# ============================================================

def main():

    raw_candidates = []

    seen_statuses = set()

    print(
        "Starting UTCutie expanded "
        "Mastodon discovery..."
    )

    # --------------------------------------------------------
    # DISCOVERY
    # --------------------------------------------------------

    for instance in INSTANCES:

        instance_status_count = 0

        for tag in TAGS:

            statuses = fetch_hashtag(
                instance,
                tag,
            )

            instance_status_count += (
                len(statuses)
            )

            for status in statuses:

                status_id = str(
                    status.get(
                        "id"
                    )
                    or ""
                )

                local_key = (
                    instance,
                    status_id,
                )

                if local_key in seen_statuses:
                    continue

                seen_statuses.add(
                    local_key
                )

                raw_candidates.extend(
                    extract_media_candidates(
                        status,
                        instance,
                        tag,
                    )
                )

        print(
            f"{instance}: "
            f"{instance_status_count} statuses"
        )

    write_json(
        OUTPUT_CANDIDATES,
        raw_candidates,
    )

    print()
    print(
        "Raw unique statuses discovered:",
        len(seen_statuses),
    )

    print(
        "Raw relevant video candidates:",
        len(raw_candidates),
    )

    # --------------------------------------------------------
    # PRE-VALIDATION DEDUP
    # --------------------------------------------------------

    preliminary = []

    seen = set()

    for candidate in raw_candidates:

        key = (
            candidate.get(
                "canonical_status_url"
            )
            or candidate.get(
                "status_url"
            )
            or candidate.get(
                "media_url"
            )
        )

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)

        preliminary.append(
            candidate
        )

    print(
        "Unique candidates for validation:",
        len(preliminary),
    )

    # --------------------------------------------------------
    # CONTENT GATE
    # --------------------------------------------------------

    gated = []

    rejection_counts = {}

    for candidate in preliminary:

        analysis = content_analysis(
            candidate
        )

        rejected, reason = (
            is_hard_reject(
                candidate,
                analysis,
            )
        )

        if rejected:

            rejection_counts[reason] = (
                rejection_counts.get(
                    reason,
                    0,
                )
                + 1
            )

            continue

        candidate[
            "analysis"
        ] = analysis

        gated.append(
            candidate
        )

    print()
    print(
        "Passed strict content gate:",
        len(gated),
    )

    print(
        "Content gate rejections:"
    )

    for reason, count in (
        rejection_counts.items()
    ):
        print(
            f"  {reason}: {count}"
        )

    # --------------------------------------------------------
    # MEDIA VALIDATION
    # --------------------------------------------------------

    validated = []

    validation_rejections = {}

    with tempfile.TemporaryDirectory() as temp_dir:

        for candidate in gated:

            checked = validate_media(
                candidate,
                temp_dir,
            )

            if not checked:

                validation_rejections[
                    "invalid media"
                ] = (
                    validation_rejections.get(
                        "invalid media",
                        0,
                    )
                    + 1
                )

                continue

            analysis = checked.get(
                "analysis"
            ) or content_analysis(
                checked
            )

            checked = score_candidate(
                checked,
                analysis,
                checked.get(
                    "media_info"
                )
                or {},
            )

            # ------------------------------------------------
            # Content-value gate.
            #
            # Prevents technically valid but weak animal
            # posts from entering the selection pool.
            # ------------------------------------------------

            if (
                checked.get(
                    "content_value_score",
                    0,
                )
                < MIN_CONTENT_VALUE
            ):

                validation_rejections[
                    "weak content value"
                ] = (
                    validation_rejections.get(
                        "weak content value",
                        0,
                    )
                    + 1
                )

                continue

            validated.append(
                checked
            )

    print()
    print(
        "Post-validation rejections:"
    )

    for reason, count in (
        validation_rejections.items()
    ):
        print(
            f"  {reason}: {count}"
        )

    # --------------------------------------------------------
    # FINAL DEDUP
    # --------------------------------------------------------

    validated = (
        deduplicate_canonical(
            validated
        )
    )

    write_json(
        OUTPUT_VALIDATED,
        validated,
    )

    print()
    print(
        "Validated videos:",
        len(validated),
    )

    # --------------------------------------------------------
    # HISTORY
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
        "Fresh videos after history:",
        len(fresh),
    )

    # --------------------------------------------------------
    # HARD FRESHNESS FILTER
    #
    # Nothing older than 30 days is allowed into the normal
    # selection pool.
    # --------------------------------------------------------

    preferred = [
        candidate
        for candidate in fresh
        if candidate.get(
            "recency_days",
            9999,
        ) <= PREFERRED_DAYS
    ]

    fallback = [
        candidate
        for candidate in fresh
        if (
            PREFERRED_DAYS
            < candidate.get(
                "recency_days",
                9999,
            )
            <= FALLBACK_DAYS
        )
    ]

    too_old = [
        candidate
        for candidate in fresh
        if candidate.get(
            "recency_days",
            9999,
        ) > FALLBACK_DAYS
    ]

    print(
        f"Preferred fresh videos "
        f"(<= {PREFERRED_DAYS} days):",
        len(preferred),
    )

    print(
        f"Fallback videos "
        f"({PREFERRED_DAYS}-{FALLBACK_DAYS} days):",
        len(fallback),
    )

    print(
        f"Rejected as too old "
        f"(> {FALLBACK_DAYS} days):",
        len(too_old),
    )

    # --------------------------------------------------------
    # RANKING
    #
    # Fresh pool always beats fallback pool.
    # Fallback is only used if fresh material is insufficient.
    # --------------------------------------------------------

    preferred.sort(
        key=lambda x: x.get(
            "total_score",
            0,
        ),
        reverse=True,
    )

    fallback.sort(
        key=lambda x: x.get(
            "total_score",
            0,
        ),
        reverse=True,
    )

    preferred_selected = (
        select_with_diversity(
            preferred,
            MAX_VIDEOS,
        )
    )

    remaining_slots = (
        MAX_VIDEOS
        - len(
            preferred_selected
        )
    )

    final_selected = list(
        preferred_selected
    )

    if remaining_slots > 0:

        selected_keys = {
            (
                item.get("sha256")
                or item.get("media_url")
                or item.get(
                    "canonical_status_url"
                )
            )
            for item in final_selected
        }

        fallback_remaining = [
            item
            for item in fallback
            if (
                item.get("sha256")
                or item.get("media_url")
                or item.get(
                    "canonical_status_url"
                )
            )
            not in selected_keys
        ]

        fallback_selected = (
            select_with_diversity(
                fallback_remaining,
                remaining_slots,
            )
        )

        final_selected.extend(
            fallback_selected
        )

    final_selected.sort(
        key=lambda x: (
            0
            if x.get(
                "recency_days",
                9999,
            ) <= PREFERRED_DAYS
            else 1,
            -x.get(
                "total_score",
                0,
            ),
        )
    )

    final_selected = (
        final_selected[:MAX_VIDEOS]
    )

    write_json(
        OUTPUT_SELECTED,
        final_selected,
    )

    # --------------------------------------------------------
    # FINAL REPORT
    # --------------------------------------------------------

    print()
    print(
        "============================================================"
    )

    print(
        "UTCUTIE EXPANDED MASTODON "
        "SELECTED CANDIDATES"
    )

    print(
        "============================================================"
    )

    print(
        json.dumps(
            final_selected,
            ensure_ascii=False,
            indent=2,
        )
    )

    print()
    print(
        "============================================================"
    )

    print(
        "UTCUTIE DISCOVERY COMPLETE"
    )

    print(
        "============================================================"
    )

    print(
        "Raw candidates:",
        len(raw_candidates),
    )

    print(
        "Passed content gate:",
        len(gated),
    )

    print(
        "Validated videos:",
        len(validated),
    )

    print(
        "Fresh videos:",
        len(fresh),
    )

    print(
        "Preferred videos:",
        len(preferred),
    )

    print(
        "Fallback videos:",
        len(fallback),
    )

    print(
        "Too-old videos rejected:",
        len(too_old),
    )

    print(
        "Selected videos:",
        len(final_selected),
    )

    print(
        "Published-history entries:",
        len(history),
    )

    print()
    print(
        "Publication history was NOT modified."
    )


if __name__ == "__main__":
    main()
