"""카톡 오픈채팅 들낙 감지기 — Windows 앱.

PC 카톡을 읽어 오픈채팅 들낙을 감지하고(안드로이드/WSL 불필요), 네이티브 창으로
대시보드를 띄운다. 감지 스레드 + 로컬 웹서버(Flask) + pywebview 창을 한 프로세스로.
PyInstaller 로 단일 .exe 패키징.
"""
import json
import os
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# 자원/데이터 경로 (패키징 대응)
FROZEN = getattr(sys, "frozen", False)
RES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DATA_DIR = Path(os.environ.get("KAKAO_DATA_DIR",
                os.path.join(os.environ.get("LOCALAPPDATA", str(Path.home())),
                             "KakaoInoutDetector")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ["KAKAO_DATA_DIR"] = str(DATA_DIR)   # pc_detector 가 같은 폴더 쓰도록

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pc_detector as D  # noqa: E402

PORT = int(os.environ.get("PORT", "8799"))
EVENTS = DATA_DIR / "events.jsonl"
NOTES = DATA_DIR / "notes.json"
PAGE = (RES / "dashboard.html").read_text(encoding="utf-8")

STATUS = {"last_poll": None, "error": None, "keys": 0, "rooms": {}, "watch": [],
          "hint": "시작 중… (PC 카톡이 켜져 있어야 합니다)",
          "account": None, "backend": "PC KakaoTalk (SQLCipher)"}


# ---------------- 감지 스레드 ----------------
def detector_loop():
    while True:
        try:
            pc = D.PCKakao()
            STATUS["account"] = os.path.basename(pc.user_dir)[:10]
            st = D.load_state()
            while True:
                try:
                    rooms = D.run_once(pc, st, STATUS)
                    STATUS["rooms"] = {str(k): v for k, v in rooms.items()}
                    STATUS["last_poll"] = time.time()
                    STATUS["error"] = None
                except Exception as e:
                    STATUS["error"] = repr(e)
                time.sleep(D.POLL_SEC)
        except Exception as e:
            msg = str(e)
            if "미실행" in msg or "KakaoTalk.exe" in msg:
                STATUS["hint"] = "PC 카톡이 실행돼 있지 않습니다. 카톡을 켜고 로그인하세요."
            elif "user dir" in msg:
                STATUS["hint"] = "PC 카톡에 로그인된 계정이 없습니다. 카톡에 로그인하세요."
            else:
                STATUS["hint"] = f"대기 중: {msg[:60]}"
            STATUS["error"] = None
            STATUS["keys"] = 0
            STATUS["rooms"] = {}
            time.sleep(5)


# ---------------- 데이터 ----------------
def load_events():
    out = []
    if EVENTS.exists():
        for line in EVENTS.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            e.pop("raw", None)
            e["userId"] = str(e.get("userId", ""))
            e["chatId"] = str(e.get("chatId", ""))
            out.append(e)
    return out


def load_notes():
    if NOTES.exists():
        try:
            return json.loads(NOTES.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_notes(n):
    NOTES.write_text(json.dumps(n, ensure_ascii=False, indent=2), encoding="utf-8")


def summarize(events, notes):
    agg = {}
    for e in events:
        key = f"{e['chatId']}:{e['userId']}"
        a = agg.setdefault(key, {"chatId": e["chatId"], "room": e["room"], "userId": e["userId"],
                                 "nicks": [], "join": 0, "leave": 0, "kick": 0, "deullak": 0,
                                 "first": e["time"], "last": e["time"]})
        nick = e.get("nick") or ""
        if nick and nick not in a["nicks"]:
            a["nicks"].append(nick)
        if e["action"] == "입장":
            a["join"] += 1
        elif e["action"] == "퇴장":
            a["leave"] += 1
        elif e["action"] == "강퇴":
            a["kick"] += 1
        if e.get("deullak"):
            a["deullak"] += 1
        a["last"] = e["time"]
    rows = list(agg.values())
    for r in rows:
        r["whitelisted"] = notes.get(r["userId"], {}).get("whitelist", False)
        r["note"] = notes.get(r["userId"], {}).get("note", "")
    rows.sort(key=lambda r: (not r["deullak"], -r["deullak"], -r["join"]))
    return rows


# ---------------- 웹 ----------------
from flask import Flask, jsonify, request, Response  # noqa: E402

app = Flask(__name__)
app.logger.disabled = True
import logging  # noqa: E402
from urllib.parse import urlparse  # noqa: E402
logging.getLogger("werkzeug").setLevel(logging.ERROR)

_ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}


@app.before_request
def _csrf_guard():
    """상태변경 요청은 로컬 대시보드에서 온 JSON 만 허용.
    서버가 127.0.0.1 에만 떠 있어도, 사용자가 연 외부 웹페이지가 브라우저를 통해
    POST 로 감시목록·화이트리스트를 바꾸는 CSRF 를 막는다. 외부 사이트는 교차출처
    JSON POST 시 프리플라이트가 필요한데 이 서버는 허용하지 않으므로 차단된다."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    origin = request.headers.get("Origin")
    if origin and urlparse(origin).netloc not in _ALLOWED_HOSTS:
        return jsonify({"ok": False, "error": "forbidden origin"}), 403
    if not request.is_json:
        return jsonify({"ok": False, "error": "json required"}), 415


@app.get("/api/status")
def api_status():
    lp = STATUS["last_poll"]
    return jsonify({
        "serial": STATUS["account"] or "-", "read_mode": STATUS["backend"],
        "device": f"keys={STATUS['keys']}", "rooms": STATUS["rooms"],
        "watch": STATUS.get("watch", []), "hint": STATUS.get("hint"),
        "error": STATUS["error"], "last_poll": lp,
        "age_sec": (round(time.time() - lp, 1) if lp else None),
    })


@app.get("/api/watch")
def api_watch_get():
    return jsonify(sorted(D.load_watch()))


@app.post("/api/watch")
def api_watch_set():
    d = request.get_json(silent=True) or {}
    ids = d.get("watch", [])
    if not isinstance(ids, list):
        return jsonify({"ok": False}), 400
    D.save_watch(ids)
    STATUS["watch"] = sorted(str(x) for x in ids)
    return jsonify({"ok": True, "watch": STATUS["watch"]})


@app.get("/api/events")
def api_events():
    room = request.args.get("room")
    limit = int(request.args.get("limit", "300"))
    only = request.args.get("deullak") == "1"
    evs = load_events()
    if room:
        evs = [e for e in evs if e["chatId"] == room]
    if only:
        evs = [e for e in evs if e.get("deullak")]
    evs.reverse()
    return jsonify(evs[:limit])


@app.get("/api/summary")
def api_summary():
    room = request.args.get("room")
    evs = load_events()
    if room:
        evs = [e for e in evs if e["chatId"] == room]
    return jsonify(summarize(evs, load_notes()))


@app.post("/api/note")
def api_note():
    d = request.get_json(silent=True) or {}
    uid = str(d.get("userId", ""))
    if not uid:
        return jsonify({"ok": False}), 400
    notes = load_notes()
    cur = notes.setdefault(uid, {})
    if "whitelist" in d:
        cur["whitelist"] = bool(d["whitelist"])
    if "note" in d:
        cur["note"] = str(d["note"])
    save_notes(notes)
    return jsonify({"ok": True, "userId": uid, **cur})


@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


def serve():
    from werkzeug.serving import make_server
    srv = make_server("127.0.0.1", PORT, app, threaded=True)
    srv.serve_forever()


def main():
    threading.Thread(target=detector_loop, daemon=True).start()
    threading.Thread(target=serve, daemon=True).start()
    time.sleep(1.0)
    url = f"http://127.0.0.1:{PORT}"
    # 네이티브 창(pywebview) 우선, 실패 시 기본 브라우저
    try:
        import webview  # type: ignore
        webview.create_window("들낙 감지기", url, width=1180, height=860)
        webview.start()
    except Exception:
        import webbrowser
        webbrowser.open(url)
        print(f"들낙 감지기 실행 중: {url}  (창을 닫지 마세요; Ctrl+C 로 종료)")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
