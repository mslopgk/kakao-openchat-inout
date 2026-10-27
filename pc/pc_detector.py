"""PC 카톡(Windows) 기반 오픈채팅 들낙 감지 — 안드로이드 불필요.

PC KakaoTalk 26.x 는 방별 chatLogs_<chatId>.edb 를 SQLCipher4(DB별 raw 32B 키)로
저장한다. 키는 실행 중인 KakaoTalk.exe 메모리에 상주 → 읽기전용으로 추출.
복호화하면 평문 SQLite 이고, 오픈채팅 입퇴장은 chatLogs.type=0 피드의 message(JSON):
  {"feedType":4,"members":[{"userId":..,"nickName":".."}]}   # 입장
  {"feedType":2,"member":{"userId":..,"nickName":".."}}       # 퇴장
authorId/member.userId 가 방 내에서 안정적이라 프로필 바꿔치기도 묶인다.

원본 .edb 는 절대 수정하지 않는다(임시 복사본만 복호화). 개인 대화 내용은 다루지 않고
오픈채팅 피드만 처리한다.
"""
import bisect
import ctypes
import ctypes.wintypes as wt
import glob
import json
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
# 상태/이벤트 저장 위치: KAKAO_DATA_DIR 환경변수 있으면 그곳(패키징된 앱용), 없으면 pc/
DATA_DIR = Path(os.environ.get("KAKAO_DATA_DIR", HERE))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE = DATA_DIR / "pc_state.json"
EVENTS = DATA_DIR / "events.jsonl"        # PC 백엔드 전용
USERS_ROOT = os.path.expandvars(r"%LOCALAPPDATA%\Kakao\KakaoTalk\users")

POLL_SEC = 5
QUICK_LEAVE_SEC = 10 * 60
REJOIN_WINDOW_SEC = 24 * 3600
REJOIN_COUNT = 2
FEED_TYPES = {1: "초대", 2: "퇴장", 4: "입장", 6: "강퇴"}
OPEN_TYPES = {"OM", "OD"}                 # 오픈채팅 그룹/다이렉트

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ===================== Win32 read-only memory =====================
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_LIMITED = 0x1000
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
READABLE = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_psapi = ctypes.WinDLL("psapi", use_last_error=True)


class _MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD), ("__a1", wt.DWORD),
                ("RegionSize", ctypes.c_size_t), ("State", wt.DWORD),
                ("Protect", wt.DWORD), ("Type", wt.DWORD), ("__a2", wt.DWORD)]


def find_pids(name="KakaoTalk.exe"):
    arr = (wt.DWORD * 8192)()
    need = wt.DWORD()
    _psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(need))
    out = []
    for i in range(need.value // ctypes.sizeof(wt.DWORD)):
        pid = arr[i]
        if not pid:
            continue
        h = _k32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
        if not h:
            continue
        buf = ctypes.create_unicode_buffer(260)
        sz = wt.DWORD(260)
        if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(sz)) and \
                buf.value.lower().endswith(name.lower()):
            out.append(pid)
        _k32.CloseHandle(h)
    return out


def _open(pid):
    h = _k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        raise OSError(f"OpenProcess({pid}) err {ctypes.get_last_error()}")
    return h


def _iter_regions(h):
    mbi = _MBI()
    addr = 0
    while addr < 0x7FFFFFFFFFFF:
        if not _k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            break
        size = mbi.RegionSize
        if mbi.State == MEM_COMMIT and mbi.Protect in READABLE and not (mbi.Protect & PAGE_GUARD):
            yield addr, size
        addr += size or 0x1000


def _read_region(h, base, size, chunk=8 << 20):
    out = bytearray()
    buf = ctypes.create_string_buffer(chunk)
    got = ctypes.c_size_t(0)
    off = 0
    while off < size:
        n = min(chunk, size - off)
        if _k32.ReadProcessMemory(h, ctypes.c_void_p(base + off), buf, n, ctypes.byref(got)) and got.value:
            out += buf.raw[:got.value]
        else:
            out += b"\x00" * n
        off += n
    return bytes(out)


def read_regions(pid, max_mb=1024):
    h = _open(pid)
    regs = []
    try:
        for base, size in _iter_regions(h):
            if 0 < size <= (max_mb << 20):
                regs.append((base, _read_region(h, base, size)))
    finally:
        _k32.CloseHandle(h)
    return regs


_RIDX = None


def _index(regs):
    global _RIDX
    rs = sorted(regs, key=lambda x: x[0])
    _RIDX = ([r[0] for r in rs], rs)


def _read_from(addr, n):
    bases, rs = _RIDX
    i = bisect.bisect_right(bases, addr) - 1
    if i < 0:
        return None
    base, data = rs[i]
    if base <= addr and addr + n <= base + len(data):
        return data[addr - base:addr - base + n]
    return None


def _region_of(addr):
    bases, rs = _RIDX
    i = bisect.bisect_right(bases, addr) - 1
    if i < 0:
        return None
    base, data = rs[i]
    return (base, data) if base <= addr < base + len(data) else None


# ===================== SQLCipher v4 =====================
PAGE = 4096
RESERVE = 80
MAGIC = b"SQLite format 3\x00"


def _aes_dec(key, iv, data):
    d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return d.update(data) + d.finalize()


def _valid_tail(t):
    if len(t) < 84:
        return False
    if int.from_bytes(t[0:2], "big") not in {512, 1024, 2048, 4096, 8192, 16384, 32768, 65536}:
        return False
    if t[2] not in (1, 2) or t[3] not in (1, 2):
        return False
    if t[4] < 32 or t[5] < 32 or t[6] < 32:
        return False
    return int.from_bytes(t[28:32], "big") in (0, 1, 2, 3, 4)


def try_key(first_page, key):
    if len(key) != 32 or len(first_page) < PAGE:
        return False
    usable = PAGE - RESERVE
    enc = first_page[16:usable]
    iv = first_page[usable:usable + 16]
    if len(enc) % 16:
        return False
    try:
        return _valid_tail(_aes_dec(key, iv, enc[:96])[:84])
    except Exception:
        return False


def decrypt_edb(src, dst, key):
    data = open(src, "rb").read()
    out = bytearray()
    usable = PAGE - RESERVE
    pg = 0
    for off in range(0, len(data), PAGE):
        page = data[off:off + PAGE]
        if len(page) == PAGE:
            iv = page[usable:usable + 16]
            if pg == 0:
                plain = MAGIC + _aes_dec(key, iv, page[16:usable])
            else:
                plain = _aes_dec(key, iv, page[:usable])
            out += plain + b"\x00" * RESERVE
        else:
            out += page
        pg += 1
    open(dst, "wb").write(bytes(out))
    return bytes(out[:16]) == MAGIC


# ===================== key recovery (64-bit, oracle-driven) =====================
def _codec_addrs(regs):
    pat = struct.pack("<IIIIIIII", 256000, 2, 16, 32, 16, 16, 4096, 0x63)
    out = []
    seen = set()
    for base, data in regs:
        pos = 0
        while True:
            pos = data.find(pat, pos)
            if pos < 0:
                break
            ctx = base + pos - 4
            raw = _read_from(ctx, 92)
            if raw:
                v = struct.unpack("<" + "I" * 23, raw)
                if v[7] == 4096 and v[9] == 80 and v[10] == 64 and v[14] & 1 and ctx not in seen:
                    seen.add(ctx)
                    out.append(ctx)
            pos += 4
    return out


def recover_keys(regs, oracle_pages):
    """{key -> oracle_page_index} — codec 주변 64비트 포인터 역참조 후 실제 edb로 검증."""
    _index(regs)
    codecs = _codec_addrs(regs)
    found = {}
    tested = set()

    def test(k):
        if not k or len(k) != 32 or k in tested or k == b"\x00" * 32:
            return
        tested.add(k)
        for i, fp in enumerate(oracle_pages):
            if try_key(fp, k):
                found[k] = i
                return

    def ptrs(blob):
        for i in range(0, len(blob) - 8, 8):
            yield int.from_bytes(blob[i:i + 8], "little")

    for ctx in codecs:
        r = _region_of(ctx)
        if not r:
            continue
        base, data = r
        o = ctx - base
        win = data[max(0, o - 256):o + 2304]
        for p in ptrs(win):
            if not (0x10000 <= p < 0x7FFFFFFFFFFF):
                continue
            k = _read_from(p, 32)
            if k:
                test(k)
            s = _read_from(p, 160)
            if s:
                for p2 in ptrs(s):
                    if 0x10000 <= p2 < 0x7FFFFFFFFFFF:
                        k2 = _read_from(p2, 32)
                        if k2:
                            test(k2)
    return found, codecs


# ===================== KakaoTalk data =====================
def active_user_dir():
    best, bt = None, -1
    for d in glob.glob(os.path.join(USERS_ROOT, "*", "chat_data")):
        logs = glob.glob(os.path.join(d, "chatLogs_*.edb"))
        m = max([os.path.getmtime(p) for p in logs] or [0])
        if m > bt:
            bt, best = m, os.path.dirname(d)
    return best


def _copy_set(edb, dstdir):
    """edb + wal + shm 를 임시폴더로 복사(원본 보호), 복사된 .edb 경로 반환."""
    base = os.path.basename(edb)
    for suf in ("", "-wal", "-shm"):
        s = edb + suf
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(dstdir, base + suf))
    return os.path.join(dstdir, base)


class PCKakao:
    def __init__(self):
        self.user_dir = active_user_dir()
        if not self.user_dir:
            raise RuntimeError("PC 카톡 user dir 없음")
        self.keys = {}        # edb_path(소문자 basename) -> key
        self.tmp = tempfile.mkdtemp(prefix="pckak_det_")

    # --- 키 추출 ---
    def refresh_keys(self):
        pids = find_pids()
        if not pids:
            raise RuntimeError("KakaoTalk.exe 미실행")
        edbs = glob.glob(os.path.join(self.user_dir, "**", "*.edb"), recursive=True)
        pages = []
        for e in edbs:
            try:
                pages.append((e, open(e, "rb").read(PAGE)))
            except OSError:
                pass
        regs = []
        for pid in pids:
            regs += read_regions(pid)
        found, codecs = recover_keys(regs, [p for _e, p in pages])
        self.keys = {}
        for k, idx in found.items():
            self.keys[os.path.basename(pages[idx][0]).lower()] = k
        return len(self.keys), len(codecs)

    def _decrypt(self, edb):
        key = self.keys.get(os.path.basename(edb).lower())
        if not key:
            # 첫 페이지로 키 매칭 시도(이름 다를 때)
            try:
                fp = open(edb, "rb").read(PAGE)
            except OSError:
                return None
            key = next((k for k in self.keys.values() if try_key(fp, k)), None)
            if not key:
                return None
        work = tempfile.mkdtemp(dir=self.tmp)
        src = _copy_set(edb, work)
        dst = src + ".sqlite"
        if decrypt_edb(src, dst, key):
            return dst
        return None

    # --- 오픈채팅 방 목록 ---
    def open_rooms(self):
        """{chatId(int): name} — type OM/OD 만."""
        rooms = {}
        cli = os.path.join(self.user_dir, "chat_data", "chatListInfo.edb")
        if not os.path.exists(cli):
            return rooms
        dec = self._decrypt(cli)
        if not dec:
            return rooms
        link_name = {}
        oll = os.path.join(self.user_dir, "chat_data", "openLinkListInfo.edb")
        if os.path.exists(oll):
            d2 = self._decrypt(oll)
            if d2:
                try:
                    c2 = sqlite3.connect(d2)
                    for lid, nm in c2.execute("select linkId,linkName from openLinkList"):
                        link_name[lid] = nm
                    c2.close()
                except Exception:
                    pass
        try:
            con = sqlite3.connect(dec)
            for r in con.execute("select chatId,type,chatRoomTitle,linkId from chatRoomList"):
                cid, typ, title, linkId = r
                if typ in OPEN_TYPES:
                    rooms[int(cid)] = title or link_name.get(linkId) or str(cid)
            con.close()
        except Exception:
            pass
        return rooms

    def room_feeds(self, chat_id, after_log_id=0):
        """해당 방 chatLogs 에서 after_log_id 이후 type=0 피드 반환."""
        edb = os.path.join(self.user_dir, "chat_data", f"chatLogs_{chat_id}.edb")
        if not os.path.exists(edb):
            return []
        dec = self._decrypt(edb)
        if not dec:
            return []
        rows = []
        try:
            con = sqlite3.connect(dec)
            con.row_factory = sqlite3.Row
            for r in con.execute(
                "select logId,authorId,type,sendAt,message from chatLogs "
                f"where type=0 and logId>{int(after_log_id)} order by logId"
            ):
                rows.append(dict(r))
            con.close()
        except Exception:
            pass
        return rows

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ===================== 들낙 판정 + 이벤트 =====================
def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"last": {}, "history": {}}


def save_state(st):
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


def emit(ev):
    with open(EVENTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    tag = "🚨 들낙" if ev.get("deullak") else "  "
    print(f"{tag} [{ev['time']}] {ev['room']} | {ev['action']} | "
          f"{ev['nick']} (userId={ev['userId']})"
          + (f" -> {ev['reason']}" if ev.get("reason") else ""), flush=True)


def judge(hist, action, ts):
    if action == "퇴장":
        joins = [t for a, t in hist if a == "입장"]
        if joins and ts - joins[-1] <= QUICK_LEAVE_SEC:
            return f"입장 {int(ts - joins[-1])}초 만에 퇴장"
    if action == "입장":
        recent = [t for a, t in hist if a == "입장" and ts - t <= REJOIN_WINDOW_SEC]
        if len(recent) + 1 >= REJOIN_COUNT:
            return f"24시간 내 {len(recent) + 1}번째 입장"
    return None


def _ts(send_at):
    v = int(send_at or 0)
    return v // 1000 if v > 1_000_000_000_000 else v


def process_room(chat_id, room, feeds, st):
    last = st["last"].get(str(chat_id), 0)
    for r in feeds:
        last = max(last, r["logId"])
        try:
            feed = json.loads(r["message"])
        except Exception:
            continue
        action = FEED_TYPES.get(feed.get("feedType"), f"feed{feed.get('feedType')}")
        ts = _ts(r["sendAt"])
        members = feed.get("members") or ([feed["member"]] if "member" in feed else [])
        for m in members:
            uid = m.get("userId")
            if uid is None:
                continue
            key = f"{chat_id}:{uid}"
            hist = st["history"].setdefault(key, [])
            reason = judge(hist, action, ts) if action in ("입장", "퇴장") else None
            hist.append((action, ts))
            del hist[:-20]
            emit({"time": datetime.fromtimestamp(ts).strftime("%F %T") if ts else "",
                  "room": room, "chatId": chat_id, "action": action,
                  "nick": m.get("nickName", ""), "userId": uid,
                  "deullak": bool(reason), "reason": reason, "raw": feed})
    st["last"][str(chat_id)] = last


def run_once(pc, st, status=None):
    nk, nc = pc.refresh_keys()
    rooms = pc.open_rooms()
    if status is not None:
        status["rooms"] = {str(k): v for k, v in rooms.items()}
        status["keys"] = nk
    for cid, name in rooms.items():
        feeds = pc.room_feeds(cid, st["last"].get(str(cid), 0))
        if feeds:
            process_room(cid, name, feeds, st)
    save_state(st)
    return rooms


def main():
    pc = PCKakao()
    st = load_state()
    print(f"PC카톡 감지 시작 user={os.path.basename(pc.user_dir)}", flush=True)
    try:
        while True:
            try:
                rooms = run_once(pc, st)
                print(f"[{datetime.now():%H:%M:%S}] 오픈챗 {len(rooms)}개 확인", flush=True)
            except Exception as e:
                print(f"[오류] {e!r}", flush=True)
            time.sleep(POLL_SEC)
    finally:
        pc.cleanup()


if __name__ == "__main__":
    if "--once" in sys.argv:
        pc = PCKakao()
        st = load_state()
        rooms = run_once(pc, st)
        print("오픈챗 방:", rooms)
        pc.cleanup()
    else:
        main()
