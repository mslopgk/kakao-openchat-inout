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

## 두 가지 구동 방식

| | 방식 A: Windows + AVD | 방식 B: WSL2 + Redroid |
|---|---|---|
| 폴더 | [`windows-emulator/`](windows-emulator/) | [`linux-redroid/`](linux-redroid/) |
| 형태 | 안드로이드 에뮬레이터(GUI) | 도커 컨테이너(헤드리스) |
| root | `adb root` (google_apis 이미지) | `--privileged` |
| 상태 | **전체 실검증 완료** | **전체 실검증 완료** (adb root + `READ_MODE=pull`) |
| 적합 | 바로 쓰기 | 상시 가동/자동복구 |

둘 다 **같은 감지기**([`detector/`](detector/))를 쓴다 — `adb` 로 DB를 읽으므로 `ADB_SERIAL`만 맞추면 공통.

## 빠른 시작 (방식 A)

```bash
# 에뮬레이터 기동 + root (상세: windows-emulator/README.md)
emulator.exe -avd kakaobot -no-boot-anim -gpu auto -no-snapshot-save &
adb wait-for-device && adb root
# 카톡 설치 → 보조기기 QR 로그인 → 감지기
python -m pip install pycryptodome
ADB_SERIAL=emulator-5554 python -u detector/inout_detector.py
```

## 구성

```
detector/          감지기 (공통). inout_detector.py + ref/kakaodecrypt.py
windows-emulator/  방식 A: AVD 설치/운영, ui.sh, overnight_logger.sh
linux-redroid/     방식 B: 커널빌드/이미지/기동 스크립트
docs/              작업·대화 히스토리 (HISTORY.md)
```

## 주의 / 한계

- 오픈채팅 자동화는 **카톡 약관 위반**이라 계정 정지 위험이 있다 → 부계정 사용.
- `userId`·DB 스키마·`enc` 값은 **카톡 26.9.1 실측 기준**. 버전 올라가면 바뀔 수 있음.
- 복호화는 [jiru/kakaodecrypt](https://github.com/jiru/kakaodecrypt) (WTFPL) 사용.
- 이 저장소는 **private**. 로그인 세션·DB·추출 바이너리·커널 이미지는 커밋하지 않는다 (`.gitignore`).
