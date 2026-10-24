"""카카오톡 오픈채팅 들낙 감지기.

에뮬레이터(adb root)의 KakaoTalk.db를 폴링해 입장/퇴장 피드를 복호화하고,
userId 기준으로 들낙(짧은 시간 내 입장->퇴장, 반복 입장)을 잡아낸다.
"""
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "ref"))
from kakaodecrypt import KakaoDecrypt  # noqa: E402

ADB = os.environ.get("ADB", r"D:\Android\Sdk\platform-tools\adb.exe")
# 여러 기기가 붙어 있을 때 대상 지정 (예: emulator-5554, localhost:5555)
ADB_SERIAL = os.environ.get("ADB_SERIAL")
DB = "/data/data/com.kakao.talk/databases/KakaoTalk.db"
DB2 = "/data/data/com.kakao.talk/databases/KakaoTalk2.db"
HERE = Path(__file__).parent
STATE = HERE / "state.json"
EVENTS = HERE / "events.jsonl"

POLL_SEC = 3
QUICK_LEAVE_SEC = 10 * 60      # 입장 후 이 시간 안에 나가면 들낙
REJOIN_WINDOW_SEC = 24 * 3600  # 이 시간 안에 입장 횟수
REJOIN_COUNT = 2               # 이 횟수 이상이면 들낙

FEED_TYPES = {1: "초대", 2: "퇴장", 4: "입장", 6: "강퇴"}

sys.stdout.reconfigure(encoding="utf-8")


def sql(db, query):
    out = subprocess.run(
        [ADB, *(["-s", ADB_SERIAL] if ADB_SERIAL else []), "shell",
         f"sqlite3 -json {db} \"{query}\""],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    ).stdout.strip()
    return json.loads(out) if out else []


def room_names():
    links = {r["id"]: r["name"] for r in sql(DB2, "select id,name from open_link")}
    return {r["id"]: links.get(r["link_id"], str(r["id"]))
            for r in sql(DB, "select id,link_id from chat_rooms")}


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"last_id": 0, "history": {}}


def save_state(st):
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def emit(ev):
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    tag = "🚨 들낙" if ev.get("deullak") else "  "
    print(f"{tag} [{ev['time']}] {ev['room']} | {ev['action']} | "
          f"{ev['nick']} (userId={ev['userId']})"
          + (f" -> {ev['reason']}" if ev.get("reason") else ""), flush=True)


def judge(hist, action, ts):
    """hist: 해당 (방,userId)의 [(action, ts), ...]. 들낙 사유 문자열 또는 None."""
    if action == "퇴장":
        joins = [t for a, t in hist if a == "입장"]
        if joins and ts - joins[-1] <= QUICK_LEAVE_SEC:
            return f"입장 {int(ts - joins[-1])}초 만에 퇴장"
    if action == "입장":
        recent = [t for a, t in hist if a == "입장" and ts - t <= REJOIN_WINDOW_SEC]
        if len(recent) + 1 >= REJOIN_COUNT:
            return f"24시간 내 {len(recent) + 1}번째 입장"
    return None


def process(rows, st, names):
    for r in rows:
        st["last_id"] = max(st["last_id"], r["_id"])
        if r["type"] != 0:
            continue
        try:
            enc = json.loads(r["v"]).get("enc", 0)
            feed = json.loads(KakaoDecrypt.decrypt(r["user_id"], enc, r["message"]))
        except Exception as e:  # 복호화/파싱 실패는 원문 기록
            emit({"time": str(r["created_at"]), "room": str(r["chat_id"]), "action": "파싱실패",
                  "nick": "", "userId": r["user_id"], "reason": repr(e)})
            continue
        action = FEED_TYPES.get(feed.get("feedType"), f"feed{feed.get('feedType')}")
        ts = r["created_at"]
        room = names.get(r["chat_id"], str(r["chat_id"]))
        # 입장은 members 배열, 퇴장/강퇴는 member 단일 객체로 온다
        members = feed.get("members") or ([feed["member"]] if "member" in feed else [])
        for m in members:
            key = f"{r['chat_id']}:{m['userId']}"
            hist = st["history"].setdefault(key, [])
            reason = judge(hist, action, ts) if action in ("입장", "퇴장") else None
            hist.append((action, ts))
            del hist[:-20]
            emit({"time": datetime.fromtimestamp(ts).strftime("%F %T"), "room": room,
                  "chatId": r["chat_id"], "action": action, "nick": m.get("nickName", ""),
                  "userId": m["userId"], "deullak": bool(reason), "reason": reason,
                  "raw": feed})


def main():
    st = load_state()
    names = room_names()
    print(f"감지 시작 (last_id={st['last_id']}, 방 {len(names)}개)", flush=True)
    while True:
        try:
            rows = sql(DB, "select _id,type,chat_id,user_id,created_at,v,message "
                           f"from chat_logs where _id>{st['last_id']} order by _id")
            if rows:
                if any(r["chat_id"] not in names for r in rows):
                    names = room_names()
                process(rows, st, names)
                save_state(st)
        except Exception as e:
            print(f"[오류] {e!r}", flush=True)
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
