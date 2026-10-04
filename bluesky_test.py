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

import requests
import yt_dlp


API_URL = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"

SEARCH_TERMS = [
    "cat",
    "cats",
    "kitten",
    "dog",
    "dogs",
    "puppy",
    "pet",
    "pets",
    "animal",
    "animals",
    "cute animal",
    "funny animal",
    "cute cat",
    "cute dog",
    "funny cat",
    "funny dog",
]

SEARCH_LIMIT = 100
MAX_PAGES_PER_TERM = 2

MIN_DURATION = 15
MAX_DURATION = 180

MAX_FILE_SIZE = 48 * 1024 * 1024

MAX_SELECTED = 20

REQUEST_TIMEOUT = 30

HISTORY_FILE = Path("history.json")
OUTPUT_FILE = Path("bluesky_selected_candidates.json")
RAW_OUTPUT_FILE = Path("bluesky_candidates.json")

DOWNLOAD_DIR = Path("bluesky_downloads")


ANIMAL_KEYWORDS = {
    "cat": 20,
    "cats": 20,
    "kitten": 22,
    "kittens": 22,
    "dog": 20,
    "dogs": 20,
    "puppy": 22,
    "puppies": 22,
    "pet": 14,
    "pets": 16,
    "animal": 16,
    "animals": 18,
    "bird": 16,
    "birds": 18,
    "parrot": 18,
    "rabbit": 18,
    "bunny": 18,
    "hamster": 18,
    "guinea pig": 18,
    "horse": 16,
    "pony": 16,
    "cow": 14,
    "goat": 16,
    "sheep": 14,
    "chicken": 14,
    "duck": 14,
    "duckling": 18,
    "panda": 18,
    "fox": 16,
    "otter": 18,
    "seal": 18,
    "penguin": 18,
    "koala": 18,
    "hedgehog": 18,
    "wildlife": 18,
}

FUNNY_KEYWORDS = {
    "funny": 8,
    "hilarious": 10,
    "lol": 5,
    "laugh": 6,
    "silly": 6,
    "fails": 6,
    "failure": 6,
    "chaos": 5,
    "adorable": 6,
    "cute": 7,
    "aww": 8,
    "wholesome": 7,
    "fun": 4,
}

NEGATIVE_KEYWORDS = {
    "kill": -30,
    "killed": -30,
    "dead": -25,
    "death": -30,
    "injury": -25,
    "injured": -25,
    "blood": -40,
    "violence": -30,
    "abuse": -40,
    "attack": -15,
    "attacked": -15,
    "fight": -12,
    "fighting": -12,
    "nsfw": -50,
}


def normalize_text(value):
    if not value:
        return ""

    value = html.unescape(str(value))

    value = re.sub(r"https?://\S+", "", value)

    value = re.sub(
        r"(?<!\w)#[\w]+",
        "",
        value,
        flags=re.UNICODE,
    )

    value = value.replace("\r\n", "\n")
    value = value.replace("\r", "\n")

    lines = []

    for line in value.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()

        if line:
            lines.append(line)

    return "\n".join(lines)


def clean_caption(value):
    value = normalize_text(value)

    if not value:
        return ""

    paragraphs = value.split("\n")

    cleaned = []

    for paragraph in paragraphs:
        paragraph = paragraph.strip()

        if not paragraph:
            continue

        cleaned.append(paragraph)

    return "\n".join(cleaned)


def build_post_url(post):
    author = post.get("author") or {}
    handle = author.get("handle")

    uri = post.get("uri", "")

    if not handle or not uri:
        return ""

    rkey = uri.rstrip("/").split("/")[-1]

    if not rkey:
        return ""

    return f"https://bsky.app/profile/{handle}/post/{rkey}"


def contains_video_embed(embed):
    if not isinstance(embed, dict):
        return False

    embed_type = embed.get("$type", "")

    if embed_type == "app.bsky.embed.video#view":
        return True

    if embed_type == "app.bsky.embed.recordWithMedia#view":
        media = embed.get("media")

        if isinstance(media, dict):
            return contains_video_embed(media)

    return False


def search_bluesky(term, cursor=None):
    params = {
        "q": term,
        "limit": SEARCH_LIMIT,
    }

    if cursor:
        params["cursor"] = cursor

    response = requests.get(
        API_URL,
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": "UTCutieDiscovery/1.0",
            "Accept": "application/json",
        },
    )

    response.raise_for_status()

    return response.json()


def get_video_metadata(post_url, output_dir):
    output_template = str(output_dir / "%(id)s.%(ext)s")

    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": output_template,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "socket_timeout": 30,
        "retries": 2,
        "fragment_retries": 2,
        "max_filesize": MAX_FILE_SIZE,
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(
                post_url,
                download=True,
            )

        if not info:
            return None

        requested = info.get("requested_downloads") or []

        filepath = None

        if requested:
            filepath = requested[0].get("filepath")

        if not filepath:
            filepath = info.get("_filename")

        if not filepath:
            files = list(output_dir.glob("*"))

            if files:
                filepath = str(files[0])

        if not filepath:
            return None

        path = Path(filepath)

        if not path.exists():
            return None

        return {
            "path": path,
            "duration": info.get("duration"),
            "view_count": info.get("view_count") or 0,
            "like_count": info.get("like_count") or 0,
            "comment_count": info.get("comment_count") or 0,
        }

    except Exception as exc:
        print(
            f"DOWNLOAD FAILED: {post_url}\n"
            f"Reason: {exc}"
        )

        return None


def validate_video(path):
    if not path.exists():
        return None

    file_size = path.stat().st_size

    if file_size <= 0:
        return None

    if file_size > MAX_FILE_SIZE:
        return None

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-show_entries",
        "stream=codec_type",
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
            check=True,
        )

        data = json.loads(result.stdout)

    except Exception:
        return None

    streams = data.get("streams") or []

    has_video = any(
        stream.get("codec_type") == "video"
        for stream in streams
    )

    if not has_video:
        return None

    duration = None

    try:
        duration = float(
            (data.get("format") or {}).get("duration")
        )
    except (TypeError, ValueError):
        return None

    if duration is None:
        return None

    if duration < MIN_DURATION:
        return None

    if duration > MAX_DURATION:
        return None

    return {
        "duration": round(duration, 3),
        "file_size": file_size,
    }


def sha256_file(path):
    digest = hashlib.sha256()

    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def text_score(text):
    text_lower = text.lower()

    animal_score = 0
    funny_score = 0
    negative_score = 0

    for keyword, value in ANIMAL_KEYWORDS.items():
        if keyword in text_lower:
            animal_score += value

    for keyword, value in FUNNY_KEYWORDS.items():
        if keyword in text_lower:
            funny_score += value

    for keyword, value in NEGATIVE_KEYWORDS.items():
        if keyword in text_lower:
            negative_score += value

    return animal_score, funny_score, negative_score


def engagement_score(post):
    like_count = int(post.get("likeCount") or 0)
    repost_count = int(post.get("repostCount") or 0)
    reply_count = int(post.get("replyCount") or 0)
    quote_count = int(post.get("quoteCount") or 0)

    raw = (
        like_count
        + repost_count * 2
        + reply_count
        + quote_count * 2
    )

    if raw <= 0:
        return 0

    score = 0

    if raw >= 10:
        score += 10

    if raw >= 50:
        score += 10

    if raw >= 250:
        score += 15

    if raw >= 1000:
        score += 15

    if raw >= 5000:
        score += 15

    if raw >= 20000:
        score += 15

    return min(score, 80)


def recency_score(post):
    created_at = (
        (post.get("record") or {}).get("createdAt")
        or ""
    )

    if not created_at:
        return 0

    try:
        created = datetime.fromisoformat(
            created_at.replace("Z", "+00:00")
        )

        age_hours = (
            datetime.now(timezone.utc) - created
        ).total_seconds() / 3600

    except Exception:
        return 0

    if age_hours < 6:
        return 30

    if age_hours < 24:
        return 25

    if age_hours < 72:
        return 18

    if age_hours < 168:
        return 10

    return 3


def quality_score(duration, file_size):
    score = 0

    if 20 <= duration <= 120:
        score += 20
    else:
        score += 10

    size_mb = file_size / (1024 * 1024)

    if size_mb <= 15:
        score += 15
    elif size_mb <= 30:
        score += 10
    else:
        score += 5

    return score


def load_history():
    if not HISTORY_FILE.exists():
        return []

    try:
        with HISTORY_FILE.open(
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

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
            "source_url",
            "status_url",
            "sha256",
        ):
            value = item.get(field)

            if value:
                keys.add(str(value))

    return keys


def already_in_history(candidate, keys):
    values = {
        candidate.get("media_url"),
        candidate.get("source_url"),
        candidate.get("sha256"),
    }

    values.discard(None)
    values.discard("")

    return bool(values & keys)


def process_search_results():
    all_posts = {}

    for term in SEARCH_TERMS:
        print()
        print(f"SEARCH: {term}")

        cursor = None

        for page in range(MAX_PAGES_PER_TERM):
            try:
                data = search_bluesky(
                    term,
                    cursor=cursor,
                )

            except Exception as exc:
                print(
                    f"SEARCH FAILED: {term} | {exc}"
                )
                break

            posts = data.get("posts") or []

            print(
                f"  Page {page + 1}: "
                f"{len(posts)} posts"
            )

            for post in posts:
                uri = post.get("uri")

                if uri:
                    all_posts[uri] = post

            cursor = data.get("cursor")

            if not cursor:
                break

    return list(all_posts.values())


def main():
    print("=" * 70)
    print("UTCUTIE BLUESKY DISCOVERY")
    print("=" * 70)

    DOWNLOAD_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    history = load_history()
    history_keys_set = history_keys(history)

    print(
        f"Publication history entries: "
        f"{len(history)}"
    )

    posts = process_search_results()

    print()
    print(
        f"Unique Bluesky posts discovered: "
        f"{len(posts)}"
    )

    candidates = []
    seen_media = set()
    seen_hashes = set()

    for index, post in enumerate(posts, start=1):
        embed = post.get("embed")

        if not contains_video_embed(embed):
            continue

        post_url = build_post_url(post)

        if not post_url:
            continue

        record = post.get("record") or {}
        caption = clean_caption(
            record.get("text", "")
        )

        combined_text = " ".join(
            [
                caption,
                post.get("author", {}).get(
                    "displayName",
                    "",
                ),
                post.get("author", {}).get(
                    "handle",
                    "",
                ),
            ]
        )

        (
            animal_score,
            funny_score,
            negative_score,
        ) = text_score(combined_text)

        if animal_score < 14:
            continue

        if negative_score <= -25:
            continue

        print()
        print(
            f"[{index}/{len(posts)}] "
            f"Checking video: {post_url}"
        )

        temp_dir = Path(
            tempfile.mkdtemp(
                prefix="utc_bsky_",
                dir=str(DOWNLOAD_DIR),
            )
        )

        try:
            metadata = get_video_metadata(
                post_url,
                temp_dir,
            )

            if not metadata:
                continue

            validation = validate_video(
                metadata["path"]
            )

            if not validation:
                continue

            file_hash = sha256_file(
                metadata["path"]
            )

            if file_hash in seen_hashes:
                continue

            seen_hashes.add(file_hash)

            file_size = validation["file_size"]
            duration = validation["duration"]

            media_url = ""

            embed_view = embed

            if (
                isinstance(embed_view, dict)
                and embed_view.get(
                    "$type"
                ) == "app.bsky.embed.recordWithMedia#view"
            ):
                embed_view = embed_view.get(
                    "media"
                )

            if isinstance(embed_view, dict):
                media_url = (
                    embed_view.get(
                        "playlist"
                    )
                    or ""
                )

            if media_url and media_url in seen_media:
                continue

            if media_url:
                seen_media.add(media_url)

            candidate = {
                "source": "bluesky",
                "source_url": post_url,
                "status_url": post_url,
                "media_url": media_url,
                "caption": caption,
                "duration": duration,
                "file_size": file_size,
                "sha256": file_hash,
                "like_count": int(
                    post.get("likeCount") or 0
                ),
                "repost_count": int(
                    post.get("repostCount") or 0
                ),
                "reply_count": int(
                    post.get("replyCount") or 0
                ),
                "quote_count": int(
                    post.get("quoteCount") or 0
                ),
                "account": (
                    post.get("author", {})
                    .get("handle", "")
                ),
                "account_name": (
                    post.get("author", {})
                    .get("displayName", "")
                ),
                "created_at": (
                    record.get("createdAt", "")
                ),
                "animal_score": animal_score,
                "funny_score": funny_score,
                "negative_score": negative_score,
            }

            engagement = engagement_score(post)
            recency = recency_score(post)
            quality = quality_score(
                duration,
                file_size,
            )

            total_score = (
                animal_score * 2
                + funny_score
                + engagement
                + recency
                + quality
                + negative_score
            )

            candidate["engagement_score"] = engagement
            candidate["recency_score"] = recency
            candidate["quality_score"] = quality
            candidate["score"] = round(
                total_score,
                3,
            )

            if already_in_history(
                candidate,
                history_keys_set,
            ):
                candidate["history_match"] = True
            else:
                candidate["history_match"] = False

            candidates.append(candidate)

        finally:
            shutil.rmtree(
                temp_dir,
                ignore_errors=True,
            )

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    fresh = [
        candidate
        for candidate in candidates
        if not candidate["history_match"]
    ]

    selected = fresh[:MAX_SELECTED]

    with RAW_OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            candidates,
            f,
            ensure_ascii=False,
            indent=2,
        )

    with OUTPUT_FILE.open(
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
    print("BLUESKY DISCOVERY COMPLETE")
    print("=" * 70)
    print(
        f"Unique posts: {len(posts)}"
    )
    print(
        f"Validated animal videos: "
        f"{len(candidates)}"
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
    print(
        f"Raw results: {RAW_OUTPUT_FILE}"
    )
    print(
        f"Selected results: {OUTPUT_FILE}"
    )

    for number, candidate in enumerate(
        selected,
        start=1,
    ):
        print()
        print(
            f"{number:02d}. "
            f"score={candidate['score']} | "
            f"{candidate['duration']} sec | "
            f"{candidate['file_size']} bytes"
        )
        print(
            candidate["source_url"]
        )
        print(
            candidate["caption"][:300]
        )


if __name__ == "__main__":
    main()
