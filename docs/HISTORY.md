# 작업·대화 히스토리

이 프로젝트가 어떻게 진행됐는지의 기록. 결론만 보려면 [최종 상태](#최종-상태)로.

## 1. 질문 — 들낙 감지가 가능한가

> "카카오톡 오픈채팅 들낙감지 구현가능? 개발자 봇 집어넣어서 들어오는 사람의 고유ID 조회할수 있으면?"

- **공식 경로 없음.** 오픈채팅용 공식 봇 API가 없고, 알림만 읽는 봇은 입퇴장 피드를 못 본다.
- 가능한 길: 카톡 클라이언트를 하나 띄우고 그 **로컬 DB의 입퇴장 피드를 복호화**.
- 사용자가 "루팅폰 없이 최대한", "그냥 감지만 되면 됨" 으로 범위 확정.

## 2. 방식 A 구축 (Windows + AVD) — 실검증

- 루팅폰 대신 **AVD + `adb root`**. root 되는 **google_apis(비-Play)** 이미지 사용.
- 카톡 minSdk 32 → API 30 불가, **API 34** 사용. 카톡은 arm64 전용인데 x86_64 이미지의
  `libndk_translation` 으로 실행됨.
- 삽질: `Invoke-WebRequest` 가 너무 느림 → `curl.exe`. 라이선스 동의는 Git Bash `yes |`.
- **부계정을 보조기기로 QR 로그인** → 폰 본 로그인 유지.
- 블라인드 좌표 탭으로 방을 날릴 뻔함("Delete & Leave" 확인창까지) → `uiautomator dump` 로
  텍스트 찾아 누르는 `ui.sh` 작성, 한 번에 한 동작.

## 3. 피드 복호화와 판정

- `chat_logs.message` 는 base64 AES-CBC. 키는 **행의 `user_id` + `enc`(관측값 31)** 로 PKCS12-SHA1 KDF.
  [jiru/kakaodecrypt](https://github.com/jiru/kakaodecrypt) 사용.
- `feedType`: 1=초대, 2=퇴장, 4=입장, 6=강퇴.
- **버그**: 입장은 `members` 배열, 퇴장은 `member` 단수 — 처음엔 퇴장을 전부 놓침. fallback 추가 후
  처음부터 재처리하니 8개 이벤트 전부 정상 플래그.
- 사용자가 새 방을 파서 **프로필 4종**으로 번갈아 들낙 → **같은 방에선 userId 동일** 확인.
  (방이 다르면 userId 다름도 확인)

## 4. 배포 방식 선택

> "안드로이드폰 APK? 윈도우 에뮬레이터? 카톡 봇?" → **"WSL가지고 3 구현해봐"**

→ 방식 B (WSL2 + Redroid) 착수.

## 5. 방식 B 구축 (WSL2 + Redroid)

- Redroid 는 호스트 커널을 씀 → WSL 커널에 **binder** 가 필요. `microsoft/WSL2-Linux-Kernel` 직접 빌드.
- 삽질:
  - 모듈 전부 내장(`=y`) → 커널 43MB → WSL `CreateVm E_ABORT`. **모듈 분리 빌드**로 해결.
  - `.wslconfig` 의 `kernel=` 백슬래시 → 무시됨. **슬래시**로.
  - dockerd 가 nftables/NAT 생성 실패 → 모듈 로드가 docker보다 늦음. `modules-load.d` 프리로드.
  - 포트포워딩 안 됨 → `xt_nat` 등 모듈 보강.
  - 에뮬레이터가 호스트 5555 점유 → Redroid를 **5600:5555** 로. `adb localhost:5600` offline →
    **WSL IP 직결**(예 `192.168.105.52:5600`).
  - `vmIdleTimeout=-1` + `--restart unless-stopped` + systemd docker → **WSL 재부팅 자동복구** 확인.
- AVD에서 `libndk_translation` 추출 → `redroid-kakao:14` 이미지 오버레이. 카톡 설치·실행.
- 추가 발견(실검증 중):
  - Redroid adbd 는 기본 `shell` → **`adb root` 가능**(에뮬레이터처럼) → `/data/data` 읽힘.
  - Redroid 내장 `sqlite3` 가 DB 질의 시 **core dump** → 감지기에 **`READ_MODE=pull`** 추가
    (DB를 `adb pull` 로 호스트에 꺼내 로컬 sqlite3 로 읽음. `exec-out cat` 은 Windows 에서 바이너리 깨짐).
- **2026-10-27 전체 실검증:** 부계정 QR 로그인(인증번호 단계는 생략되기도) → 방 동기화 →
  피드 9건 복호화 → 들낙 판정까지 방식 A와 동일 동작. 프로필 4종이 전부 같은 userId 로 묶임 재확인.

## 6. 정리

- pnug·was(multisite) 등 **불필요한 도커 컨테이너 제거** (볼륨/프로젝트 폴더는 보존).
- 두 방식 + 감지기 + 이 히스토리를 **private git** 으로 정리(이 저장소).

## 7. 방식 C — PC 카톡 (안드로이드 제거) + Windows 앱 (2026-10-28)

"PC카톡으로 하면 안드로이드 의존성이 없어지잖아" → 조사·구현.

- PC 카톡(26.9.0)은 방별 `chatLogs_*.edb` = **SQLCipher4**(파일 전체 암호화, DB별 raw 32B 키).
  최신 방식은 **키가 KakaoTalk.exe 메모리에 상주**. 공개 툴 코드를 읽어 방식 확인 후
  자동승인이 외부코드 실행을 막아 → **자체 스크립트로 재구현**(읽기전용 메모리, 오픈챗만).
- 삽질: 도구는 32비트 포인터 가정인데 **KakaoTalk.exe는 64비트** → codec 주변 8바이트 포인터를
  역참조해 실제 edb로 검증하는 **오라클 방식**으로 해결. 키 30개 복구, `.edb`→평문 SQLite.
- `chatLogs(logId, **authorId**, type, message)`, **type=0 피드 message는 평문 JSON**
  (feedType 4=입장/2=퇴장, userId 포함) → kakaodecrypt 불필요. 오픈챗 목록은
  `chatListInfo(type=OM/OD)` + `openLinkListInfo(linkName)`.
- 엔드투엔드 실동작: 오픈챗 17방 자동 목록화, 관측 660명 중 **들낙 120명** 판정(닉 바꿔치기 묶임).
- **Windows 앱화**: `pc_detector.py`+`app.py`(감지+Flask+pywebview) → PyInstaller 단일
  `KakaoInoutDetector.exe`(~21MB). 클라이언트는 PC카톡 켜고 더블클릭만.

## 최종 상태

| 항목 | 상태 |
|---|---|
| 들낙 감지 로직 (복호화·판정) | ✅ 완료·실검증 (입장/퇴장/재입장, 프로필 다종) |
| 방식 A (Windows+AVD) | ✅ 전체 동작 |
| 방식 B (WSL+Redroid) | ✅ 전체 실검증 (adb root + pull 모드) |
| ⭐ 방식 C (PC 카톡 + .exe 앱) | ✅ 전체 실동작 (안드로이드 無, 단일 exe) |
| userId 성질 | ✅ 같은 방 불변, 방 간 상이 |

## 알려진 함정 / 다음 할 것

- 카톡 버전업 시 DB 스키마·`enc`·userId 포맷 변동 가능 → 재확인 필요.
- 강퇴(6)·초대(1) 피드 포맷 실측 미완.
- 알림 채널(텔레그램/웹훅/호출기) 미연결.
- **메모리 주의**: 에뮬레이터/WSL VM 둘 다 상시 뜨면 RAM 부담. (이 세션 중 유휴 시 백그라운드
  프로세스가 메모리 압박으로 종료된 바 있음 — 운영 시 한 방식만 켜둘 것)

## 8. 26.9.1 PC방 재검증 + 견고성 수정 + UI 리디자인 (2026-10-29~30)

새 PC(PC방, 카톡 **26.9.1.5339**)에서 방식 C 를 처음 돌리자 `keys=0` 으로 전혀 동작 안 함.
원래 코드는 26.9.0 한 환경에만 맞춰져 있었고, 환경에 따라 깨질 수 있는 지점들을 수정.

**환경 세팅(이 PC):** Git 2.56 / gh 2.103 / Python 3.13.17(+flask,cryptography,pywebview,
pyinstaller) / PC 카톡 26.9.1.5339 설치. 전부 공식 배포처 + 서명 확인. exe 빌드·실행 OK.

**고친 것 (master 에 머지됨):**
1. **키 포인터 폭** — 이 빌드는 힙이 4GB 미만이라 `codec_ctx` 안 키 포인터가 32비트 값으로
   4바이트 정렬돼 박힘. 기존은 8바이트 정렬 64비트로만 읽어 전부 버림(codec 31개·키 0개).
   → `_ptrs` 가 4바이트 간격에서 32/64비트 둘 다 시도. 키 복구됨.
2. **WAL 미반영** — 26.9.x 는 메인 `.edb` 가 빈 껍데기, 스키마·행이 전부 암호화된 `-wal` 에
   있음. 기존은 wal 복사만 하고 안 읽어 방 0개. → `_dec_page`/`_apply_wal` 로 SQLCipher WAL
   프레임을 누적 체크섬·커밋 규칙대로 리플레이(찢긴 프레임 방어 포함).
3. **계정 자동선택** — 캐시 계정이 여럿이라 엉뚱한 계정을 집던 문제. 키가 가장 많이 복구된
   계정(=메모리에 떠 있는 로그인 계정)을 자동 선택.
4. **키 캐싱** — 폴링마다 수백 MB 재스캔하던 것을 `ensure_keys()` 로 대체(1-AES 유효성 확인,
   무효 시에만 재추출). 실측 폴링당 6.25s → 0.03s.
5. **임시폴더 정리** — `prune()` 로 매 폴링 끝에 복호화 임시폴더 삭제(디스크 누적 방지).
6. **로컬 API CSRF 방어** — 외부 웹페이지가 `/api/watch`·`/api/note` 로 설정 변조하던 것 차단
   (Origin + JSON content-type 검사).
7. **UI 리디자인** — 네온/글로우/스캔라인 걷어내고 차분한 모던 대시보드로 재작성. 라이트/다크
   토글(시스템 기본), 외부 폰트·CDN 제거. API·동작 그대로.

실검증(26.9.1): 키 복구 → 오픈챗 방 탐지 → 피드 복호화 → 들낙 판정, 닉 바꿔치기도 동일
userId 로 묶임 확인. UI 미리보기 아티팩트로 확인.

**커밋/브랜치 상태:**
- `master`: 1~6(백엔드) 머지 완료(push 됨).
- `feat/ui-redesign-and-docs`: 7(UI) + 문서 정리. **이 핸드오프 시점에 아직 master 미머지.**

### 이어서 할 일 (다른 PC에서 resume)
- [x] `feat/ui-redesign-and-docs` 의 문서 정리 마무리(README·pc/README·detector/README 익명화
      일부 진행함) 후 커밋.
- [x] 새 `dashboard.html` 반영해 **exe 재빌드**(`pyinstaller app.spec --noconfirm`).
- [x] `feat/ui-redesign-and-docs` → `master` 머지(또는 PR).
- [ ] (선택) GitHub 저장소를 private 로 전환할지 결정. 현재 **public**.

## 9. resume 마무리 + 이모지 닉 버그 (2026-10-30)

새 PC 에서 이어받아 마무리. 환경: Git 2.56 / gh 2.103 / Python 3.13.15(+flask, cryptography,
pywebview, pyinstaller 6.22) / PC 카톡 실행 중.

- 문서 익명화 재점검 — 문서·코드에 실제 userId·닉 없음 확인. `.gitignore` 에 `pc/watch.json`
  추가(감지기 단독 실행 시 `pc/` 에 생겨 감시 chatId 가 커밋될 수 있었음).
- **버그: 이모지 닉에서 감지 정지 + 이벤트 중복.** `emit()` 이 `events.jsonl` 에 먼저 쓰고
  콘솔 `print` 에서 `UnicodeEncodeError(cp949)` → `run_once` 가 상태 저장 전에 터져 같은 이벤트가
  매 폴링 재기록되고 진행이 멈춤. → stdout `errors="replace"` + `emit` 의 print 를 try 로 감쌈
  (콘솔 출력은 부가 기능). cp949 콘솔·쓰기 불가 stdout 둘 다 이벤트 정상 기록 확인.
- exe 재빌드 후 테스트 계정으로 스모크: 계정 자동선택(테스트 계정), 키 복구, 방 탐지, 폴링
  오류 없음, 새 UI 서빙, 외부 Origin POST 403.
- 주의: 테스트는 반드시 **테스트 계정**으로. 실행 중 강제 종료 시 `%TEMP%\pckak_det_*` 에
  복호화 DB 사본이 남을 수 있으니 삭제할 것.
- 미검증/한계: 64비트 힙 경로(이 PC엔 32비트 경우만 있어 미실측), codec 파라미터·테이블/컬럼명·
  피드 JSON 하드코딩(버전업 시 재확인), 강퇴(6)·초대(1) 피드 포맷 미실측, 백신 오탐·권한 차단.
