import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ============================================================
# UTCUTIE PROFESSIONAL VALIDATION ENGINE
# ============================================================

MIN_DURATION = 15
MAX_DURATION = 180

MAX_FILE_SIZE_MB = 48
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

MAX_SELECTED = 20

CANDIDATE_FILE = Path("candidate_urls.txt")
VALIDATED_FILE = Path("validated_candidates.json")
SELECTED_FILE = Path("selected_candidates.json")


# ============================================================
# CONTROLLED TEST SEEDS
# ============================================================
# These are ONLY engineering test candidates.
# They are not the final daily discovery mechanism.

SEED_URLS = [
    "https://x.com/garibansipsi/status/2054157848670605453"
]


# ============================================================
# PET / ANIMAL VOCABULARY
# ============================================================

PET_KEYWORDS = {
    # English
    "dog",
    "dogs",
    "puppy",
    "puppies",
    "doggo",
    "doggy",
    "pup",
    "cat",
    "cats",
    "kitten",
    "kittens",
    "kitty",
    "kitties",
    "pet",
    "pets",
    "animal",
    "animals",
    "bird",
    "birds",
    "parrot",
    "parrots",
    "rabbit",
    "rabbits",
    "bunny",
    "bunnies",
    "hamster",
    "hamsters",
    "guinea",
    "pig",
    "horse",
    "horses",
    "pony",
    "ponies",
    "duck",
    "ducks",
    "goose",
    "geese",
    "chicken",
    "chickens",
    "goat",
    "goats",
    "sheep",
    "cow",
    "cows",
    "calf",
    "calves",
    "monkey",
    "monkeys",
    "panda",
    "pandas",
    "otter",
    "otters",
    "fox",
    "foxes",
    "bear",
    "bears",
    "penguin",
    "penguins",
    "seal",
    "seals",
    "dolphin",
    "dolphins",
    "turtle",
    "turtles",
    "snake",
    "snakes",
    "lizard",
    "lizards",

    # Turkish
    "kedi",
    "kediler",
    "kediyi",
    "kedileri",
    "kediye",
    "köpek",
    "köpekler",
    "köpeği",
    "köpekleri",
    "yavru",
    "hayvan",
    "hayvanlar",
    "kuş",
    "kuşlar",
    "tavşan",
    "tavşanlar",
    "at",
    "atlar",
    "ördek",
    "ördekler",
    "maymun",
    "panda",

    # Persian
    "گربه",
    "گربه‌ها",
    "گربهها",
    "بچه‌گربه",
    "بچه گربه",
    "سگ",
    "سگ‌ها",
    "سگها",
    "توله",
    "توله‌سگ",
    "حیوان",
    "حیوانات",
    "پرنده",
    "پرندگان",
    "طوطی",
    "خرگوش",
    "همستر",
    "اسب",
    "اردک",
    "میمون",
    "پاندا",

    # Spanish / Portuguese common terms
    "gato",
    "gatos",
    "gatito",
    "gatitos",
    "perro",
    "perros",
    "cachorro",
    "cachorros",
    "animal",
    "animales",
    "mascota",
    "mascotas",

    # French
    "chat",
    "chats",
    "chaton",
    "chatons",
    "chien",
    "chiens",
    "chiot",
    "chiots",
    "animal",
    "animaux",
    "animaux",
    "lapin",
    "lapins",
    "oiseau",
    "oiseaux",

    # German
    "katze",
    "katzen",
    "kätzchen",
    "hund",
    "hunde",
    "welpe",
    "welpen",
    "tier",
    "tiere",
    "kaninchen",
    "vogel",
    "vögel",
}


# Stronger terms receive more relevance weight.
STRONG_PET_KEYWORDS = {
    "cat",
    "cats",
    "kitten",
    "kittens",
    "kitty",
    "dog",
    "dogs",
    "puppy",
    "puppies",
    "doggo",
    "kedi",
    "kediler",
    "kedileri",
    "köpek",
    "köpekler",
    "گربه",
    "گربه‌ها",
    "بچه‌گربه",
    "سگ",
    "توله‌سگ",
    "gato",
    "gatito",
    "perro",
    "cachorro",
    "chat",
    "chaton",
    "chien",
    "chiot",
    "katze",
    "kätzchen",
    "hund",
    "welpe",
}


# ============================================================
# CONTENT / NEGATIVE SIGNALS
# ============================================================

LOW_VALUE_KEYWORDS = {
    "politics",
    "political",
    "crypto",
    "bitcoin",
    "forex",
    "casino",
    "gambling",
    "porn",
    "nsfw",
    "adult",
    "onlyfans",
    "giveaway",
    "betting",
    "sportsbook",
}


# ============================================================
# HELPERS
# ============================================================

def normalize_text(value):
    if value is None:
        return ""

    value = str(value).lower()

    # Normalize common Unicode punctuation.
    replacements = {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "\u200c": " ",
        "\u200d": " ",
        "\ufeff": " ",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    # Keep Unicode letters/numbers.
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def keyword_matches(text, keywords):
    """
    Unicode-friendly keyword matching.

    We intentionally use substring matching because some languages
    attach suffixes to the base word, e.g. Turkish:
    kedi -> kedileri
    """

    normalized = normalize_text(text)

    matches = []

    for keyword in keywords:
        keyword_normalized = normalize_text(keyword)

        if keyword_normalized and keyword_normalized in normalized:
            matches.append(keyword)

    return sorted(set(matches))


def safe_number(value, default=0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def calculate_engagement_score(data):
    views = safe_number(data.get("view_count"))
    likes = safe_number(data.get("like_count"))
    comments = safe_number(data.get("comment_count"))
    reposts = safe_number(data.get("repost_count"))

    score = (
        math.log10(views + 1) * 10
        + math.log10(likes + 1) * 8
        + math.log10(comments + 1) * 5
        + math.log10(reposts + 1) * 6
    )

    return round(score, 3)


def calculate_quality_score(data):
    formats = data.get("formats") or []

    video_formats = [
        item
        for item in formats
        if item.get("vcodec")
        and item.get("vcodec") != "none"
    ]

    if not video_formats:
        return 0.0

    best_width = 0
    best_height = 0

    for fmt in video_formats:
        width = int(safe_number(fmt.get("width"), 0))
        height = int(safe_number(fmt.get("height"), 0))

        if width * height > best_width * best_height:
            best_width = width
            best_height = height

    pixels = best_width * best_height

    if pixels >= 1280 * 720:
        score = 10.0
    elif pixels >= 854 * 480:
        score = 8.0
    elif pixels >= 640 * 360:
        score = 6.0
    elif pixels > 0:
        score = 4.0
    else:
        score = 0.0

    return round(score, 3)


def get_best_video_format(data):
    formats = data.get("formats") or []

    candidates = []

    for fmt in formats:
        if fmt.get("vcodec") in (None, "none"):
            continue

        if fmt.get("video_ext") not in (None, "", "none"):
            ext = fmt.get("video_ext")
        else:
            ext = fmt.get("ext")

        if ext != "mp4":
            continue

        width = int(safe_number(fmt.get("width"), 0))
        height = int(safe_number(fmt.get("height"), 0))

        filesize = fmt.get("filesize")

        if filesize is None:
            filesize = fmt.get("filesize_approx")

        filesize = int(safe_number(filesize, 0))

        candidates.append({
            "format_id": fmt.get("format_id"),
            "width": width,
            "height": height,
            "filesize": filesize,
            "filesize_mb": round(
                filesize / (1024 * 1024), 2
            ) if filesize else None,
            "resolution": fmt.get("resolution"),
            "protocol": fmt.get("protocol"),
        })

    if not candidates:
        return None

    # Prefer highest resolution among files that are known
    # to fit the Telegram/Render size target.
    fitting = [
        item
        for item in candidates
        if item["filesize"] == 0
        or item["filesize"] <= MAX_FILE_SIZE_BYTES
    ]

    if fitting:
        fitting.sort(
            key=lambda item: (
                item["width"] * item["height"],
                item["width"],
                item["height"],
            ),
            reverse=True,
        )

        return fitting[0]

    # If every known size is above the limit, return the smallest.
    candidates.sort(
        key=lambda item: (
            item["filesize"] if item["filesize"] else float("inf"),
            -(item["width"] * item["height"]),
        )
    )

    return candidates[0]


def calculate_recency_score(data):
    upload_date = data.get("upload_date")

    if not upload_date:
        return 0.0

    try:
        uploaded = datetime.strptime(
            str(upload_date),
            "%Y%m%d"
        ).replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)

        age_days = max(
            0,
            (now - uploaded).days
        )

        # Recent content gets more weight, but old viral
        # content is not automatically rejected.
        if age_days <= 1:
            score = 15
        elif age_days <= 3:
            score = 13
        elif age_days <= 7:
            score = 11
        elif age_days <= 14:
            score = 9
        elif age_days <= 30:
            score = 7
        elif age_days <= 90:
            score = 4
        else:
            score = 1

        return float(score)

    except Exception:
        return 0.0


def build_searchable_text(data):
    fields = [
        data.get("title"),
        data.get("fulltitle"),
        data.get("description"),
        data.get("uploader"),
        data.get("uploader_id"),
    ]

    tags = data.get("tags") or []

    fields.extend(tags)

    return normalize_text(
        " ".join(
            str(item)
            for item in fields
            if item
        )
    )


def calculate_relevance(data):
    text = build_searchable_text(data)

    strong_matches = keyword_matches(
        text,
        STRONG_PET_KEYWORDS
    )

    normal_matches = keyword_matches(
        text,
        PET_KEYWORDS
    )

    negative_matches = keyword_matches(
        text,
        LOW_VALUE_KEYWORDS
    )

    # Strong animal terms carry most of the weight.
    score = (
        len(strong_matches) * 12
        + len(normal_matches) * 4
    )

    # Multiple independent pet signals are valuable.
    if len(normal_matches) >= 2:
        score += 8

    if len(strong_matches) >= 2:
        score += 10

    # Negative signals reduce relevance but do not necessarily
    # destroy a candidate because some accounts use mixed text.
    score -= len(negative_matches) * 8

    score = clamp(score, 0, 100)

    return {
        "score": round(score, 3),
        "strong_matches": strong_matches,
        "matches": normal_matches,
        "negative_matches": negative_matches,
    }


def extract_metadata(url):
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--dump-single-json",
        "--no-warnings",
        url,
    ]

    print("Running:")
    print(" ".join(command))

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        print("yt-dlp timed out.")
        return None

    if result.returncode != 0:
        print("yt-dlp could not access this post.")

        if result.stderr:
            print(result.stderr[-2000:])

        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print("yt-dlp returned invalid JSON.")
        return None


def validate_candidate(url):
    print()
    print("=" * 70)
    print("VALIDATING X POST")
    print("=" * 70)
    print(url)
    print()

    data = extract_metadata(url)

    if not data:
        return None

    canonical_id = (
        data.get("id")
        or data.get("display_id")
        or ""
    )

    display_id = data.get("display_id") or canonical_id

    title = data.get("title") or data.get("fulltitle") or ""
    description = data.get("description") or ""

    duration = safe_number(
        data.get("duration"),
        0
    )

    formats = data.get("formats") or []

    video_formats = [
        fmt
        for fmt in formats
        if fmt.get("vcodec")
        and fmt.get("vcodec") != "none"
    ]

    if duration < MIN_DURATION:
        print(
            f"REJECTED: duration too short "
            f"({duration:.1f}s)."
        )
        return None

    if duration > MAX_DURATION:
        print(
            f"REJECTED: duration too long "
            f"({duration:.1f}s)."
        )
        return None

    if not video_formats:
        print("REJECTED: no video format found.")
        return None

    relevance = calculate_relevance(data)

    # IMPORTANT:
    # We no longer require a single exact keyword.
    # We accept a candidate when there is meaningful animal
    # evidence in its metadata.
    if relevance["score"] <= 0:
        print(
            "REJECTED: no meaningful pet/animal signal "
            "in available metadata."
        )
        return None

    best_format = get_best_video_format(data)

    if not best_format:
        print("REJECTED: no usable MP4 video format.")
        return None

    known_size = best_format.get("filesize")

    if known_size and known_size > MAX_FILE_SIZE_BYTES:
        print(
            "REJECTED: best usable video format exceeds "
            f"{MAX_FILE_SIZE_MB} MB."
        )
        return None

    engagement_score = calculate_engagement_score(data)
    quality_score = calculate_quality_score(data)
    recency_score = calculate_recency_score(data)

    # Relevance is deliberately the strongest component.
    total_score = (
        relevance["score"] * 2.0
        + engagement_score
        + quality_score
        + recency_score
    )

    result = {
        "url": data.get("webpage_url") or url,
        "original_url": data.get("original_url") or url,

        "id": canonical_id,
        "display_id": display_id,

        "title": title,
        "description": description,

        "uploader": data.get("uploader"),
        "uploader_id": data.get("uploader_id"),
        "uploader_url": data.get("uploader_url"),

        "upload_date": data.get("upload_date"),
        "timestamp": data.get("timestamp"),

        "duration": duration,

        "view_count": data.get("view_count"),
        "like_count": data.get("like_count"),
        "comment_count": data.get("comment_count"),
        "repost_count": data.get("repost_count"),

        "thumbnail": data.get("thumbnail"),

        "relevance": relevance,
        "engagement_score": engagement_score,
        "quality_score": quality_score,
        "recency_score": recency_score,
        "total_score": round(total_score, 3),

        "best_video_format": best_format,

        "extractor": data.get("extractor"),
        "extractor_key": data.get("extractor_key"),
    }

    print()
    print("ACCEPTED")
    print("-" * 70)

    print(f"Canonical ID: {canonical_id}")
    print(f"Title: {title}")
    print(f"Uploader: {data.get('uploader')}")
    print(f"Duration: {duration:.1f}s")

    print(
        f"Views: {data.get('view_count')}"
    )

    print(
        f"Likes: {data.get('like_count')}"
    )

    print(
        f"Comments: {data.get('comment_count')}"
    )

    print(
        f"Reposts: {data.get('repost_count')}"
    )

    print()
    print(
        "Pet/animal matches:",
        ", ".join(
            relevance["matches"]
        ) or "none"
    )

    print(
        "Strong matches:",
        ", ".join(
            relevance["strong_matches"]
        ) or "none"
    )

    print(
        f"Relevance score: {relevance['score']}"
    )

    print(
        f"Engagement score: {engagement_score}"
    )

    print(
        f"Quality score: {quality_score}"
    )

    print(
        f"Recency score: {recency_score}"
    )

    print(
        f"TOTAL SCORE: {result['total_score']}"
    )

    print(
        "Best format:",
        best_format
    )

    return result


# ============================================================
# CANDIDATE LOADING
# ============================================================

def load_candidate_urls():
    urls = []

    if CANDIDATE_FILE.exists():
        try:
            content = CANDIDATE_FILE.read_text(
                encoding="utf-8"
            )

            for line in content.splitlines():
                line = line.strip()

                if not line:
                    continue

                if line.startswith("#"):
                    continue

                if line.startswith("http://") or line.startswith(
                    "https://"
                ):
                    urls.append(line)

        except Exception as exc:
            print(
                f"Could not read {CANDIDATE_FILE}: {exc}"
            )

    # Deduplicate while preserving order.
    unique_urls = []

    for url in urls:
        if url not in unique_urls:
            unique_urls.append(url)

    if unique_urls:
        print(
            f"Loaded {len(unique_urls)} "
            "candidate URLs."
        )
        return unique_urls

    print("No discovered candidates found.")
    print("Using controlled seed candidates.")

    return SEED_URLS.copy()


# ============================================================
# DEDUPLICATION
# ============================================================

def deduplicate_candidates(candidates):
    seen_ids = set()
    seen_urls = set()

    unique = []

    for item in candidates:
        candidate_id = str(
            item.get("id") or ""
        ).strip()

        url = str(
            item.get("url") or ""
        ).strip()

        if candidate_id:
            if candidate_id in seen_ids:
                continue

            seen_ids.add(candidate_id)

        if url:
            if url in seen_urls:
                continue

            seen_urls.add(url)

        unique.append(item)

    return unique


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("UTCUTIE PROFESSIONAL VALIDATION ENGINE")
    print("=" * 70)

    print(
        f"Duration: {MIN_DURATION}–{MAX_DURATION} seconds"
    )

    print(
        f"Maximum file size: {MAX_FILE_SIZE_MB} MB"
    )

    print()

    candidate_urls = load_candidate_urls()

    print()
    print(
        f"Candidates to validate: "
        f"{len(candidate_urls)}"
    )

    validated = []

    for index, url in enumerate(
        candidate_urls,
        start=1
    ):
        print()
        print(
            f"Candidate {index}/"
            f"{len(candidate_urls)}"
        )

        try:
            result = validate_candidate(url)

            if result:
                validated.append(result)

        except Exception as exc:
            print(
                f"Unexpected validation error: {exc}"
            )

    validated = deduplicate_candidates(
        validated
    )

    validated.sort(
        key=lambda item: item.get(
            "total_score",
            0
        ),
        reverse=True,
    )

    selected = validated[:MAX_SELECTED]

    VALIDATED_FILE.write_text(
        json.dumps(
            validated,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    SELECTED_FILE.write_text(
        json.dumps(
            selected,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 70)
    print("VALIDATION COMPLETE")
    print("=" * 70)

    print(
        f"Validated: {len(validated)}"
    )

    print(
        f"Selected: {len(selected)}"
    )

    print(
        f"Saved: {VALIDATED_FILE}"
    )

    print(
        f"Saved: {SELECTED_FILE}"
    )

    print()
    print("SELECTED CONTENT:")

    if not selected:
        print("No candidates selected.")
        return

    for index, item in enumerate(
        selected,
        start=1
    ):
        print()
        print(
            f"{index}. "
            f"{item.get('title', '')}"
        )

        print(
            f"   URL: {item.get('url')}"
        )

        print(
            f"   Duration: "
            f"{item.get('duration')}s"
        )

        print(
            f"   Views: "
            f"{item.get('view_count')}"
        )

        print(
            f"   Likes: "
            f"{item.get('like_count')}"
        )

        print(
            f"   Relevance: "
            f"{item.get('relevance', {}).get('score')}"
        )

        print(
            f"   Total score: "
            f"{item.get('total_score')}"
        )


if __name__ == "__main__":
    main()
