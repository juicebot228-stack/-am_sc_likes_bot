import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

LIKES_URL = os.environ.get("SC_LIKES_URL", "https://soundcloud.com/andrej-monaxov-859528296/likes")
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ.get("CHANNEL", "@am_sc_likes")
POST_OLD = os.environ.get("POST_OLD", "false").lower() == "true"
MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "1"))
STATE_FILE = "state.json"


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"initialized": False, "posted": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def fetch_likes():
    """Возвращает список лайков, новые первыми."""
    out = subprocess.run(
        ["yt-dlp", "--flat-playlist", "-J", "--no-warnings", LIKES_URL],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        print(out.stderr, file=sys.stderr)
        raise SystemExit("yt-dlp не смог прочитать лайки (профиль приватный или SoundCloud блокирует запрос)")
    data = json.loads(out.stdout)
    items = []
    for e in data.get("entries") or []:
        url = e.get("url") or e.get("webpage_url")
        if not url:
            continue
        items.append({
            "url": url,
            "title": e.get("title") or "",
            "artist": e.get("uploader") or "",
        })
    return items


def send(item):
    caption = " — ".join(x for x in (item["artist"], item["title"]) if x)
    text = f"🎵 {caption}\n{item['url']}" if caption else item["url"]
    body = urllib.parse.urlencode({"chat_id": CHANNEL, "text": text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data=body)
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def main():
    state = load_state()
    likes = fetch_likes()
    if not likes:
        raise SystemExit("Список лайков пуст: проверь, что лайки публичные")

    if not state["initialized"]:
        state["initialized"] = True
        if not POST_OLD:
            state["posted"] = [i["url"] for i in likes]
            save_state(state)
            print(f"Первый запуск: запомнил {len(likes)} текущих лайков, буду постить только новые")
            return

    posted = set(state["posted"])
    pending = [i for i in reversed(likes) if i["url"] not in posted]  # от старых к новым
    print(f"В очереди: {len(pending)}")

    for item in pending[:MAX_PER_RUN]:
        send(item)
        state["posted"].append(item["url"])
        save_state(state)
        print("Отправлено:", item["url"])
        time.sleep(3)

    save_state(state)


if __name__ == "__main__":
    main()
