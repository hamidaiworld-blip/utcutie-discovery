import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

QUEUE_FILE = Path("daily_queue.json")
HISTORY_FILE = Path("history.json")
TEHRAN = ZoneInfo("Asia/Tehran")

RENDER_URL = os.environ.get("RENDER_API_URL", "https://x-video-downloader-api.onrender.com/send-media-and-send")
RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "
",
        encoding="utf-8",
    )
    tmp.replace(path)


def history_key(item):
    for field in ("canonical_url", "url", "source_url"):
        value = str(item.get(field) or "").strip()
        if value:
            return "url:" + value
    if item.get("sha256"):
        return "sha:" + str(item["sha256"])
    if item.get("media_url"):
        return "media:" + str(item["media_url"])
    return ""


def due_items(queue):
    now = datetime.now(TEHRAN)
    due = []
    for item in queue:
        if item.get("status") != "pending" or not item.get("scheduled_at"):
            continue

        scheduled = datetime.fromisoformat(item["scheduled_at"])
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=TEHRAN)

        if scheduled <= now:
            due.append(item)

    due.sort(key=lambda x: x.get("scheduled_at", ""))
    return due, now


def send_item(item):
    import requests

    media_url = str(item.get("media_url") or "").strip()
    caption = str(item.get("caption") or "@utcutie")

    if not media_url:
        return False, "missing media_url"

    if not RENDER_API_KEY:
        return False, "RENDER_API_KEY is not configured"

    response = requests.get(
        RENDER_URL,
        params={
            "url": media_url,
            "caption": caption,
            "x-api-key": RENDER_API_KEY,
        },
        timeout=240,
    )

    if not response.ok:
        return False, f"HTTP {response.status_code}: {response.text[:500]}"

    try:
        data = response.json()
    except Exception:
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

    due, now = due_items(queue)

    print(f"Tehran now: {now.isoformat()}")
    print(f"Due pending items: {len(due)}")
    print(f"Mode: {'DRY RUN' if DRY_RUN else 'LIVE'}")

    if not due:
        print("Nothing is due.")
        return

    keys = {history_key(x) for x in history if isinstance(x, dict)}
    changed = False

    for item in due:
        queue_id = item.get("queue_id")
        source_url = str(item.get("source_url") or "").strip()
        media_url = str(item.get("media_url") or "").strip()
        key = "url:" + source_url if source_url else "media:" + media_url

        if key in keys or (media_url and "media:" + media_url in keys):
            item["status"] = "published"
            item["published_at"] = now.isoformat()
            item["result"] = "already_in_history"
            changed = True
            print(f"{queue_id}: already in history; marked published")
            continue

        if DRY_RUN:
            print(
                f"{queue_id}: DRY RUN — "
                f"scheduled={item.get('scheduled_at')} source={source_url}"
            )
            continue

        ok, result = send_item(item)

        if not ok:
            item["last_error"] = result
            item["last_attempt_at"] = now.isoformat()
            changed = True
            print(f"{queue_id}: FAILED — {result}")
            continue

        item["status"] = "published"
        item["published_at"] = now.isoformat()
        item["telegram_message_id"] = result.get("telegram_message_id")
        item["render_response"] = {
            "duration": result.get("duration"),
            "file_size": result.get("file_size"),
        }

        history.append(
            {
                "published_at": now.isoformat(),
                "sha256": item.get("sha256")
                or hashlib.sha256(media_url.encode()).hexdigest(),
                "media_url": media_url,
                "status_url": source_url,
                "duration": result.get("duration", item.get("duration")),
                "file_size": result.get("file_size", item.get("file_size")),
                "total_score": item.get("score"),
                "telegram_message_id": result.get("telegram_message_id"),
            }
        )

        keys.add(key)

        if media_url:
            keys.add("media:" + media_url)

        changed = True
        print(
            f"{queue_id}: PUBLISHED — "
            f"Telegram message {result.get('telegram_message_id')}"
        )

    if changed and not DRY_RUN:
        payload["updated_at"] = now.isoformat()
        payload["published_count"] = sum(
            1 for x in queue if x.get("status") == "published"
        )
        save_json(QUEUE_FILE, payload)
        save_json(HISTORY_FILE, history)
        print("Queue and history saved.")
    else:
        print("No persistent changes made.")


if __name__ == "__main__":
    main()
