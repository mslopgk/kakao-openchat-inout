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
<title>들낙 감지 · OPS</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;700;800&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#07090d; --bg2:#0b0e14; --panel:#0e121a; --panel2:#111722;
  --line:#1a2130; --line2:#232c3e; --fg:#dde4ef; --mut:#5f6b82; --mut2:#8793a8;
  --grn:#3ff08a; --grn-dim:#143024; --cyan:#4fd4ff;
  --red:#ff4d5e; --red-dim:#2a0f16; --amber:#ffb13c; --amber-dim:#2a1e0c;
  --glow-red:0 0 0 1px rgba(255,77,94,.35),0 0 22px -6px rgba(255,77,94,.55);
  --mono:'JetBrains Mono',ui-monospace,Consolas,monospace;
  --sans:'IBM Plex Sans KR',-apple-system,'Malgun Gothic',sans-serif;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--sans);
  font-size:14px;line-height:1.55;letter-spacing:.1px;-webkit-font-smoothing:antialiased}
/* 배경: 미세 그리드 + 상단 글로우 + 그레인 */
body::before{content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;
  background:
   radial-gradient(900px 480px at 78% -10%, rgba(79,212,255,.08), transparent 60%),
   radial-gradient(1100px 600px at 10% -20%, rgba(63,240,138,.06), transparent 55%),
   linear-gradient(var(--bg2),var(--bg));
  background-attachment:fixed}
body::after{content:"";position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.035;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
.grid-lines{position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.5;
  background-image:linear-gradient(90deg,rgba(255,255,255,.015) 1px,transparent 1px);
  background-size:72px 100%}

/* ── 헤더 (상태 바) ── */
header{position:sticky;top:0;z-index:20;backdrop-filter:blur(12px);
  background:linear-gradient(180deg,rgba(7,9,13,.92),rgba(7,9,13,.72));
  border-bottom:1px solid var(--line);padding:0}
.bar{display:flex;gap:16px;align-items:center;flex-wrap:wrap;
  padding:13px 22px;max-width:1280px;margin:0 auto}
.brand{display:flex;align-items:baseline;gap:10px}
.brand .mk{font-family:var(--mono);font-weight:800;color:var(--red);font-size:13px;
  letter-spacing:2px;text-shadow:0 0 14px rgba(255,77,94,.5)}
.brand h1{font-family:var(--mono);font-size:15px;margin:0;font-weight:700;letter-spacing:.5px}
.brand h1 b{color:var(--grn)}
.brand .sub{font-family:var(--mono);font-size:10.5px;color:var(--mut);letter-spacing:3px;text-transform:uppercase}
.spacer{flex:1}
.live{display:inline-flex;align-items:center;gap:8px;font-family:var(--mono);
  font-size:11.5px;letter-spacing:.4px;padding:5px 11px;border:1px solid var(--line2);
  border-radius:999px;background:var(--panel);color:var(--mut2)}
.dot{width:8px;height:8px;border-radius:50%;background:#444;position:relative;flex:none}
.dot.on{background:var(--grn);box-shadow:0 0 0 0 rgba(63,240,138,.7);animation:pulse 1.8s infinite}
.dot.off{background:var(--red);box-shadow:0 0 10px rgba(255,77,94,.7)}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(63,240,138,.6)}70%{box-shadow:0 0 0 7px rgba(63,240,138,0)}100%{box-shadow:0 0 0 0 rgba(63,240,138,0)}}
.ctl{display:flex;align-items:center;gap:8px}
label.sel{font-family:var(--mono);font-size:10.5px;color:var(--mut);letter-spacing:1.5px;text-transform:uppercase;display:flex;align-items:center;gap:7px}
select,button{font-family:var(--mono);background:var(--panel);color:var(--fg);
  border:1px solid var(--line2);border-radius:8px;padding:6px 11px;font-size:12px;letter-spacing:.3px}
button{cursor:pointer;transition:.15s}
button:hover{border-color:var(--grn);color:var(--grn);box-shadow:0 0 16px -8px var(--grn)}
.scan{height:1px;background:linear-gradient(90deg,transparent,var(--grn),var(--cyan),transparent);
  opacity:.5;background-size:200% 100%;animation:scan 4s linear infinite}
@keyframes scan{0%{background-position:200% 0}100%{background-position:-200% 0}}

/* ── 레이아웃 ── */
.wrap{padding:22px;max-width:1280px;margin:0 auto;display:grid;gap:20px}
.reveal{opacity:0;transform:translateY(10px);animation:rise .6s cubic-bezier(.2,.7,.2,1) forwards}
.reveal:nth-child(1){animation-delay:.03s}.reveal:nth-child(2){animation-delay:.11s}.reveal:nth-child(3){animation-delay:.19s}
@keyframes rise{to{opacity:1;transform:none}}

/* 현황 타일 */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.tile{position:relative;background:linear-gradient(180deg,var(--panel2),var(--panel));
  border:1px solid var(--line);border-radius:14px;padding:16px 18px;overflow:hidden}
.tile::before{content:"";position:absolute;left:0;top:14px;bottom:14px;width:3px;border-radius:3px;background:var(--mut)}
.tile.alert::before{background:var(--red);box-shadow:0 0 14px var(--red)}
.tile.ok::before{background:var(--grn);box-shadow:0 0 14px var(--grn)}
.tile .num{font-family:var(--mono);font-weight:800;font-size:34px;line-height:1;
  font-variant-numeric:tabular-nums;letter-spacing:-1px}
.tile.alert .num{color:var(--red);text-shadow:0 0 22px rgba(255,77,94,.4)}
.tile.ok .num{color:var(--grn)}
.tile .lbl{margin-top:9px;font-family:var(--mono);font-size:10px;letter-spacing:2px;
  text-transform:uppercase;color:var(--mut)}

/* 카드 */
.card{background:linear-gradient(180deg,rgba(17,23,34,.6),rgba(14,18,26,.6));
  border:1px solid var(--line);border-radius:14px;overflow:hidden;
  box-shadow:0 24px 60px -40px rgba(0,0,0,.9)}
.card>h2{display:flex;align-items:center;gap:10px;font-family:var(--mono);font-size:11px;
  margin:0;padding:13px 18px;border-bottom:1px solid var(--line);color:var(--mut2);
  font-weight:600;letter-spacing:2.5px;text-transform:uppercase}
.card>h2 .tick{color:var(--grn);opacity:.8}
.card>h2 .opt{margin-left:auto;font-weight:400;letter-spacing:.3px;text-transform:none;
  color:var(--mut);display:flex;align-items:center;gap:6px;font-family:var(--sans);font-size:12px}
.tblwrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th{font-family:var(--mono);color:var(--mut);font-weight:500;font-size:10px;letter-spacing:1.5px;
  text-transform:uppercase;text-align:left;padding:10px 14px;border-bottom:1px solid var(--line);
  position:sticky;background:var(--panel);top:0}
td{padding:11px 14px;border-bottom:1px solid rgba(26,33,48,.6);white-space:nowrap;vertical-align:middle}
tbody tr{transition:background .12s}
tbody tr:hover{background:rgba(79,212,255,.04)}
td.nicks{white-space:normal;max-width:360px}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.uid{font-family:var(--mono);font-size:11px;color:var(--mut2);letter-spacing:.2px}
.t{font-family:var(--mono);font-size:11.5px;color:var(--mut2)}
.num-c{font-family:var(--mono);font-weight:600;font-variant-numeric:tabular-nums;text-align:center}

/* 들낙 강조 행 */
tr.dl{background:linear-gradient(90deg,rgba(255,77,94,.09),transparent 70%)}
tr.dl:hover{background:linear-gradient(90deg,rgba(255,77,94,.14),transparent 70%)}
tr.dl td:first-child{box-shadow:inset 3px 0 0 var(--red)}
tr.wl{opacity:.4}

/* 배지 */
.badge{display:inline-flex;align-items:center;gap:5px;font-family:var(--mono);font-weight:700;
  font-size:11px;letter-spacing:.3px;padding:3px 9px;border-radius:999px;border:1px solid transparent}
.b-join{color:var(--grn);background:var(--grn-dim);border-color:rgba(63,240,138,.25)}
.b-leave{color:var(--amber);background:var(--amber-dim);border-color:rgba(255,177,60,.25)}
.b-kick{color:var(--red);background:var(--red-dim);border-color:rgba(255,77,94,.3)}
.b-dl{color:#fff;background:var(--red);box-shadow:var(--glow-red);font-weight:800}
.dash{color:var(--mut);font-family:var(--mono)}
.chip{font-family:var(--sans);font-size:11.5px;background:var(--panel2);border:1px solid var(--line2);
  border-radius:7px;padding:2px 8px;margin:2px 3px 2px 0;display:inline-block;color:var(--fg)}
.reason{color:var(--red);font-size:12.5px}
.tgl{font-size:10.5px;padding:4px 10px;letter-spacing:.5px}
.tgl.is-wl{border-color:var(--amber);color:var(--amber)}
.tgl.is-wl:hover{box-shadow:0 0 16px -8px var(--amber)}
.empty{padding:28px 18px;text-align:center;color:var(--mut);font-family:var(--mono);font-size:12px;letter-spacing:1px}
.foot{font-family:var(--mono);font-size:10.5px;color:var(--mut);letter-spacing:.5px;
  text-align:center;padding:4px 0 10px}
@media(max-width:720px){.stats{grid-template-columns:repeat(2,1fr)}.brand .sub{display:none}}
@media(prefers-reduced-motion:reduce){*{animation:none!important}}
</style></head><body>
<div class="grid-lines"></div>
<header>
  <div class="bar">
    <div class="brand">
      <span class="mk">◣◢</span>
      <h1><b>들낙</b> DETECTOR</h1>
      <span class="sub">open-chat ops</span>
    </div>
    <span class="spacer"></span>
    <span id="live" class="live"><span class="dot"></span>연결 확인중</span>
    <div class="ctl">
      <label class="sel">ROOM
        <select id="room"><option value="">전체</option></select>
      </label>
      <button id="auto" class="tgl">AUTO · ON</button>
    </div>
  </div>
  <div class="scan"></div>
</header>

<div class="wrap">
  <div class="stats reveal" id="stat"></div>

  <div class="card reveal">
    <h2><span class="tick">▚</span>들낙 블랙리스트
      <span class="opt">userId 기준 · 프로필 바꿔도 묶임</span></h2>
    <div class="tblwrap"><table>
      <thead><tr><th>들낙</th><th>방</th><th>사용 닉네임</th><th>입장</th><th>퇴장</th>
      <th>강퇴</th><th>최근 활동</th><th>userId</th><th>관리</th></tr></thead>
      <tbody id="bl"></tbody>
    </table></div>
  </div>

  <div class="card reveal">
    <h2><span class="tick">▚</span>실시간 이벤트 로그
      <label class="opt"><input type="checkbox" id="onlydl"> 들낙만</label></h2>
    <div class="tblwrap"><table>
      <thead><tr><th>시각</th><th>방</th><th>동작</th><th>닉네임</th><th>userId</th><th>들낙 사유</th></tr></thead>
      <tbody id="log"></tbody>
    </table></div>
  </div>
  <div class="foot" id="foot"></div>
</div>

<script>
let auto=true, rooms={};
const $=s=>document.querySelector(s);
const esc=s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const actBadge=a=>({'입장':'b-join','퇴장':'b-leave','강퇴':'b-kick'}[a]||'');
async function j(u,o){const r=await fetch(u,o);return r.json();}

async function tickStatus(){
  const s=await j('/api/status');
  const ok=s.age_sec!=null && s.age_sec<15 && !s.error;
  $('#live').innerHTML=`<span class="dot ${ok?'on':'off'}"></span>`+
    (ok?`감지중 · ${s.age_sec}s`:(s.error?'오류 · '+esc(String(s.error).slice(0,40)):'대기'));
  $('#live').title=s.serial?`${s.serial} · ${s.read_mode}`:'';
  const sel=$('#room'), cur=sel.value;
  rooms=s.rooms||{};
  if(sel.dataset.n!=Object.keys(rooms).length){
    sel.innerHTML=['<option value="">전체</option>',
      ...Object.entries(rooms).map(([id,n])=>`<option value="${id}">${esc(n)}</option>`)].join('');
    sel.value=cur; sel.dataset.n=Object.keys(rooms).length;
  }
  $('#foot').textContent=`${s.serial||'-'}  ·  ${s.read_mode}  ·  poll ${s.age_sec!=null?s.age_sec+'s':'-'}  ·  ${new Date().toLocaleTimeString('ko-KR')}`;
}

async function tickData(){
  const room=$('#room').value, qs=room?`?room=${room}`:'';
  const [sum,log]=await Promise.all([
    j('/api/summary'+qs),
    j('/api/events'+(room?`?room=${room}`:'?')+($('#onlydl').checked?'&deullak=1':'')),
  ]);
  const totDL=sum.reduce((a,r)=>a+((r.deullak>0&&!r.whitelisted)?1:0),0);
  const totJ=sum.reduce((a,r)=>a+r.join,0), totL=sum.reduce((a,r)=>a+r.leave,0);
  const tile=(cls,n,l)=>`<div class="tile ${cls}"><div class="num">${n}</div><div class="lbl">${l}</div></div>`;
  $('#stat').innerHTML=
    tile(totDL>0?'alert':'',totDL,'들낙 유저')+
    tile('',sum.length,'관측 유저')+
    tile('ok',totJ,'총 입장')+
    tile('',totL,'총 퇴장');

  const bl=$('#bl');
  if(!sum.length){bl.innerHTML='<tr><td colspan="9" class="empty">관측된 유저 없음</td></tr>';}
  else{bl.innerHTML=sum.map(r=>{
    const cls=(r.deullak>0&&!r.whitelisted)?'dl':(r.whitelisted?'wl':'');
    const nicks=r.nicks.map(n=>`<span class="chip">${esc(n)}</span>`).join('')||'<span class="dash">—</span>';
    const dl=r.deullak>0?`<span class="badge b-dl">⚠ ${r.deullak}</span>`:'<span class="dash">·</span>';
    return `<tr class="${cls}"><td>${dl}</td><td>${esc(r.room)}</td><td class="nicks">${nicks}</td>`+
      `<td class="num-c" style="color:var(--grn)">${r.join}</td>`+
      `<td class="num-c" style="color:var(--amber)">${r.leave}</td>`+
      `<td class="num-c">${r.kick||'<span class=dash>·</span>'}</td>`+
      `<td class="t">${esc(r.last)}</td><td class="uid">${esc(r.userId)}</td>`+
      `<td><button class="tgl ${r.whitelisted?'is-wl':''}" data-uid="${r.userId}" data-wl="${r.whitelisted?1:0}">`+
      `${r.whitelisted?'WL 해제':'화이트리스트'}</button></td></tr>`;
  }).join('');}
  bl.querySelectorAll('button[data-uid]').forEach(b=>b.onclick=async()=>{
    await j('/api/note',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({userId:b.dataset.uid, whitelist:b.dataset.wl!='1'})});
    tickData();
  });

  const tb=$('#log');
  if(!log.length){tb.innerHTML='<tr><td colspan="6" class="empty">이벤트 없음</td></tr>';}
  else{tb.innerHTML=log.map(e=>
    `<tr class="${e.deullak?'dl':''}"><td class="t">${esc(e.time)}</td><td>${esc(e.room)}</td>`+
    `<td><span class="badge ${actBadge(e.action)}">${esc(e.action)}</span></td>`+
    `<td>${esc(e.nick)||'<span class=dash>—</span>'}</td><td class="uid">${esc(e.userId)}</td>`+
    `<td class="reason">${e.reason?'⚠ '+esc(e.reason):'<span class=dash>—</span>'}</td></tr>`
  ).join('');}
}

async function loop(){try{await tickStatus();await tickData();}catch(e){}}
$('#auto').onclick=()=>{auto=!auto;$('#auto').textContent='AUTO · '+(auto?'ON':'OFF');$('#auto').style.color=auto?'':'var(--mut)';};
$('#room').onchange=tickData;$('#onlydl').onchange=tickData;
loop();setInterval(()=>{if(auto)loop();},4000);
</script></body></html>"""


if __name__ == "__main__":
    threading.Thread(target=detector_loop, daemon=True).start()
    print(f"관리자 대시보드: http://localhost:{PORT}  (serial={SERIAL}, mode={os.environ['READ_MODE']})", flush=True)
    app.run(host="127.0.0.1", port=PORT, threaded=True)
