# 방식 C — PC 카카오톡 (안드로이드 불필요) · Windows 앱

PC용 KakaoTalk(Windows)의 로컬 DB를 복호화해 오픈채팅 들낙을 감지한다.
**에뮬레이터·Redroid·WSL·adb 전부 불필요** — PC 카톡만 실행돼 있으면 된다.

> 상태: **전체 실동작 검증(2026-10-28).** 오픈챗 17방 자동 목록화, 들낙 판정, 프로필 바꿔치기(userId) 추적.
> 단일 `.exe` 로 패키징(PyInstaller).

## 왜 되는가

- PC 카톡(26.x)은 방별 `chatLogs_<chatId>.edb` 를 **SQLCipher4**(AES-256-CBC + HMAC-SHA512,
  DB별 raw 32바이트 키)로 저장. 파일 전체가 암호화라 `SQLite format 3` 헤더가 안 보인다.
- **키는 실행 중인 `KakaoTalk.exe` 메모리에 상주.** 읽기전용(`PROCESS_VM_READ`)으로 열어
  SQLCipher `codec_ctx` 시그니처(`kdf_iter=256000, key=32, page=4096, reserve=80, hmac=64 …`)를
  찾고, 그 주변 포인터를 역참조해 32바이트 키 후보를 모은 뒤 **실제 edb 첫 페이지로 검증**한다.
  (버전/오프셋에 안 흔들리는 오라클 방식. KakaoTalk.exe 는 64비트라 포인터는 8바이트.)
- 복호화하면 평문 SQLite. `chatLogs(logId, authorId, type, sendAt, message, …)` 에서
  **`type=0` 이 피드(시스템 메시지)**, `message` 는 **평문 JSON**(모바일과 달리 추가 암호화 없음):

```json
{"feedType":4,"members":[{"userId":...,"nickName":".."}]}   // 입장
{"feedType":2,"member":{"userId":...,"nickName":".."}}       // 퇴장
```

- **`authorId`/`member.userId` 는 방 안에서 안정적** → 오픈프로필/닉 바꿔치기해도 묶인다.
- 오픈채팅 방 목록·이름은 `chatListInfo.edb`(`chatRoomList.type` 이 `OM`/`OD`) +
  `openLinkListInfo.edb`(`openLinkList.linkName`) 에서 얻는다.

## 구성

```
pc_detector.py   감지 엔진: 메모리 키추출 + SQLCipher4 복호화 + 오픈챗 목록 + 들낙 판정
app.py           Windows 앱: 감지 스레드 + 로컬 웹서버(Flask) + 네이티브 창(pywebview)
dashboard.html   대시보드 UI (앱이 서빙)
app.spec         PyInstaller 빌드 스펙 (단일 exe, 창형)
```

- 원본 `.edb` 는 **절대 수정하지 않는다**(임시 복사본만 복호화, 종료 시 삭제).
- 개인 1:1/일반 대화는 다루지 않고 **오픈채팅 방만** 처리한다.

## 실행 (개발)

```bash
pip install flask cryptography pywebview
python pc_detector.py --once     # 1회 패스: 오픈챗 목록 + 들낙 출력
python app.py                    # 앱: http://127.0.0.1:8799 (네이티브 창 or 브라우저)
```

데이터(상태/이벤트/화이트리스트/감시목록)는 `%LOCALAPPDATA%\KakaoInoutDetector\` 에 저장
(`pc_state.json`, `events.jsonl`, `notes.json`, `watch.json`).

### 대시보드 기능
- **현황** 타일(들낙 유저/관측/입장/퇴장) · **들낙 블랙리스트**(userId별, 닉 바꿔치기 묶임, 화이트리스트 토글) · **실시간 로그**(방 필터, 들낙만 보기).
- **감시 방 설정**: 그 계정의 오픈챗을 체크박스로 나열 → 원하는 방만 감지(비우면 전체). `watch.json` 에 저장.
- **안내 배너**: PC 카톡 미실행/미로그인/오픈챗 없음일 때 상단에 안내(5초마다 자동 재시도).

## 빌드 (단일 exe)

```bash
pyinstaller app.spec --noconfirm
# 산출물: pc/dist/KakaoInoutDetector.exe
```

클라이언트는 **PC 카톡을 켠 상태**에서 `KakaoInoutDetector.exe` 를 더블클릭하면 끝.
(파이썬·안드로이드·WSL 불필요. 최초 실행 시 메모리 스캔 수십 초)

## 한계

- **상시 온라인 제약은 동일** — PC 카톡이 실행+로그인돼 있어야 피드를 받는다(플랫폼 무관).
  단, 껐다 켜도 재접속 시 백로그가 동기화되는 범위는 방 활동량에 따름.
- 키는 카톡 **재시작 시 재추출** 필요(앱이 매 폴링마다 자동 재시도).
- KakaoTalk.exe **버전 업데이트** 시 codec 구조체 오프셋이 바뀌면 키추출부 보정 필요
  (오라클 방식이라 어지간한 변화는 흡수).
- 보안: 이 앱은 로컬에서만 동작하며 어떤 데이터도 외부로 보내지 않는다.
