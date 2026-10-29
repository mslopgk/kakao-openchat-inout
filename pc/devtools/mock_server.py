"""대시보드 UI 검증용 목업 서버 — 가짜 데이터만 사용(실제 카톡 미접근).
usage: python mock_server.py <dashboard.html> <port>
상태 전환: GET /mock/phase?p=live|kakao_off|scanning|no_keys|error|no_rooms|starting|stale
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PAGE = open(sys.argv[1], encoding="utf-8").read()
PORT = int(sys.argv[2])
STATE = {"phase": "live"}
ROOMS = {"1001": "주식 정보 공유방", "1002": "개발자 네트워킹 라운지", "1003": "동네 러닝 크루 🏃",
         "1004": "중고거래 · 나눔 (서울 강서)"}
NOW = time.time()


def t(ago):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW - ago))


EVENTS = [
    {"time": t(60), "room": ROOMS["1001"], "chatId": "1001", "action": "퇴장", "nick": "투자의신🤩", "userId": "9001", "deullak": True, "reason": "입장 42초 만에 퇴장"},
    {"time": t(102), "room": ROOMS["1001"], "chatId": "1001", "action": "입장", "nick": "투자의신🤩", "userId": "9001", "deullak": True, "reason": "24시간 내 3번째 입장"},
    {"time": t(400), "room": ROOMS["1002"], "chatId": "1002", "action": "입장", "nick": "백엔드김", "userId": "9002", "deullak": False, "reason": None},
    {"time": t(900), "room": ROOMS["1003"], "chatId": "1003", "action": "퇴장", "nick": "광고봇", "userId": "9003", "deullak": True, "reason": "입장 8초 만에 퇴장"},
    {"time": t(910), "room": ROOMS["1003"], "chatId": "1003", "action": "입장", "nick": "광고봇", "userId": "9003", "deullak": False, "reason": None},
    {"time": t(3000), "room": ROOMS["1004"], "chatId": "1004", "action": "강퇴", "nick": "스팸계정", "userId": "9004", "deullak": False, "reason": None},
    {"time": t(5000), "room": ROOMS["1002"], "chatId": "1002", "action": "입장", "nick": "프론트박", "userId": "9005", "deullak": False, "reason": None},
    {"time": t(7200), "room": ROOMS["1001"], "chatId": "1001", "action": "입장", "nick": "단타왕", "userId": "9001", "deullak": False, "reason": None},
]
SUMMARY = [
    {"chatId": "1001", "room": ROOMS["1001"], "userId": "9001", "nicks": ["단타왕", "투자의신🤩"], "join": 3, "leave": 2, "kick": 0, "deullak": 2, "first": t(7200), "last": t(60), "whitelisted": False, "note": ""},
    {"chatId": "1003", "room": ROOMS["1003"], "userId": "9003", "nicks": ["광고봇"], "join": 1, "leave": 1, "kick": 0, "deullak": 1, "first": t(910), "last": t(900), "whitelisted": False, "note": ""},
    {"chatId": "1002", "room": ROOMS["1002"], "userId": "9002", "nicks": ["백엔드김"], "join": 1, "leave": 0, "kick": 0, "deullak": 0, "first": t(400), "last": t(400), "whitelisted": False, "note": ""},
    {"chatId": "1004", "room": ROOMS["1004"], "userId": "9004", "nicks": ["스팸계정"], "join": 0, "leave": 0, "kick": 1, "deullak": 0, "first": t(3000), "last": t(3000), "whitelisted": False, "note": ""},
    {"chatId": "1002", "room": ROOMS["1002"], "userId": "9005", "nicks": ["프론트박"], "join": 1, "leave": 0, "kick": 0, "deullak": 1, "first": t(5000), "last": t(5000), "whitelisted": True, "note": ""},
]
WATCH = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            b = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b)
        elif u.path == "/mock/add":
            EVENTS.insert(0, {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "room": ROOMS["1002"], "chatId": "1002",
                              "action": "퇴장", "nick": "눈팅만함", "userId": "9006", "deullak": True,
                              "reason": "입장 15초 만에 퇴장"})
            self._json({"ok": True})
        elif u.path == "/mock/phase":
            STATE["phase"] = q["p"][0]
            self._json({"ok": True})
        elif u.path == "/api/status":
            ph = STATE["phase"]
            live = ph in ("live", "stale", "no_rooms")
            self._json({"serial": "e731544a2b", "read_mode": "PC KakaoTalk (SQLCipher)",
                        "device": "keys=16", "rooms": {} if ph == "no_rooms" else (ROOMS if live else {}),
                        "watch": WATCH, "hint": None,
                        "error": "OSError('ReadProcessMemory failed: 299')" if ph == "error" else None,
                        "last_poll": time.time() - (95 if ph == "stale" else 2) if live else None,
                        "age_sec": (95.0 if ph == "stale" else 2.1) if live else None,
                        "phase": "live" if ph == "stale" else ph, "keys": 16 if live else 0,
                        "poll_sec": 5, "version": "1.1.0", "uptime_sec": 120})
        elif u.path == "/api/summary":
            room = q.get("room", [None])[0]
            self._json([r for r in SUMMARY if not room or r["chatId"] == room])
        elif u.path == "/api/events":
            room = q.get("room", [None])[0]
            self._json([e for e in EVENTS if not room or e["chatId"] == room])
        else:
            self._json({}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        d = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/watch":
            WATCH[:] = d.get("watch", [])
            self._json({"ok": True, "watch": WATCH})
        elif self.path == "/api/note":
            for r in SUMMARY:
                if r["userId"] == str(d.get("userId")):
                    r["whitelisted"] = bool(d.get("whitelist"))
            self._json({"ok": True})


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
