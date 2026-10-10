import hashlib
import json
import os
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


QUEUE_FILE = Path("daily_queue.json")
HISTORY_FILE = Path("history.json")
TEHRAN = ZoneInfo("Asia/Tehran")

RENDER_URL = os.environ.get(
    "RENDER_API_URL",
    "https://x-video-downloader-api.onrender.com/upload-and-send",
)
RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

MAX_POSTS_PER_RUN = 1
MAX_LATE_MINUTES = 20
RETRY_COOLDOWN_MINUTES = 15
PUBLISH_START_MINUTE = 11 * 60
PUBLISH_END_MINUTE = 23 * 60


def load_json(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_datetime(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=TEHRAN)
    return result.astimezone(TEHRAN)


def item_history_keys(item):
    keys = set()
    for field in ("canonical_url", "url", "source_url", "status_url", "media_url"):
        value = str(item.get(field) or "").strip()
        if value:
            keys.add("url:" + value if field != "media_url" else "media:" + value)
    sha = str(item.get("sha256") or "").strip()
    if sha:
        keys.add("sha:" + sha)
    return keys


def send_item(item):
    if item.get("rights_verified") is not True:
        return False, "rights not verified; upload blocked"
    rights_basis = str(item.get("rights_basis") or "").strip().casefold()
    if rights_basis not in {"cc0", "public domain", "cc by 4.0", "cc by-sa 4.0", "written permission"}:
        return False, "unsupported or missing rights basis; upload blocked"
    if not str(item.get("attribution") or "").strip():
        return False, "missing required attribution; upload blocked"
    if rights_basis == "written permission":
        if not str(item.get("permission_reference") or "").strip():
            return False, "written permission reference missing; upload blocked"
    elif not str(item.get("license_url") or "").strip():
        return False, "license URL missing; upload blocked"

    media_url = str(item.get("media_url") or "").strip()
    source_url = str(item.get("source_url") or "").strip()
    caption = str(item.get("caption") or "").strip()
    if not media_url:
        return False, "missing media_url"
    if not caption:
        caption = "@utcutie"
    if not caption.endswith("@utcutie"):
        caption = caption.rstrip() + chr(10) + chr(10) + "@utcutie"
    if not RENDER_API_KEY:
        return False, "RENDER_API_KEY is not configured"
    if not media_url.startswith("https://"):
        return False, "media URL must use HTTPS"

    media_host = (urlsplit(media_url).hostname or "").casefold()
    source_host = (urlsplit(source_url).hostname or "").casefold()
    if source_host == "commons.wikimedia.org" and media_host != "upload.wikimedia.org":
        return False, "Commons media host is not the expected Wikimedia upload host"

    max_size = 48 * 1024 * 1024
    suffix = Path(urlsplit(media_url).path).suffix.casefold()
    if suffix not in {".mp4", ".webm"}:
        return False, f"unsupported source video extension: {suffix or 'missing'}"

    with tempfile.TemporaryDirectory(prefix="utcutie_publish_") as temp_dir:
        temp = Path(temp_dir)
        source_path = temp / ("source" + suffix)
        output_path = temp / "video.mp4"
        response = None
        try:
            for attempt in range(3):
                response = requests.get(
                    media_url,
                    stream=True,
                    allow_redirects=True,
                    headers={"User-Agent": "UTCutiePublisher/1.0 (+https://github.com/hamidaiworld-blip/utcutie-discovery)"},
                    timeout=(15, 120),
                )
                if response.status_code != 429 or attempt == 2:
                    break
                retry_after = response.headers.get("Retry-After", "")
                response.close()
                try:
                    delay = float(retry_after)
                except (TypeError, ValueError):
                    delay = 2 ** (attempt + 1)
                time.sleep(min(8.0, max(1.0, delay)))

            if response is None or response.status_code != 200:
                status = response.status_code if response is not None else "no response"
                if response is not None:
                    response.close()
                return False, f"source download failed: HTTP {status}"

            final_host = (urlsplit(response.url).hostname or "").casefold()
            if source_host == "commons.wikimedia.org" and final_host != "upload.wikimedia.org":
                response.close()
                return False, "Commons download redirected to an unexpected host"

            content_type = response.headers.get("Content-Type", "").casefold()
            if "video/" not in content_type and "application/octet-stream" not in content_type:
                response.close()
                return False, f"source did not return a supported video content type: {content_type[:80]}"

            content_length = response.headers.get("Content-Length", "")
            if content_length.isdigit() and int(content_length) > max_size:
                response.close()
                return False, "source video exceeds the 48 MB limit"

            total = 0
            with source_path.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_size:
                        response.close()
                        return False, "source video exceeds the 48 MB limit"
                    output.write(chunk)
            response.close()
            if total == 0:
                return False, "source video is empty"

            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source_path),
                "-map", "0:v:0", "-map", "0:a?",
                "-vf", "scale=w='min(1280,iw)':h=-2",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", str(output_path),
            ]
            try:
                converted = subprocess.run(command, capture_output=True, text=True, timeout=180)
            except subprocess.TimeoutExpired:
                return False, "MP4 conversion timed out after 180 seconds"
            if converted.returncode != 0 or not output_path.exists():
                detail = (converted.stderr or "ffmpeg conversion failed").strip()[-800:]
                return False, "MP4 conversion failed: " + detail

            output_size = output_path.stat().st_size
            if output_size <= 0 or output_size > max_size:
                return False, "converted MP4 is empty or exceeds the 48 MB limit"

            try:
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(output_path)],
                    capture_output=True, text=True, timeout=30,
                )
                duration = float(probe.stdout.strip()) if probe.returncode == 0 else 0.0
            except (subprocess.TimeoutExpired, ValueError):
                duration = 0.0
            if not 15 <= duration <= 180:
                return False, f"converted MP4 duration is invalid: {duration:.2f}s"

            try:
                with output_path.open("rb") as video_file:
                    response = requests.post(
                        RENDER_URL,
                        data={"caption": caption},
                        files={"video": ("video.mp4", video_file, "video/mp4")},
                        headers={"x-api-key": RENDER_API_KEY},
                        timeout=240,
                    )
            except requests.RequestException as exc:
                return False, f"Render upload request failed: {str(exc)[:300]}"

            if not response.ok:
                return False, f"Render upload HTTP {response.status_code}: {response.text[:500]}"
            try:
                data = response.json()
            except ValueError:
                return False, f"Render returned non-JSON response: {response.text[:300]}"
            if not data.get("success") or not data.get("telegram_sent"):
                return False, f"Render rejected upload: {data}"
            return True, data

        except requests.RequestException as exc:
            return False, f"source download error: {str(exc)[:300]}"
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

def main():
    payload = load_json(QUEUE_FILE, None)
    if not isinstance(payload, dict) or not isinstance(payload.get("queue"), list):
        raise RuntimeError("daily_queue.json is missing or invalid")

    queue = payload["queue"]
    history = load_json(HISTORY_FILE, [])
    if not isinstance(history, list):
        raise RuntimeError("history.json is invalid")

    now = datetime.now(TEHRAN)
    print(f"Tehran now: {now.isoformat()}")
    print(f"Mode: {'DRY RUN' if DRY_RUN else 'LIVE'}")
    print(f"Queue created_at: {payload.get('created_at')}")
    print(f"Target channel: {payload.get('target_channel')}")

    created_at = parse_datetime(payload.get("created_at"))
    if not created_at or created_at.date() != now.date():
        print("SAFETY STOP: queue is missing a valid created_at for today's Tehran date.")
        return

    if str(payload.get("target_channel") or "").strip().lower() != "@utcutie":
        print("SAFETY STOP: queue target is not @utcutie.")
        return

    minute_of_day = now.hour * 60 + now.minute
    if minute_of_day < PUBLISH_START_MINUTE or minute_of_day > PUBLISH_END_MINUTE + 10:
        print("Outside the allowed Tehran publishing window (11:00–23:10); nothing will be sent.")
        return

    history_keys = set()
    for entry in history:
        if isinstance(entry, dict):
            history_keys.update(item_history_keys(entry))

    due = []
    changed = False
    for item in queue:
        if not isinstance(item, dict) or item.get("status") != "pending":
            continue

        # Defense in depth: block any legacy or manually edited item whose
        # reuse rights are not explicitly documented in the queue.
        rights_basis = str(item.get("rights_basis") or "").strip().casefold()
        rights_valid = (
            item.get("rights_verified") is True
            and rights_basis in {"cc0", "public domain", "cc by 4.0", "cc by-sa 4.0", "written permission"}
            and bool(str(item.get("attribution") or "").strip())
            and (
                bool(str(item.get("permission_reference") or "").strip())
                if rights_basis == "written permission"
                else bool(str(item.get("license_url") or "").strip())
            )
        )
        if not rights_valid:
            item["status"] = "blocked_rights_unverified"
            item["result"] = "blocked: verified license or written permission and attribution are required"
            item["blocked_at"] = now.isoformat()
            changed = True
            print(f"{item.get('queue_id')}: blocked; reuse rights not verified.")
            continue

        scheduled = parse_datetime(item.get("scheduled_at"))
        if not scheduled or scheduled > now:
            continue

        if item_history_keys(item) & history_keys:
            item["status"] = "skipped"
            item["result"] = "already_in_history"
            item["skipped_at"] = now.isoformat()
            item.pop("published_at", None)
            item.pop("telegram_message_id", None)
            changed = True
            print(f"{item.get('queue_id')}: already in history; skipped without upload.")
            continue

        if now - scheduled > timedelta(minutes=MAX_LATE_MINUTES):
            item["status"] = "skipped"
            item["result"] = "schedule_expired_safety_guard"
            item["skipped_at"] = now.isoformat()
            changed = True
            print(f"{item.get('queue_id')}: skipped; scheduled time is more than {MAX_LATE_MINUTES} minutes old.")
            continue

        last_attempt = parse_datetime(item.get("last_attempt_at"))
        if last_attempt and now - last_attempt < timedelta(minutes=RETRY_COOLDOWN_MINUTES):
            print(f"{item.get('queue_id')}: retry cooldown active.")
            continue

        due.append((scheduled, item))

    due.sort(key=lambda pair: pair[0])
    print(f"Eligible due items: {len(due)}")

    if DRY_RUN:
        for scheduled, item in due[:MAX_POSTS_PER_RUN]:
            print(
                f"DRY RUN — queue_id={item.get('queue_id')} "
                f"scheduled={scheduled.isoformat()} source={item.get('source_url', '')}"
            )
        print("No Telegram uploads performed.")
        return

    if not due:
        if changed:
            payload["updated_at"] = now.isoformat()
            save_json(QUEUE_FILE, payload)
        print("Nothing eligible to publish.")
        return

    _, item = due[0]
    ok, result = send_item(item)
    item["last_attempt_at"] = now.isoformat()

    if not ok:
        item["last_error"] = str(result)
        changed = True
        print(f"{item.get('queue_id')}: FAILED — {result}")
    else:
        item["status"] = "published"
        item["published_at"] = now.isoformat()
        item["telegram_message_id"] = result.get("telegram_message_id")
        item["render_response"] = {
            "duration": result.get("duration"),
            "file_size": result.get("file_size"),
        }
        item.pop("last_error", None)
        media_url = str(item.get("media_url") or "")
        history.append(
            {
                "published_at": now.isoformat(),
                "sha256": item.get("sha256")
                or hashlib.sha256(media_url.encode("utf-8")).hexdigest(),
                "media_url": media_url,
                "status_url": item.get("source_url", ""),
                "duration": result.get("duration", item.get("duration")),
                "file_size": result.get("file_size", item.get("file_size")),
                "score": item.get("score"),
                "telegram_message_id": result.get("telegram_message_id"),
            }
        )
        changed = True
        print(
            f"{item.get('queue_id')}: PUBLISHED successfully; "
            f"Telegram message ID={result.get('telegram_message_id')}"
        )

    if changed:
        payload["updated_at"] = now.isoformat()
        payload["published_count"] = sum(
            1
            for entry in queue
            if entry.get("status") == "published" and entry.get("telegram_message_id")
        )
        save_json(QUEUE_FILE, payload)
        save_json(HISTORY_FILE, history)
        print("Queue and history saved.")


if __name__ == "__main__":
    main()
