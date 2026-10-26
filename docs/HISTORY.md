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

## 최종 상태

| 항목 | 상태 |
|---|---|
| 들낙 감지 로직 (복호화·판정) | ✅ 완료·실검증 (입장/퇴장/재입장, 프로필 4종) |
| 방식 A (Windows+AVD) | ✅ 전체 동작 |
| 방식 B (WSL+Redroid) | ✅ 전체 실검증 (adb root + pull 모드). 로그인만 사람이 QR 1회 |
| userId 성질 | ✅ 같은 방 불변, 방 간 상이 |

## 알려진 함정 / 다음 할 것

- 카톡 버전업 시 DB 스키마·`enc`·userId 포맷 변동 가능 → 재확인 필요.
- 강퇴(6)·초대(1) 피드 포맷 실측 미완.
- 알림 채널(텔레그램/웹훅/호출기) 미연결.
- **메모리 주의**: 에뮬레이터/WSL VM 둘 다 상시 뜨면 RAM 부담. (이 세션 중 유휴 시 백그라운드
  프로세스가 메모리 압박으로 종료된 바 있음 — 운영 시 한 방식만 켜둘 것)
