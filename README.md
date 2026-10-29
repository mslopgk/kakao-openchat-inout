# kakao-openchat-inout

카카오톡 **오픈채팅방 들낙(들어왔다 나갔다) 감지기**.
내가 관리하는 오픈채팅방에서 입장/퇴장/재입장 피드를 읽어 **userId 기준**으로 들낙러를 잡아낸다.

> **배경** — 오픈채팅엔 공식 봇 API가 없다. 알림만 읽는 봇은 입퇴장 피드를 못 본다.
> 그래서 카톡 클라이언트를 하나 띄워 그 **로컬 DB(`KakaoTalk.db`)의 피드를 복호화**해서 판정한다.
> 방장이 자기 방의 입퇴장을 보려는 용도이며, 계정은 **부계정을 보조기기(2nd device)**로 로그인해 쓴다.

## 왜 이게 먹히나 (핵심 발견)

- 오픈채팅 입/퇴장은 `chat_logs` 에 **피드(시스템 메시지, `type=0`)** 로 남는다. 암호화돼 있지만 복호 가능.
- **같은 방 안에서는** 기본프로필/오픈프로필을 바꿔 들낙해도 **userId 가 동일** → 프로필 갈아끼우기로 못 피한다. (4종 프로필로 실검증)
- 단, **방이 다르면 userId 가 다르다** (오픈채팅 userId는 방=링크별 발급) → 방 간 블랙리스트 공유는 불가.
- 퇴장 피드는 입장과 포맷이 달라 (`members` 배열 vs `member` 단수) 처음엔 퇴장을 전부 놓쳤었다.

## 세 가지 구동 방식

| | 방식 A: Windows + AVD | 방식 B: WSL2 + Redroid | ⭐ 방식 C: PC 카톡 |
|---|---|---|---|
| 폴더 | [`windows-emulator/`](windows-emulator/) | [`linux-redroid/`](linux-redroid/) | [`pc/`](pc/) |
| 형태 | 안드로이드 에뮬레이터 | 도커 컨테이너(헤드리스) | **PC 카톡 네이티브** |
| 안드로이드 | 필요 | 필요 | **불필요** |
| 복호화 | 메시지 AES(kakaodecrypt) | 동일 | **SQLCipher4(메모리 키)** |
| 상태 | 전체 실검증 | 전체 실검증 | **전체 실검증 + .exe 앱** |
| 적합 | 바로 쓰기 | 상시 가동 | **클라이언트 배포(가장 가벼움)** |

- A·B 는 **같은 감지기**([`detector/`](detector/))를 쓴다(`adb` 로 DB 읽기, `ADB_SERIAL`만 다름).
- **방식 C 가 최종 권장** — 에뮬·WSL·adb 없이 PC 카톡만 켜고 `.exe` 더블클릭. `authorId`(userId)로
  프로필 바꿔치기까지 추적. 자세한 건 [`pc/README.md`](pc/README.md).
- 공통 한계: 어느 방식이든 카톡 클라이언트가 **상시 온라인**이어야 피드를 받는다(메신저 방식의 본질).

## 빠른 시작 (방식 A)

```bash
# 에뮬레이터 기동 + root (상세: windows-emulator/README.md)
emulator.exe -avd kakaobot -no-boot-anim -gpu auto -no-snapshot-save &
adb wait-for-device && adb root
# 카톡 설치 → 보조기기 QR 로그인 → 감지기
python -m pip install pycryptodome
ADB_SERIAL=emulator-5554 python -u detector/inout_detector.py
```

## 관리자 대시보드 (`admin.py`)

**상시 감지 + 웹 대시보드를 한 프로세스로** 돌린다. 감지기를 백그라운드 스레드로 상시 실행하면서
실시간 이벤트 로그와 **userId별 들낙 블랙리스트**(프로필 바꿔도 묶임)를 보여준다.

```bash
pip install flask pycryptodome
python admin.py                     # Redroid(WSL) 자동 감지, http://localhost:8787
PORT=9000 python admin.py
ADB_SERIAL=emulator-5554 READ_MODE=shell python admin.py   # 방식 A(에뮬레이터)
```

- `ADB_SERIAL` 미지정 시 WSL IP(`<ip>:5600`)를 자동 해석하고 pull 모드로 뜬다 (방식 B).
- 대시보드: 현황(들낙 유저 수 등) · 블랙리스트(userId별 닉/입퇴장/들낙 횟수, 화이트리스트 토글) · 실시간 로그(방 필터, 들낙만 보기).
- `notes.json` 에 화이트리스트/메모 저장(로컬, 커밋 안 함).

## 구성

```
admin.py           상시 감지 + 관리자 대시보드 (Flask)
detector/          감지기 (공통). inout_detector.py + ref/kakaodecrypt.py
windows-emulator/  방식 A: AVD 설치/운영, ui.sh, overnight_logger.sh
linux-redroid/     방식 B: 커널빌드/이미지/기동 스크립트
docs/              작업·대화 히스토리(HISTORY.md), 필요사양(REQUIREMENTS.md)
```

## 주의 / 한계

- 오픈채팅 자동화는 **카톡 약관 위반**이라 계정 정지 위험이 있다 → 부계정 사용.
- `userId`·DB 스키마·`enc` 값은 **카톡 26.9.1 실측 기준**. 버전 올라가면 바뀔 수 있음.
- 방식 C 의 **메모리 키추출**은 카톡 빌드·OS 메모리 배치에 영향을 받는다. 32/64비트
  포인터를 모두 시도하고 실패 시 자동 재추출하지만, 구조체가 크게 바뀌면 보정 필요.
- 복호화는 [jiru/kakaodecrypt](https://github.com/jiru/kakaodecrypt) (WTFPL) 사용.
- **공개 저장소**다. 로그인 세션·DB·추출 바이너리·커널 이미지·빌드 산출물은 커밋하지
  않으며(`.gitignore`), 실데이터(userId·닉네임 등)는 문서·예시에도 넣지 않는다.
