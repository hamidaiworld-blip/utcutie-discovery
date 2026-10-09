import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


QUEUE_FILE = Path("daily_queue.json")
HISTORY_FILE = Path("history.json")
TEHRAN = ZoneInfo("Asia/Tehran")

RENDER_URL = os.environ.get(
    "RENDER_API_URL",
    "https://x-video-downloader-api.onrender.com/send-media-and-send",
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
    media_url = str(item.get("media_url") or "").strip()
    caption = str(item.get("caption") or "").strip()
    if not media_url:
        return False, "missing media_url"
    if not caption:
        caption = "@utcutie"
    if not caption.endswith("@utcutie"):
        caption = caption.rstrip() + "\n\n@utcutie"
    if not RENDER_API_KEY:
        return False, "RENDER_API_KEY is not configured"

    try:
        response = requests.get(
            RENDER_URL,
            params={
                "media_url": media_url,
                "caption": caption,
            },
            headers={"x-api-key": RENDER_API_KEY},
            timeout=240,
        )
    except requests.RequestException as exc:
        return False, f"request error: {exc}"

    if not response.ok:
        return False, f"HTTP {response.status_code}: {response.text[:500]}"

    try:
        data = response.json()
    except ValueError:
        return False, f"non-JSON response: {response.text[:500]}"

    if not data.get("success") or not data.get("telegram_sent"):
        return False, f"Render rejected upload: {data}"

    return True, data


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
        scheduled = parse_datetime(item.get("scheduled_at"))
        if not scheduled or scheduled > now:
            continue

        if item_history_keys(item) & history_keys:
            item["status"] = "published"
            item["published_at"] = now.isoformat()
            item["result"] = "already_in_history"
            changed = True
            print(f"{item.get('queue_id')}: already in history; marked published.")
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
            1 for entry in queue if entry.get("status") == "published"
        )
        save_json(QUEUE_FILE, payload)
        save_json(HISTORY_FILE, history)
        print("Queue and history saved.")


if __name__ == "__main__":
    main()
