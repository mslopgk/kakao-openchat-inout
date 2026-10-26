"""카톡 오픈채팅 들낙 감지 - 상시 감지 + 관리자 대시보드 (단일 프로세스).

- 백그라운드 스레드: Redroid(또는 에뮬)를 폴링해 피드 복호화·들낙 판정 (detector 재사용)
- Flask: 실시간 이벤트 로그 + userId별 들낙 블랙리스트 대시보드

실행:
    python admin.py                 # 기본: Redroid(WSL) pull 모드, http://localhost:8787
    PORT=9000 python admin.py
    ADB_SERIAL=emulator-5554 READ_MODE=shell python admin.py   # 방식 A(에뮬레이터)

주의: userId는 2^53를 넘는 큰 정수라 API에서 문자열로 직렬화한다(JS 정밀도 손실 방지).
"""
import json
import os
import subprocess
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).parent
DET = REPO / "detector"
sys.path.insert(0, str(DET))

ADB = os.environ.get("ADB", r"D:\Android\Sdk\platform-tools\adb.exe")
PORT = int(os.environ.get("PORT", "8787"))


def wsl_ip():
    try:
        out = subprocess.run(["wsl", "-d", "Ubuntu", "-u", "root", "--", "hostname", "-I"],
                             capture_output=True, text=True, timeout=20).stdout
        return out.split()[0] if out.split() else None
    except Exception:
        return None


# ADB_SERIAL 미지정 시 Redroid(WSL IP:5600) 자동 해석
SERIAL = os.environ.get("ADB_SERIAL")
if not SERIAL:
    ip = wsl_ip()
    SERIAL = f"{ip}:5600" if ip else None
os.environ["ADB"] = ADB
if SERIAL:
    os.environ["ADB_SERIAL"] = SERIAL
os.environ.setdefault("READ_MODE", "pull" if (SERIAL and ":" in SERIAL) else "shell")

import inout_detector as det  # noqa: E402  (환경변수 설정 후 import)

EVENTS = DET / "events.jsonl"
NOTES = REPO / "notes.json"   # userId별 메모/화이트리스트 (로컬 전용)

STATUS = {"last_poll": None, "error": None, "device": None,
          "serial": SERIAL, "read_mode": os.environ["READ_MODE"], "rooms": {}}


def adb(*a):
    return subprocess.run([ADB, *(["-s", SERIAL] if SERIAL else []), *a],
                          capture_output=True, text=True, timeout=60)


def ensure_device():
    """adb connect + root (Redroid adbd는 기본 shell이라 root 승격 필요)."""
    if not SERIAL:
        return "no-serial"
    adb("connect", SERIAL)
    if ":" in SERIAL:          # tcp(Redroid): root 승격
        adb("root")
        time.sleep(1)
        adb("connect", SERIAL)
    r = adb("shell", "id")
    dev = r.stdout.strip() or r.stderr.strip()
    STATUS["device"] = dev
    return dev


# ---------------- 상시 감지 스레드 ----------------
def detector_loop():
    while True:
        try:
            ensure_device()
            st = det.load_state()
            names = det.room_names()
            STATUS["rooms"] = {str(k): v for k, v in names.items()}
            print(f"[감지 시작] serial={SERIAL} mode={os.environ['READ_MODE']} "
                  f"last_id={st['last_id']} 방 {len(names)}개", flush=True)
            while True:
                rows = det.sql(det.DB, "select _id,type,chat_id,user_id,created_at,v,message "
                                       f"from chat_logs where _id>{st['last_id']} order by _id")
                if rows:
                    if any(r["chat_id"] not in names for r in rows):
                        names = det.room_names()
                        STATUS["rooms"] = {str(k): v for k, v in names.items()}
                    det.process(rows, st, names)
                    det.save_state(st)
                STATUS["last_poll"] = time.time()
                STATUS["error"] = None
                time.sleep(det.POLL_SEC)
        except Exception as e:
            STATUS["error"] = repr(e)
            print(f"[감지 오류] {e!r} -> 5초 후 재연결", flush=True)
            time.sleep(5)


# ---------------- 데이터 로드 ----------------
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
            e["userId"] = str(e.get("userId", ""))   # 큰 정수 → 문자열
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
    """(room,userId)별 집계 → 들낙 블랙리스트."""
    agg = {}
    for e in events:
        key = f"{e['chatId']}:{e['userId']}"
        a = agg.setdefault(key, {
            "chatId": e["chatId"], "room": e["room"], "userId": e["userId"],
            "nicks": [], "join": 0, "leave": 0, "kick": 0, "deullak": 0,
            "first": e["time"], "last": e["time"],
        })
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


@app.get("/api/status")
def api_status():
    lp = STATUS["last_poll"]
    return jsonify({
        "serial": STATUS["serial"], "read_mode": STATUS["read_mode"],
        "device": STATUS["device"], "rooms": STATUS["rooms"],
        "error": STATUS["error"],
        "last_poll": lp, "age_sec": (round(time.time() - lp, 1) if lp else None),
    })


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
    evs.reverse()   # 최신 먼저
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
    d = request.get_json(force=True)
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


PAGE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>들낙 감지 관리자</title>
<style>
:root{--bg:#0f1115;--card:#171a21;--line:#262b36;--fg:#e6e9ef;--mut:#8b93a7;
--red:#ff5d5d;--redbg:#2a1416;--grn:#37d67a;--ylw:#ffce54;--acc:#5b8def}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 -apple-system,Segoe UI,Roboto,'Malgun Gothic',sans-serif}
header{padding:14px 18px;border-bottom:1px solid var(--line);display:flex;
gap:14px;align-items:center;flex-wrap:wrap;position:sticky;top:0;background:var(--bg);z-index:5}
h1{font-size:16px;margin:0;font-weight:700}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:6px}
.mut{color:var(--mut)}select,button{background:var(--card);color:var(--fg);
border:1px solid var(--line);border-radius:8px;padding:6px 10px;font-size:13px}
button{cursor:pointer}button:hover{border-color:var(--acc)}
.wrap{padding:18px;max-width:1200px;margin:0 auto;display:grid;gap:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
.card h2{font-size:13px;margin:0;padding:12px 14px;border-bottom:1px solid var(--line);
color:var(--mut);font-weight:600;letter-spacing:.3px;text-transform:uppercase}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--mut);font-weight:600;font-size:12px}
td.nicks,td.note{white-space:normal}
tr.dl{background:var(--redbg)}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:700}
.b-join{background:#143022;color:var(--grn)}.b-leave{background:#3a2a12;color:var(--ylw)}
.b-kick{background:#2a1416;color:var(--red)}.b-dl{background:var(--red);color:#fff}
.uid{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--mut)}
.chip{font-size:11px;background:#1f2430;border:1px solid var(--line);border-radius:6px;
padding:1px 6px;margin:1px;display:inline-block}
.stat{display:flex;gap:20px;flex-wrap:wrap}.stat b{font-size:20px}
.wl{opacity:.45}.right{margin-left:auto}
.tgl{font-size:12px;padding:3px 8px}
small{color:var(--mut)}
</style></head><body>
<header>
  <h1>🚨 들낙 감지 관리자</h1>
  <span id="live" class="mut"><span class="dot" style="background:#666"></span>연결 확인중</span>
  <div class="right"></div>
  <label class="mut">방 <select id="room"><option value="">전체</option></select></label>
  <button id="auto" class="tgl">자동갱신: ON</button>
  <span id="updated" class="mut"></span>
</header>
<div class="wrap">
  <div class="card"><h2>현황</h2><div style="padding:14px" class="stat" id="stat"></div></div>
  <div class="card">
    <h2>들낙 블랙리스트 (userId 기준 · 프로필 바꿔도 묶임)</h2>
    <table><thead><tr><th>들낙</th><th>방</th><th>사용 닉네임</th><th>입장</th><th>퇴장</th>
    <th>강퇴</th><th>최근</th><th>userId</th><th>관리</th></tr></thead>
    <tbody id="bl"></tbody></table>
  </div>
  <div class="card">
    <h2>실시간 이벤트 로그 <label class="mut" style="font-weight:400;text-transform:none">
    <input type="checkbox" id="onlydl"> 들낙만</label></h2>
    <table><thead><tr><th>시각</th><th>방</th><th>동작</th><th>닉네임</th><th>userId</th>
    <th>들낙 사유</th></tr></thead><tbody id="log"></tbody></table>
  </div>
</div>
<script>
let auto=true, rooms={};
const $=s=>document.querySelector(s), el=(t,c,h)=>{const e=document.createElement(t);
if(c)e.className=c; if(h!=null)e.innerHTML=h; return e;};
const esc=s=>(s==null?'':String(s)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const actBadge=a=>({'입장':'b-join','퇴장':'b-leave','강퇴':'b-kick'}[a]||'');

async function j(u,o){const r=await fetch(u,o);return r.json();}

async function tickStatus(){
  const s=await j('/api/status');
  const live=$('#live'); const ok=s.age_sec!=null && s.age_sec<15 && !s.error;
  live.innerHTML=`<span class="dot" style="background:${ok?'var(--grn)':'var(--red)'}"></span>`+
    (ok?`감지중 (${s.age_sec}s 전 폴링)`:(s.error?'오류: '+esc(s.error):'대기'));
  // 방 드롭다운
  const sel=$('#room'); const cur=sel.value;
  const opts=['<option value="">전체</option>'];
  rooms=s.rooms||{};
  for(const[id,name]of Object.entries(rooms))opts.push(`<option value="${id}">${esc(name)}</option>`);
  if(sel.dataset.n!=Object.keys(rooms).length){sel.innerHTML=opts.join('');sel.value=cur;sel.dataset.n=Object.keys(rooms).length;}
  $('#updated').textContent=s.serial?`${s.serial} · ${s.read_mode}`:'';
}
async function tickData(){
  const room=$('#room').value, qs=room?`?room=${room}`:'';
  const [sum,log]=await Promise.all([
    j('/api/summary'+qs),
    j('/api/events'+(room?`?room=${room}`:'?')+($('#onlydl').checked?'&deullak=1':'')),
  ]);
  // 현황
  const totDL=sum.reduce((a,r)=>a+(r.deullak>0&&!r.whitelisted?1:0),0);
  const totJ=sum.reduce((a,r)=>a+r.join,0), totL=sum.reduce((a,r)=>a+r.leave,0);
  $('#stat').innerHTML=
    `<div><b style="color:var(--red)">${totDL}</b><br><small>들낙 유저</small></div>`+
    `<div><b>${sum.length}</b><br><small>관측 유저</small></div>`+
    `<div><b>${totJ}</b><br><small>총 입장</small></div>`+
    `<div><b>${totL}</b><br><small>총 퇴장</small></div>`;
  // 블랙리스트
  const bl=$('#bl'); bl.innerHTML='';
  for(const r of sum){
    const tr=el('tr', (r.deullak>0&&!r.whitelisted)?'dl':(r.whitelisted?'wl':''));
    const nicks=r.nicks.map(n=>`<span class="chip">${esc(n)}</span>`).join(' ');
    tr.innerHTML=
      `<td>${r.deullak>0?`<span class="badge b-dl">${r.deullak}</span>`:'-'}</td>`+
      `<td>${esc(r.room)}</td><td class="nicks">${nicks}</td>`+
      `<td>${r.join}</td><td>${r.leave}</td><td>${r.kick}</td>`+
      `<td><small>${esc(r.last)}</small></td>`+
      `<td class="uid">${esc(r.userId)}</td>`+
      `<td><button class="tgl" data-uid="${r.userId}" data-wl="${r.whitelisted?1:0}">`+
      `${r.whitelisted?'화이트 해제':'화이트리스트'}</button></td>`;
    bl.appendChild(tr);
  }
  bl.querySelectorAll('button[data-uid]').forEach(b=>b.onclick=async()=>{
    await j('/api/note',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({userId:b.dataset.uid, whitelist:b.dataset.wl!='1'})});
    tickData();
  });
  // 로그
  const tb=$('#log'); tb.innerHTML='';
  for(const e of log){
    const tr=el('tr', e.deullak?'dl':'');
    tr.innerHTML=`<td><small>${esc(e.time)}</small></td><td>${esc(e.room)}</td>`+
      `<td><span class="badge ${actBadge(e.action)}">${esc(e.action)}</span></td>`+
      `<td>${esc(e.nick)}</td><td class="uid">${esc(e.userId)}</td>`+
      `<td>${e.reason?'🚨 '+esc(e.reason):''}</td>`;
    tb.appendChild(tr);
  }
  $('#updated').title=new Date().toLocaleTimeString();
}
async function loop(){ try{await tickStatus(); await tickData();}catch(e){} }
$('#auto').onclick=()=>{auto=!auto; $('#auto').textContent='자동갱신: '+(auto?'ON':'OFF');};
$('#room').onchange=tickData; $('#onlydl').onchange=tickData;
loop(); setInterval(()=>{if(auto)loop();}, 4000);
</script></body></html>"""


if __name__ == "__main__":
    threading.Thread(target=detector_loop, daemon=True).start()
    print(f"관리자 대시보드: http://localhost:{PORT}  (serial={SERIAL}, mode={os.environ['READ_MODE']})", flush=True)
    app.run(host="127.0.0.1", port=PORT, threaded=True)
