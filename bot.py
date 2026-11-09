import html
import json
import os
import glob
import subprocess
import sys
import tempfile
import time

import requests

SOURCE_URL = os.environ.get("SC_URL", "https://soundcloud.com/andrej-monaxov-859528296/sets/flex")
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.environ.get("CHANNEL", "@am_sc_likes")
POST_OLD = os.environ.get("POST_OLD", "true").lower() == "true"
MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "10"))
USE_MP3 = os.environ.get("USE_MP3", "true").lower() == "true"
MAX_FILE_BYTES = 49 * 1024 * 1024
STATE_FILE = "state.json"


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    data.setdefault("sources", {})
    return data


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def run_ytdlp(args):
    out = subprocess.run(["yt-dlp", "--no-warnings", "-J", *args], capture_output=True, text=True)
    if out.returncode != 0:
        print(out.stderr, file=sys.stderr)
        return None
    return json.loads(out.stdout)


def fetch_tracks():
    data = run_ytdlp(["--flat-playlist", SOURCE_URL])
    if data is None:
        raise SystemExit("yt-dlp не смог прочитать источник (приватный плейлист или SoundCloud блокирует запрос)")
    items = []
    for e in data.get("entries") or []:
        url = e.get("url") or e.get("webpage_url")
        if url:
            items.append({"url": url, "title": e.get("title") or "", "artist": e.get("uploader") or ""})
    # лайки идут от новых к старым, плейлист в своём порядке
    if SOURCE_URL.rstrip("/").endswith("/likes"):
        items.reverse()
    return items


def fill_details(item):
    if item["title"] and item["artist"]:
        return
    data = run_ytdlp(["--no-playlist", item["url"]])
    if data:
        item["title"] = item["title"] or data.get("title") or ""
        item["artist"] = item["artist"] or data.get("uploader") or ""


def build_text(item):
    title = html.escape(item["title"] or "Без названия")
    lines = [f"🎧 <b>{title}</b>"]
    if item["artist"]:
        lines.append(html.escape(item["artist"]))
    lines.append("")
    lines.append(f'<a href="{html.escape(item["url"], quote=True)}">▶️ Слушать на SoundCloud</a>')
    return "\n".join(lines)


def tg_post(method, data, files=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    for _ in range(3):
        r = requests.post(url, data=data, files=files, timeout=600)
        if r.status_code == 429:
            wait = r.json().get("parameters", {}).get("retry_after", 15)
            time.sleep(wait + 1)
            if files:
                for f in files.values():
                    f.seek(0)
            continue
        if not r.ok:
            raise SystemExit(f"Telegram вернул {r.status_code}: {r.text}")
        return
    raise SystemExit("Telegram: слишком много попыток")


def send_link(item):
    data = {
        "chat_id": CHANNEL,
        "text": build_text(item),
        "parse_mode": "HTML",
        "link_preview_options": json.dumps({
            "url": item["url"],
            "prefer_large_media": True,
            "show_above_text": True,
        }),
    }
    tg_post("sendMessage", data)


def download_mp3(url, folder):
    out = subprocess.run(
        ["yt-dlp", "--no-warnings", "--no-playlist", "-x", "--audio-format", "mp3",
         "--audio-quality", "0", "--embed-metadata", "--embed-thumbnail",
         "--convert-thumbnails", "jpg", "-o", f"{folder}/%(id)s.%(ext)s", url],
        capture_output=True, text=True,
    )
    files = glob.glob(f"{folder}/*.mp3")
    if out.returncode != 0 or not files:
        print(out.stderr[-1500:], file=sys.stderr)
        return None
    return files[0]


def send_audio(item, path):
    data = {
        "chat_id": CHANNEL,
        "caption": build_text(item),
        "parse_mode": "HTML",
        "title": item["title"][:64],
        "performer": item["artist"][:64],
    }
    with open(path, "rb") as f:
        tg_post("sendAudio", data, files={"audio": f})


def send(item):
    if USE_MP3:
        with tempfile.TemporaryDirectory() as tmp:
            path = download_mp3(item["url"], tmp)
            if path and os.path.getsize(path) <= MAX_FILE_BYTES:
                send_audio(item, path)
                return
            print("mp3 не вышло (ошибка или файл больше 50 МБ), отправляю ссылкой")
    send_link(item)


def main():
    state = load_state()
    src = state["sources"].setdefault(SOURCE_URL, {"initialized": False, "posted": []})
    tracks = fetch_tracks()
    if not tracks:
        raise SystemExit("Список треков пуст: проверь ссылку и что плейлист публичный")

    if not src["initialized"]:
        src["initialized"] = True
        if not POST_OLD:
            src["posted"] = [t["url"] for t in tracks]
            save_state(state)
            print(f"Первый запуск: запомнил {len(tracks)} треков, буду постить только новые")
            return

    posted = set(src["posted"])
    pending = [t for t in tracks if t["url"] not in posted]
    print(f"В плейлисте: {len(tracks)}, в очереди: {len(pending)}")

    for item in pending[:MAX_PER_RUN]:
        fill_details(item)
        send(item)
        src["posted"].append(item["url"])
        save_state(state)
        print("Отправлено:", item["url"])
        time.sleep(4)

    save_state(state)


if __name__ == "__main__":
    main()
