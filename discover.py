import json
import math
import subprocess
import sys
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

MIN_DURATION = 15
MAX_DURATION = 180
MAX_FILE_SIZE_MB = 48

MAX_SELECTED = 20

CANDIDATE_FILE = Path("candidate_urls.txt")
VALIDATED_FILE = Path("validated_candidates.json")
SELECTED_FILE = Path("selected_candidates.json")


# ------------------------------------------------------------
# Temporary controlled test candidates
#
# These are ONLY for testing the validation/ranking engine.
# The live discovery source will be connected later.
# ------------------------------------------------------------

SEED_URLS = [
    "https://x.com/garibansipsi/status/2054157848670605453",
]


# ============================================================
# HELPERS
# ============================================================

def run_command(command, timeout=180):
    print("\nRunning:")
    print(" ".join(command))

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if result.stdout:
        print(result.stdout)

    if result.stderr:
        print(result.stderr)

    return result


def safe_number(value):
    if value is None:
        return 0

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def format_number(value):
    value = safe_number(value)

    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"

    if value >= 1_000:
        return f"{value / 1_000:.1f}K"

    return str(int(value))


# ============================================================
# CANDIDATE LOADING
# ============================================================

def load_candidates():
    """
    Load URLs from candidate_urls.txt if it exists.

    If the file is empty or unavailable, use the controlled
    seed list for the engineering test.
    """

    urls = []

    if CANDIDATE_FILE.exists():

        content = CANDIDATE_FILE.read_text(
            encoding="utf-8"
        )

        for line in content.splitlines():

            url = line.strip()

            if (
                url.startswith("https://x.com/")
                or url.startswith("https://www.x.com/")
            ):
                if url not in urls:
                    urls.append(url)

    if not urls:
        print(
            "No discovered candidates found."
        )

        print(
            "Using controlled seed candidates."
        )

        urls = list(SEED_URLS)

    return urls


# ============================================================
# YT-DLP METADATA
# ============================================================

def extract_metadata(url):
    """
    Ask yt-dlp for metadata without downloading the video.
    """

    print("\n")
    print("=" * 70)
    print("VALIDATING X POST")
    print("=" * 70)

    print(url)

    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--dump-single-json",
        "--no-warnings",
        url,
    ]

    try:

        result = run_command(
            command,
            timeout=180,
        )

    except subprocess.TimeoutExpired:

        print(
            "yt-dlp timed out."
        )

        return None

    if result.returncode != 0:

        print(
            "yt-dlp could not access this post."
        )

        return None

    output = result.stdout.strip()

    if not output:

        print(
            "yt-dlp returned no metadata."
        )

        return None

    try:

        data = json.loads(output)

    except json.JSONDecodeError:

        print(
            "yt-dlp output was not valid JSON."
        )

        return None

    return data


# ============================================================
# VIDEO FORMAT CHECK
# ============================================================

def get_best_video_format(metadata):
    """
    Find the largest/most useful video format available.
    """

    formats = metadata.get("formats") or []

    video_formats = []

    for fmt in formats:

        vcodec = fmt.get("vcodec")

        if not vcodec or vcodec == "none":
            continue

        height = safe_number(
            fmt.get("height")
        )

        width = safe_number(
            fmt.get("width")
        )

        filesize = safe_number(
            fmt.get("filesize")
        )

        filesize_approx = safe_number(
            fmt.get("filesize_approx")
        )

        if not filesize:
            filesize = filesize_approx

        video_formats.append(
            {
                "format_id": fmt.get("format_id"),
                "width": int(width),
                "height": int(height),
                "filesize": int(filesize),
                "ext": fmt.get("ext"),
                "vcodec": vcodec,
                "acodec": fmt.get("acodec"),
            }
        )

    if not video_formats:
        return None

    # Prefer formats with known size.
    known_size = [
        fmt
        for fmt in video_formats
        if fmt["filesize"] > 0
    ]

    if known_size:

        suitable = [
            fmt
            for fmt in known_size
            if fmt["filesize"]
            <= MAX_FILE_SIZE_MB * 1024 * 1024
        ]

        if suitable:

            return max(
                suitable,
                key=lambda fmt: (
                    fmt["height"],
                    fmt["width"],
                ),
            )

        return min(
            known_size,
            key=lambda fmt: fmt["filesize"],
        )

    return max(
        video_formats,
        key=lambda fmt: (
            fmt["height"],
            fmt["width"],
        ),
    )


# ============================================================
# PET RELEVANCE
# ============================================================

PET_KEYWORDS = {
    "dog": 5,
    "puppy": 5,
    "cat": 5,
    "kitten": 5,
    "pet": 4,
    "puppy": 5,
    "animal": 3,
    "animals": 3,
    "doggo": 5,
    "pup": 4,
    "kitty": 5,
    "kitten": 5,
    "feline": 4,
    "canine": 4,
    "bird": 3,
    "parrot": 4,
    "rabbit": 4,
    "bunny": 4,
    "hamster": 4,
    "guinea pig": 4,
    "horse": 3,
    "duck": 3,
    "goose": 3,
    "otter": 3,
    "panda": 3,
    "monkey": 3,
}


def calculate_pet_relevance(metadata):
    """
    Estimate whether the post is about animals/pets using
    available title/description/uploader metadata.

    This is deliberately conservative.
    """

    text_parts = [
        metadata.get("title") or "",
        metadata.get("description") or "",
        metadata.get("uploader") or "",
        metadata.get("channel") or "",
    ]

    text = " ".join(text_parts).lower()

    score = 0
    matched = []

    for keyword, weight in PET_KEYWORDS.items():

        if keyword in text:

            score += weight
            matched.append(keyword)

    return score, matched


# ============================================================
# ENGAGEMENT SCORE
# ============================================================

def calculate_engagement_score(metadata):
    """
    Calculate a logarithmic engagement score.

    Logarithmic scoring prevents a viral post with millions
    of views from completely dominating every other factor.
    """

    views = safe_number(
        metadata.get("view_count")
    )

    likes = safe_number(
        metadata.get("like_count")
    )

    comments = safe_number(
        metadata.get("comment_count")
    )

    reposts = safe_number(
        metadata.get("repost_count")
    )

    score = (
        math.log10(views + 1) * 10
        + math.log10(likes + 1) * 8
        + math.log10(comments + 1) * 5
        + math.log10(reposts + 1) * 6
    )

    return round(score, 2)


# ============================================================
# QUALITY SCORE
# ============================================================

def calculate_quality_score(video_format):
    if not video_format:
        return 0

    width = video_format.get("width", 0)
    height = video_format.get("height", 0)

    score = 0

    if height >= 1080:
        score += 10
    elif height >= 720:
        score += 8
    elif height >= 480:
        score += 5
    elif height > 0:
        score += 2

    if width >= 1920:
        score += 3
    elif width >= 1280:
        score += 2

    return score


# ============================================================
# VALIDATION
# ============================================================

def validate_candidate(url):
    metadata = extract_metadata(url)

    if not metadata:
        return None

    duration = safe_number(
        metadata.get("duration")
    )

    if duration < MIN_DURATION:

        print(
            f"REJECTED: duration {duration:.1f}s "
            f"is below {MIN_DURATION}s."
        )

        return None

    if duration > MAX_DURATION:

        print(
            f"REJECTED: duration {duration:.1f}s "
            f"is above {MAX_DURATION}s."
        )

        return None

    video_format = get_best_video_format(
        metadata
    )

    if not video_format:

        print(
            "REJECTED: no video format."
        )

        return None

    size = video_format.get(
        "filesize",
        0
    )

    if size:

        size_mb = size / (
            1024 * 1024
        )

        if size_mb > MAX_FILE_SIZE_MB:

            print(
                f"REJECTED: selected format "
                f"is {size_mb:.1f} MB."
            )

            return None

    relevance_score, matched_keywords = (
        calculate_pet_relevance(metadata)
    )

    if relevance_score <= 0:

        print(
            "REJECTED: no obvious pet/animal "
            "relevance."
        )

        return None

    engagement_score = (
        calculate_engagement_score(
            metadata
        )
    )

    quality_score = (
        calculate_quality_score(
            video_format
        )
    )

    total_score = round(
        relevance_score
        + engagement_score
        + quality_score,
        2,
    )

    result = {
        "url": metadata.get(
            "webpage_url"
        ) or url,

        "id": metadata.get("id"),

        "title": metadata.get(
            "title"
        ),

        "uploader": metadata.get(
            "uploader"
        ),

        "duration": duration,

        "view_count": metadata.get(
            "view_count"
        ),

        "like_count": metadata.get(
            "like_count"
        ),

        "comment_count": metadata.get(
            "comment_count"
        ),

        "repost_count": metadata.get(
            "repost_count"
        ),

        "pet_relevance_score": relevance_score,

        "matched_pet_keywords": (
            matched_keywords
        ),

        "engagement_score": (
            engagement_score
        ),

        "quality_score": (
            quality_score
        ),

        "total_score": total_score,

        "video_format": video_format,
    }

    return result


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

    urls = load_candidates()

    print(
        f"\nCandidates to validate: {len(urls)}"
    )

    validated = []

    seen_ids = set()

    for index, url in enumerate(
        urls,
        start=1,
    ):

        print(
            f"\nCandidate {index}/{len(urls)}"
        )

        result = validate_candidate(
            url
        )

        if not result:
            continue

        tweet_id = result.get("id")

        if tweet_id and tweet_id in seen_ids:

            print(
                "REJECTED: duplicate."
            )

            continue

        if tweet_id:
            seen_ids.add(tweet_id)

        validated.append(result)

        print(
            "\nACCEPTED"
        )

        print(
            f"Title: {result['title']}"
        )

        print(
            f"Duration: "
            f"{result['duration']:.1f}s"
        )

        print(
            f"Views: "
            f"{format_number(result['view_count'])}"
        )

        print(
            f"Likes: "
            f"{format_number(result['like_count'])}"
        )

        print(
            f"Pet relevance: "
            f"{result['pet_relevance_score']}"
        )

        print(
            f"Engagement: "
            f"{result['engagement_score']}"
        )

        print(
            f"Quality: "
            f"{result['quality_score']}"
        )

        print(
            f"TOTAL SCORE: "
            f"{result['total_score']}"
        )

    validated.sort(
        key=lambda item: item["total_score"],
        reverse=True,
    )

    selected = validated[
        :MAX_SELECTED
    ]

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

    print("\n")
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

    print("\nSELECTED CONTENT:")

    for index, item in enumerate(
        selected,
        start=1,
    ):

        print(
            f"{index}. "
            f"{item['total_score']} | "
            f"{item['title']} | "
            f"{item['url']}"
        )


if __name__ == "__main__":
    main()
