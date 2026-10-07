import hashlib
import html
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import cv2
import numpy as np


INSTANCES = [
    "https://mastodon.social",
    "https://mastodon.online",
    "https://mastodon.world",
    "https://mstdn.party",
]

HASHTAGS = [
    "cats",
    "cat",
    "kittens",
    "kitten",
    "dogs",
    "dog",
    "puppies",
    "puppy",
    "pets",
    "animals",
    "aww",
    "cuteanimals",
    "funnyanimals",
    "petsofthefediverse",
    "funnycats",
    "funnydogs",
    "animalvideos",
    "catvideos",
    "dogvideos",
    "petvideos",
    "cutecats",
    "cutedogs",
    "wholesomeanimals",
    "animalsofmastodon",
    "petstodon",
    "catsofthefediverse",
    "dogsofthefediverse",
]

MAX_PAGES_PER_TAG = 5
STATUSES_PER_PAGE = 40

MIN_DURATION = 15.0
MAX_DURATION = 180.0
MAX_FILE_SIZE = 48 * 1024 * 1024

PRIMARY_DAYS = 14
SECONDARY_DAYS = 30
EMERGENCY_DAYS = 60

MAX_SELECTED = 20
MAX_DOWNLOAD_ATTEMPTS = 40
REQUEST_TIMEOUT = 25
VISUAL_SAMPLE_COUNT = 3
VISUAL_NET = None
VISUAL_CONFIDENCE = 0.45
VISUAL_MODEL_DIR = Path(".visual_model")
VISUAL_PROTO = VISUAL_MODEL_DIR / "deploy.prototxt"
VISUAL_WEIGHTS = VISUAL_MODEL_DIR / "mobilenet_iter_73000.caffemodel"
VISUAL_PROTO_URL = "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/deploy.prototxt"
VISUAL_WEIGHTS_URL = "https://github.com/chuanqi305/MobileNet-SSD/raw/master/mobilenet_iter_73000.caffemodel"

VOC_CLASSES = [
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle",
    "bus", "car", "cat", "chair", "cow", "diningtable", "dog",
    "horse", "motorbike", "person", "pottedplant", "sheep", "sofa",
    "train", "tvmonitor",
]
VISUAL_ANIMAL_CLASSES = {"bird", "cat", "cow", "dog", "horse", "sheep"}

HISTORY_FILE = Path("history.json")
SELECTED_FILE = Path("selected_candidates.json")
VALIDATED_FILE = Path("validated_candidates.json")
DISCOVERY_FILE = Path("mastodon_candidates.json")


ANIMAL_TERMS = {
    "cat", "cats", "kitten", "kittens", "kitty", "kitties",
    "dog", "dogs", "puppy", "puppies", "pup", "pups",
    "pet", "pets", "animal", "animals",
    "rabbit", "rabbits", "bunny", "bunnies",
    "hamster", "hamsters", "guinea pig", "guinea pigs",
    "bird", "birds", "parrot", "parrots", "duck", "ducks",
    "goose", "geese", "chicken", "chickens", "hen", "hens",
    "cow", "cows", "calf", "calves", "goat", "goats",
    "sheep", "lamb", "lambs", "horse", "horses", "foal",
    "pig", "pigs", "piglet", "piglets", "donkey", "donkeys",
    "fox", "foxes", "raccoon", "raccoons", "hedgehog", "hedgehogs",
    "deer", "deers", "fawn", "fawns", "squirrel", "squirrels",
    "otter", "otters", "seal", "seals", "penguin", "penguins",
    "turtle", "turtles", "tortoise", "tortoises",
    "frog", "frogs", "snake", "snakes", "lizard", "lizards",
    "fish", "goldfish", "monkey", "monkeys", "bear", "bears",
    "koala", "koalas", "panda", "pandas", "lion", "lions",
    "tiger", "tigers", "elephant", "elephants", "giraffe",
    "zebra", "wolf", "wolves", "birdie", "kitty",
}

PET_CONTEXT_TERMS = {
    "cute", "adorable", "funny", "hilarious", "lol", "laugh",
    "humor", "humour", "silly", "goofy", "play", "playing",
    "playtime", "sleeping", "sleep", "nap", "zoomies", "chasing",
    "chase", "running", "jumping", "jump", "playing with",
    "best friend", "friend", "family", "home", "backyard",
    "sunshine", "sunny", "snuggle", "snuggling", "cuddle",
    "cuddling", "wholesome", "happy", "heartwarming", "sweet",
    "reaction", "fails", "funny video", "cute video",
    "pet life", "pets", "animal video", "animal videos",
}

ADVOCACY_TERMS = {
    "rescue", "rescued", "adopt", "adopted", "adoption",
    "shelter", "foster", "fostering", "sanctuary",
    "farm sanctuary", "vegan", "vegetarian", "animal welfare",
    "animal rights", "animal activism", "activism", "campaign",
    "petition", "donate", "donation", "fundraiser", "fundraising",
    "save the animals", "meat farm",
}

IRRELEVANT_TERMS = {
    "org chart", "hierarchy", "leadership", "management",
    "sociopath", "workplace", "corporate", "company",
    "career", "linkedin", "audit", "marketing strategy",
    "business strategy", "politics", "political campaign",
    "election", "sports", "football", "soccer", "basketball",
    "baseball", "hockey", "tennis",
    "keychain", "unboxing", "product", "portrait commission",
    "custom art", "custom portrait", "merch", "merchandise",
}

PROMO_TERMS = {
    "subscribe", "follow us", "follow me", "link in bio",
    "wishlist", "buy now", "shop now", "limited edition",
    "available now", "order now", "support my patreon",
}

MUSIC_TERMS = {
    "kevin macleod", "incompetech", "creative commons",
    "music by", "licensed music", "royalty free music",
}

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
HASHTAG_RE = re.compile(r"(?u)(?<!\w)#\s*\w+")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")


def normalize_text(value):
    if value is None:
        return ""
    value = html.unescape(str(value))
    value = re.sub(r"<script[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"</(p|div|li|blockquote|h[1-6])\s*>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return value


def clean_caption(caption):
    text = normalize_text(caption)
    text = URL_RE.sub(" ", text)
    text = HASHTAG_RE.sub(" ", text)
    text = PHONE_RE.sub(" ", text)

    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue

        low = line.casefold()

        if any(term in low for term in MUSIC_TERMS):
            continue

        if any(term in low for term in PROMO_TERMS):
            continue

        lines.append(line)

    result = "\n".join(lines)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()

    if len(result) > 900:
        result = result[:900].rsplit(" ", 1)[0].rstrip(".,;:-")

    return result


def contains_phrase(text, phrase):
    text = f" {text.casefold()} "
    phrase = phrase.casefold().strip()
    return f" {phrase} " in text or phrase in text


def text_terms(text, terms):
    text = text.casefold()
    return {term for term in terms if contains_phrase(text, term)}


def content_gate(status):
    caption = normalize_text(status.get("content", ""))
    caption_without_hashtags = HASHTAG_RE.sub(" ", caption)
    low_caption = caption_without_hashtags.casefold()

    media = status.get("media_url", "") or ""
    media_name = Path(urlparse(media).path).name.casefold()

    caption_animals = text_terms(caption_without_hashtags, ANIMAL_TERMS)
    tag_names = {
        str(tag.get("name", "")).casefold().replace("_", " ")
        for tag in status.get("tags", [])
        if isinstance(tag, dict)
    }
    tag_animals = {term for term in ANIMAL_TERMS if term in tag_names}

    pet_context = text_terms(low_caption, PET_CONTEXT_TERMS)
    advocacy = text_terms(low_caption, ADVOCACY_TERMS)
    irrelevant = text_terms(low_caption, IRRELEVANT_TERMS)

    if advocacy:
        if any(term in low_caption for term in {
            "sanctuary", "vegan", "vegetarian", "animal welfare",
            "animal rights", "activism", "campaign", "petition",
            "fundraiser", "donate",
        }):
            return False, 0, "advocacy/sanctuary content"
        return False, 0, "rescue/advocacy content"

    if irrelevant:
        return False, 0, "irrelevant non-animal content"

    filename_animal = text_terms(media_name, ANIMAL_TERMS)

    if caption_animals:
        score = min(45, 30 + len(caption_animals) * 3)
        if pet_context:
            score += min(10, len(pet_context) * 2)
        return True, min(55, score), "passed"

    if tag_animals and pet_context:
        return True, min(45, 24 + len(tag_animals) * 3 + len(pet_context) * 2), "passed"

    if filename_animal and pet_context:
        return True, 35, "passed"

    return False, 0, "no animal evidence"


def freshness_days(created_at):
    if not created_at:
        return 9999.0
    try:
        created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - created).total_seconds()
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


def canonical_status_url(url):
    if not url:
        return ""

    url = str(url).strip().rstrip("/")

    bridge = re.match(
        r"^https?://[^/]+/r/(https?://.+)$",
        url,
        flags=re.I,
    )
    if bridge:
        url = bridge.group(1).rstrip("/")

    return url


def canonical_key(status):
    canonical = canonical_status_url(status.get("url"))
    if canonical:
        return f"url:{canonical}"

    sha = status.get("sha256")
    if sha:
        return f"sha:{sha}"

    media = status.get("media_url")
    if media:
        return f"media:{media}"

    return ""


def load_history():
    if not HISTORY_FILE.exists():
        return []

    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def history_keys(history):
    keys = set()

    for item in history:
        if not isinstance(item, dict):
            continue

        for field in ("canonical_url", "url", "source_url"):
            value = canonical_status_url(item.get(field))
            if value:
                keys.add(f"url:{value}")

        if item.get("sha256"):
            keys.add(f"sha:{item['sha256']}")

        if item.get("media_url"):
            keys.add(f"media:{item['media_url']}")

    return keys


def get_statuses(instance, tag, max_id=None):
    url = f"{instance.rstrip('/')}/api/v1/timelines/tag/{tag}"
    params = {
        "limit": STATUSES_PER_PAGE,
        "local": "false",
    }
    if max_id:
        params["max_id"] = max_id

    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": "UTCutieDiscovery/1.0"},
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 200:
        print(f"{instance} #{tag}: HTTP {response.status_code}")
        return []

    print(f"{instance} #{tag}: HTTP 200")
    try:
        payload = response.json()
    except Exception:
        return []

    return payload if isinstance(payload, list) else []


def extract_video_candidates(statuses, instance):
    candidates = []

    for status in statuses:
        attachments = status.get("media_attachments", [])
        if not isinstance(attachments, list):
            continue

        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue

            media_type = str(attachment.get("type", "")).casefold()
            media_url = (
                attachment.get("url")
                or attachment.get("remote_url")
                or attachment.get("preview_url")
                or ""
            )

            if media_type != "video" or not media_url:
                continue

            candidate = {
                "id": status.get("id"),
                "url": status.get("url", ""),
                "canonical_url": canonical_status_url(status.get("url", "")),
                "account": (
                    status.get("account", {}).get("acct", "")
                    if isinstance(status.get("account"), dict)
                    else ""
                ),
                "instance": instance,
                "created_at": status.get("created_at"),
                "content": status.get("content", ""),
                "caption": clean_caption(status.get("content", "")),
                "tags": status.get("tags", []),
                "media_url": media_url,
                "media_type": media_type,
                "media_description": attachment.get("description", "") or "",
                "media_meta": attachment.get("meta", {}) or {},
            }

            candidate["canonical_key"] = canonical_key(candidate)
            candidates.append(candidate)

    return candidates


def candidate_copy_rank(candidate):
    size = advertised_size(candidate)
    if size is None:
        size_rank = 1
        size_value = 0
    elif size <= MAX_FILE_SIZE:
        size_rank = 2
        size_value = size
    else:
        size_rank = 0
        size_value = size

    meta = candidate.get("media_meta") or {}
    video_meta = meta.get("video") if isinstance(meta.get("video"), dict) else {}
    bitrate = int(video_meta.get("bitrate") or 0)

    original = meta.get("original") if isinstance(meta.get("original"), dict) else {}
    width = int(original.get("width") or meta.get("width") or 0)
    height = int(original.get("height") or meta.get("height") or 0)

    return (
        size_rank,
        width * height,
        bitrate,
        -size_value if size_value else 0,
        -len(str(candidate.get("media_url") or "")),
    )


def deduplicate_candidates(candidates):
    by_key = {}

    for candidate in candidates:
        key = candidate.get("canonical_key") or canonical_key(candidate)

        if not key:
            continue

        existing = by_key.get(key)

        if existing is None or candidate_copy_rank(candidate) > candidate_copy_rank(existing):
            by_key[key] = candidate

    return list(by_key.values())


def unique_canonical_count(candidates):
    keys = set()
    for candidate in candidates:
        key = candidate.get("canonical_key") or canonical_key(candidate)
        if key:
            keys.add(key)
    return len(keys)


def advertised_size(candidate):
    meta = candidate.get("media_meta") or {}

    for key in ("size", "file_size", "filesize"):
        value = meta.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return int(value)

    original = meta.get("original")
    if isinstance(original, dict):
        value = original.get("size") or original.get("filesize")
        if isinstance(value, (int, float)) and value > 0:
            return int(value)

    return None


def preflight_size(candidate):
    known = advertised_size(candidate)
    if known is not None:
        candidate["advertised_file_size"] = known
        if known > MAX_FILE_SIZE:
            return False, "file too large"
        return True, ""

    headers = {"User-Agent": "UTCutieDiscovery/1.0"}

    try:
        response = requests.head(
            candidate["media_url"],
            allow_redirects=True,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            value = response.headers.get("Content-Length")
            if value and value.isdigit():
                size = int(value)
                candidate["advertised_file_size"] = size
                if size > MAX_FILE_SIZE:
                    return False, "file too large"
                return True, ""
    except Exception:
        pass

    # Some Mastodon media hosts do not answer HEAD correctly. A one-byte
    # range request can still reveal the complete object size via Content-Range.
    try:
        response = requests.get(
            candidate["media_url"],
            headers={**headers, "Range": "bytes=0-0"},
            allow_redirects=True,
            stream=True,
            timeout=REQUEST_TIMEOUT,
        )

        content_range = response.headers.get("Content-Range", "")
        match = re.search(r"/([0-9]+)$", content_range)
        if match:
            size = int(match.group(1))
            candidate["advertised_file_size"] = size
            if size > MAX_FILE_SIZE:
                response.close()
                return False, "file too large"
            response.close()
            return True, ""

        value = response.headers.get("Content-Length")
        if value and value.isdigit():
            size = int(value)
            candidate["advertised_file_size"] = size
            response.close()
            if size > MAX_FILE_SIZE:
                return False, "file too large"
            return True, ""

        response.close()
    except Exception:
        pass

    return True, ""


def ensure_visual_model():
    VISUAL_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if not VISUAL_PROTO.exists():
        response = requests.get(VISUAL_PROTO_URL, timeout=30)
        response.raise_for_status()
        VISUAL_PROTO.write_bytes(response.content)
    if not VISUAL_WEIGHTS.exists():
        response = requests.get(VISUAL_WEIGHTS_URL, timeout=120)
        response.raise_for_status()
        VISUAL_WEIGHTS.write_bytes(response.content)


def get_visual_net():
    global VISUAL_NET
    if VISUAL_NET is None:
        ensure_visual_model()
        VISUAL_NET = cv2.dnn.readNet(
            str(VISUAL_WEIGHTS),
            str(VISUAL_PROTO),
            "Caffe",
        )
    return VISUAL_NET


def visual_media_gate(path):
    """Reject media with a detected person but no detected target animal.

    This is a conservative media-relevance gate, not a general NSFW classifier.
    It is specifically designed to stop caption-only false positives such as
    a human pretending to be a puppy. Videos with no detected person are not
    rejected solely because this small VOC model cannot recognize every animal
    species.
    """
    net = get_visual_net()
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return False, "visual gate: cannot open video"

    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        if frame_count <= 0 or fps <= 0:
            return False, "visual gate: unknown frame data"

        sample_indices = np.linspace(0, max(0, frame_count - 1), VISUAL_SAMPLE_COUNT, dtype=int)
        person_seen = False
        animal_seen = set()
        usable_frames = 0

        for frame_index in sorted(set(int(x) for x in sample_indices)):
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            usable_frames += 1

            blob = cv2.dnn.blobFromImage(
                cv2.resize(frame, (300, 300)),
                0.007843,
                (300, 300),
                127.5,
            )
            net.setInput(blob)
            detections = net.forward()

            for detection in detections[0, 0, :, :]:
                confidence = float(detection[2])
                if confidence < VISUAL_CONFIDENCE:
                    continue
                class_id = int(detection[1])
                if not 0 <= class_id < len(VOC_CLASSES):
                    continue
                label = VOC_CLASSES[class_id]
                if label == "person":
                    person_seen = True
                elif label in VISUAL_ANIMAL_CLASSES:
                    animal_seen.add(label)

        if usable_frames == 0:
            return False, "visual gate: no readable frames"

        if person_seen and not animal_seen:
            return False, "visual gate: person detected without animal"

        return True, ""
    finally:
        capture.release()



def video_info(path):
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            return None

        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

        if fps <= 0 or frame_count <= 0:
            return None

        duration = frame_count / fps
        if duration <= 0:
            return None

        return {
            "duration": duration,
            "width": width,
            "height": height,
            "codec_name": "",
        }
    finally:
        capture.release()


def download_and_validate(candidate):
    media_url = candidate["media_url"]

    with tempfile.TemporaryDirectory(prefix="utcutie_") as tmp:
        path = Path(tmp) / "video.mp4"

        try:
            with requests.get(
                media_url,
                stream=True,
                allow_redirects=True,
                headers={"User-Agent": "UTCutieDiscovery/1.0"},
                timeout=REQUEST_TIMEOUT,
            ) as response:
                if response.status_code != 200:
                    return None, f"HTTP {response.status_code}"

                content_type = response.headers.get("Content-Type", "").casefold()
                if "video" not in content_type and "octet-stream" not in content_type:
                    return None, "not video content"

                content_length = response.headers.get("Content-Length")
                if content_length and content_length.isdigit():
                    if int(content_length) > MAX_FILE_SIZE:
                        return None, "file too large"

                total = 0
                with path.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > MAX_FILE_SIZE:
                            return None, "file too large"
                        output.write(chunk)

            if total > MAX_FILE_SIZE:
                return None, "file too large"

            stream = video_info(path)
            if not stream:
                return None, "invalid video"

            duration = float(stream.get("duration") or 0)
            if duration < MIN_DURATION:
                return None, f"too short: {duration:.2f}s"

            if duration > MAX_DURATION:
                return None, f"too long: {duration:.2f}s"

            candidate["duration"] = round(duration, 3)
            candidate["file_size"] = total
            candidate["width"] = int(stream.get("width") or 0)
            candidate["height"] = int(stream.get("height") or 0)
            candidate["codec"] = stream.get("codec_name") or ""

            digest = hashlib.sha256()
            with path.open("rb") as hashed:
                for chunk in iter(lambda: hashed.read(1024 * 1024), b""):
                    digest.update(chunk)
            candidate["sha256"] = digest.hexdigest()

            visual_ok, visual_reason = visual_media_gate(path)
            if not visual_ok:
                return None, visual_reason

            return candidate, ""

        except requests.RequestException as exc:
            return None, f"download error: {exc}"
        except Exception as exc:
            return None, f"validation error: {exc}"


def quality_score(candidate):
    width = int(candidate.get("width") or 0)
    height = int(candidate.get("height") or 0)
    size = int(candidate.get("file_size") or 0)
    duration = float(candidate.get("duration") or 0)

    score = float(candidate.get("content_score") or 0)

    if width >= 1920 or height >= 1080:
        score += 18
    elif width >= 1280 or height >= 720:
        score += 13
    elif width >= 854 or height >= 480:
        score += 7
    else:
        score -= 5

    if size and duration:
        mb_per_minute = (size / 1024 / 1024) / max(duration / 60, 0.25)
        if mb_per_minute <= 12:
            score += 8
        elif mb_per_minute <= 24:
            score += 4
        elif mb_per_minute > 100:
            score -= 5

    if 18 <= duration <= 120:
        score += 5

    return round(score, 3)


def selection_score(candidate):
    age = float(candidate.get("age_days") or 9999)
    fresh_bonus = max(0.0, 25.0 - age)

    return round(
        float(candidate.get("quality_score") or 0)
        + fresh_bonus,
        3,
    )


def sort_for_selection(items):
    return sorted(
        items,
        key=lambda x: (
            x.get("freshness_tier") == "primary",
            x.get("selection_score", 0),
            x.get("content_score", 0),
            -x.get("age_days", 9999),
        ),
        reverse=True,
    )


def select_diverse(items):
    primary = [x for x in items if x.get("freshness_tier") == "primary"]
    secondary = [x for x in items if x.get("freshness_tier") == "secondary"]
    emergency = [x for x in items if x.get("freshness_tier") == "emergency"]

    ordered = (
        sort_for_selection(primary)
        + sort_for_selection(secondary)
        + sort_for_selection(emergency)
    )

    selected = []
    account_counts = {}
    canonical_seen = set()

    # First pass: no more than two from the same account.
    for candidate in ordered:
        key = candidate.get("canonical_key") or canonical_key(candidate)
        if key in canonical_seen:
            continue

        account = candidate.get("account") or "unknown"
        if account_counts.get(account, 0) >= 2:
            continue

        selected.append(candidate)
        canonical_seen.add(key)
        account_counts[account] = account_counts.get(account, 0) + 1

        if len(selected) >= MAX_SELECTED:
            return selected

    # Second pass: if fewer than 20 remain, fill from the best leftovers.
    for candidate in ordered:
        key = candidate.get("canonical_key") or canonical_key(candidate)
        if key in canonical_seen:
            continue

        selected.append(candidate)
        canonical_seen.add(key)

        if len(selected) >= MAX_SELECTED:
            break

    return selected


def write_json(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main():
    print("=" * 70)
    print("UTCutie Mastodon Video Discovery")
    print("=" * 70)
    print()
    print("Starting discovery...")
    print()

    raw_candidates = []

    for instance in INSTANCES:
        print("=" * 70)
        print(f"INSTANCE: {instance}")
        print("=" * 70)

        for tag in HASHTAGS:
            max_id = None

            for page in range(MAX_PAGES_PER_TAG):
                statuses = get_statuses(instance, tag, max_id=max_id)

                if not statuses:
                    break

                raw_candidates.extend(
                    extract_video_candidates(statuses, instance)
                )

                next_ids = [
                    str(item.get("id"))
                    for item in statuses
                    if item.get("id")
                ]

                if not next_ids:
                    break

                next_max_id = min(next_ids, key=lambda value: int(value))

                if next_max_id == max_id:
                    break

                max_id = next_max_id

    print()
    print(f"RAW VIDEO CANDIDATES: {len(raw_candidates)}")

    canonical_count = unique_canonical_count(raw_candidates)

    print(f"UNIQUE CANONICAL POST CANDIDATES: {canonical_count}")

    passed = []
    rejection_counts = {}

    # Keep alternate federated copies alive until size preflight. One copy can
    # be too large while another copy of the same post is Telegram-safe.
    for candidate in raw_candidates:
        age = freshness_days(candidate.get("created_at"))
        candidate["age_days"] = round(age, 3)
        candidate["freshness_tier"] = freshness_tier(age)

        if candidate["freshness_tier"] == "reject":
            rejection_counts["too old"] = rejection_counts.get("too old", 0) + 1
            continue

        ok, content_score, reason = content_gate(candidate)

        if not ok:
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            continue

        candidate["content_score"] = content_score

        size_ok, size_reason = preflight_size(candidate)
        if not size_ok:
            rejection_counts[size_reason] = rejection_counts.get(size_reason, 0) + 1
            continue

        passed.append(candidate)

    unique = deduplicate_candidates(passed)
    write_json(DISCOVERY_FILE, unique)

    print()
    print(f"CONTENT-GATE PASSED: {len(passed)}")
    print(f"UNIQUE SIZE-SAFE CANONICAL CANDIDATES: {len(unique)}")
    print("CONTENT-GATE / PREFLIGHT REJECTIONS:")

    for reason, count in sorted(rejection_counts.items()):
        print(f"  {reason}: {count}")

    history = load_history()
    published_keys = history_keys(history)

    fresh_for_history = []
    history_rejections = 0

    for candidate in unique:
        key = candidate.get("canonical_key") or canonical_key(candidate)

        if key in published_keys:
            history_rejections += 1
            continue

        if candidate.get("sha256") and f"sha:{candidate['sha256']}" in published_keys:
            history_rejections += 1
            continue

        fresh_for_history.append(candidate)

    print()
    print("Starting media validation...")
    print()

    validated = []
    attempts = 0

    # Prefer newer candidates and higher content relevance before downloading.
    validation_order = sorted(
        fresh_for_history,
        key=lambda x: (
            x.get("freshness_tier") == "primary",
            x.get("content_score", 0),
            -x.get("age_days", 9999),
        ),
        reverse=True,
    )

    for candidate in validation_order:
        if attempts >= MAX_DOWNLOAD_ATTEMPTS:
            break

        attempts += 1
        print(f"[{attempts}/{min(MAX_DOWNLOAD_ATTEMPTS, len(validation_order))}]")
        print()
        print(f"Downloading media: {candidate['media_url']}")
        print(f"Source post: {candidate.get('url', '')}")

        result, reason = download_and_validate(candidate)

        if result is None:
            print(f"  {reason}.")
            continue

        result["quality_score"] = quality_score(result)
        result["selection_score"] = selection_score(result)

        validated.append(result)

    validated = deduplicate_candidates(validated)

    for candidate in validated:
        candidate["quality_score"] = quality_score(candidate)
        candidate["selection_score"] = selection_score(candidate)

    write_json(VALIDATED_FILE, validated)

    selected = select_diverse(validated)

    for candidate in selected:
        candidate["telegram_caption"] = (
            f"{candidate.get('caption', '').strip()}\n\n@utcutie"
            if candidate.get("caption", "").strip()
            else "@utcutie"
        )

        if len(candidate["telegram_caption"]) > 1024:
            candidate["telegram_caption"] = (
                candidate["telegram_caption"][:1018].rstrip()
                + "\n\n@utcutie"
            )

    write_json(SELECTED_FILE, selected)

    print()
    print(f"VALIDATED VIDEOS: {len(validated)}")
    print(f"UNIQUE VALIDATED VIDEOS: {len(validated)}")
    print(f"FRESH VIDEOS AFTER HISTORY FILTER: {len(fresh_for_history)}")

    tiers = {"primary": 0, "secondary": 0, "emergency": 0}
    for item in selected:
        tier = item.get("freshness_tier")
        if tier in tiers:
            tiers[tier] += 1

    print(f"PRIMARY (0-14 days): {tiers['primary']}")
    print(f"SECONDARY (15-30 days): {tiers['secondary']}")
    print(f"EMERGENCY (31-60 days): {tiers['emergency']}")

    print()
    print("=" * 70)
    print(f"SELECTED UNIQUE VIDEOS: {len(selected)}")
    print("=" * 70)

    for index, candidate in enumerate(selected, start=1):
        print()
        print(
            f"{index}. "
            f"score={candidate.get('selection_score')} "
            f"content={candidate.get('content_score')} "
            f"age={candidate.get('age_days')}d "
            f"duration={candidate.get('duration')}s "
            f"size={candidate.get('file_size', 0) / 1024 / 1024:.3f}MB"
        )
        print(f"   Account: {candidate.get('account', '')}")
        print(f"   Instance: {candidate.get('instance', '')}")
        print(f"   URL: {candidate.get('url', '')}")
        print(f"   SHA256: {candidate.get('sha256', '')}")
        print(f"   Caption: {candidate.get('caption', '')}")

    print()
    print("Publication history was NOT modified.")
    print()
    print("=" * 70)
    print("DISCOVERY COMPLETE")
    print("=" * 70)
    print(f"Raw candidates: {len(raw_candidates)}")
    print(f"Canonical candidates: {len(unique)}")
    print(f"Content-gate passed: {len(passed)}")
    print(f"Validated videos: {len(validated)}")
    print(f"Fresh videos: {len(fresh_for_history)}")
    print(f"Selected unique videos: {len(selected)}")
    print(f"Published-history entries: {len(history)}")


if __name__ == "__main__":
    main()
