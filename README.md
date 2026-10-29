# kakao-openchat-inout

카카오톡 **오픈채팅방 들낙(들어왔다 나갔다) 감지기**.
내가 관리하는 오픈채팅방의 입장/퇴장 피드를 읽어 **userId 기준**으로 들낙러를 잡아낸다.

> **배경** — 오픈채팅엔 공식 봇 API가 없고, 알림만 읽는 봇은 입퇴장 피드를 못 본다.
> 그래서 카톡 클라이언트의 **로컬 DB 를 복호화**해 피드를 읽고 판정한다.
> 방장이 자기 방의 입퇴장을 보려는 용도이며, 계정은 **부계정** 사용을 권장한다.

## 빠른 시작 (권장: PC 카톡 앱)

1. Windows PC 에 **PC 카카오톡**을 설치하고 감시용 계정으로 로그인한다.
2. `KakaoInoutDetector.exe` 를 실행한다. (빌드: [`pc/README.md`](pc/README.md#빌드-단일-exe))
3. 시작 화면이 **앱 엔진 연결 → PC 카톡 확인 → 보안 키 확인**을 자동으로 진행하고 대시보드로 넘어간다.

안드로이드·에뮬레이터·WSL 이 필요 없고, 설치 없이 exe 하나로 동작한다.
창은 **WebView2 런타임**으로 뜬다(Windows 11 기본 포함, 없으면 기본 브라우저로 열림).

> 화면이 어떻게 보이는지만 확인하려면 사이드바의 **데모 모드**를 켠다.
> 가상 방·유저로 시연하며, 실제 감지 기록에는 아무것도 쓰지 않는다.

## 대시보드

| 화면 | 내용 |
|---|---|
| 시작 화면 | 연결 3단계 진행 표시. 카톡 미실행·미로그인 등은 해당 단계에 해결 방법 안내, 자동 재확인 |
| 개요 | 들낙 유저 / 관측 유저 / 입장 / 퇴장 KPI, 최근 들낙, 방별 현황, 최근 활동 |
| 들낙 블랙리스트 | userId 별 묶음(닉네임 바꿔도 같은 사람), 검색, 화이트리스트 |
| 이벤트 로그 | 최근 500건, 검색, 들낙만 보기. 새 들낙은 알림 + 메뉴 배지 |
| 감시 방 설정 | 감시할 오픈채팅방 선택(비우면 전체) |

상단에 감지 상태(실시간 / 카톡 꺼짐 / 로그인 필요 / 응답 지연 / 감지 오류 / 앱 연결 끊김)가 항상
표시되고, 연결이 끊기면 자동으로 다시 연결한다. 다크 기본, 라이트 전환 가능.

## 들낙 판정

- **입장 후 10분 안에 퇴장** → 들낙
- **24시간 안에 2번 이상 입장** → 들낙

기준값은 감지기 상수로 조정한다(`QUICK_LEAVE_SEC`, `REJOIN_WINDOW_SEC`, `REJOIN_COUNT`).

## 왜 이게 먹히나 (핵심 발견)

- 오픈채팅 입/퇴장은 대화 로그에 **피드(시스템 메시지, `type=0`)** 로 남는다. 암호화돼 있지만 복호 가능.
- **같은 방 안에서는** 기본프로필/오픈프로필을 바꿔 들낙해도 **userId 가 동일** → 프로필 갈아끼우기로 못 피한다. (4종 프로필로 실검증)
- 단, **방이 다르면 userId 가 다르다** (오픈채팅 userId는 방=링크별 발급) → 방 간 블랙리스트 공유는 불가.
- 퇴장 피드는 입장과 포맷이 달라 (`members` 배열 vs `member` 단수) 처음엔 퇴장을 전부 놓쳤었다.
- PC 카톡(26.9.x)은 DB 가 SQLCipher 로 암호화돼 있고 키는 실행 중인 카톡 **메모리**에 있다.
  최신 데이터는 대부분 `-wal` 파일에 있어 WAL 까지 복호화·반영해야 한다.

## 세 가지 구동 방식

| | 방식 A: Windows + AVD | 방식 B: WSL2 + Redroid | ⭐ 방식 C: PC 카톡 |
|---|---|---|---|
| 폴더 | [`windows-emulator/`](windows-emulator/) | [`linux-redroid/`](linux-redroid/) | [`pc/`](pc/) |
| 형태 | 안드로이드 에뮬레이터 | 도커 컨테이너(헤드리스) | **PC 카톡 + Windows 앱(.exe)** |
| 안드로이드 | 필요 | 필요 | **불필요** |
| 복호화 | 메시지 AES(kakaodecrypt) | 동일 | **SQLCipher4(메모리 키) + WAL** |
| 대시보드 | `admin.py` (웹) | `admin.py` (웹) | **앱 내장(v1.1)** |
| 상태 | 전체 실검증 | 전체 실검증 | **전체 실검증, 카톡 26.9.1 대응** |
| 적합 | 실험용 | 상시 가동 서버 | **클라이언트 배포(가장 가벼움)** |

- **방식 C 가 최종 권장**이다. 상세: [`pc/README.md`](pc/README.md).
- A·B 는 **같은 감지기**([`detector/`](detector/))를 쓴다(`adb` 로 DB 읽기, `ADB_SERIAL`만 다름).
- 공통 한계: 어느 방식이든 카톡 클라이언트가 **상시 온라인**이어야 피드를 받는다(메신저 방식의 본질).

<details>
<summary>방식 A·B 실행 (에뮬레이터 / Redroid)</summary>

```bash
# 방식 A: 에뮬레이터 기동 + root (상세: windows-emulator/README.md)
emulator.exe -avd kakaobot -no-boot-anim -gpu auto -no-snapshot-save &
adb wait-for-device && adb root
# 카톡 설치 → 보조기기 QR 로그인 → 감지기
python -m pip install pycryptodome
ADB_SERIAL=emulator-5554 python -u detector/inout_detector.py
```

관리자 대시보드 `admin.py` — 상시 감지 + 웹 대시보드를 한 프로세스로 돌린다.

```bash
pip install flask pycryptodome
python admin.py                     # Redroid(WSL) 자동 감지, http://localhost:8787
PORT=9000 python admin.py
ADB_SERIAL=emulator-5554 READ_MODE=shell python admin.py   # 방식 A(에뮬레이터)
```

- `ADB_SERIAL` 미지정 시 WSL IP(`<ip>:5600`)를 자동 해석하고 pull 모드로 뜬다 (방식 B).
- `notes.json` 에 화이트리스트/메모 저장(로컬, 커밋 안 함).

</details>

## 구성

```
pc/                방식 C: PC 카톡 감지기 + Windows 앱(대시보드 내장) ← 권장
  pc_detector.py     메모리 키 추출, SQLCipher·WAL 복호화, 들낙 판정
  app.py             감지 스레드 + 로컬 API + 네이티브 창(pywebview/WebView2)
  dashboard.html     대시보드 UI (외부 의존성 없음)
  app.spec           PyInstaller 단일 exe 빌드 설정
detector/          방식 A·B 공통 감지기. inout_detector.py + ref/kakaodecrypt.py
admin.py           방식 A·B 용 상시 감지 + 웹 대시보드 (Flask)
windows-emulator/  방식 A: AVD 설치/운영 스크립트
linux-redroid/     방식 B: 커널빌드/이미지/기동 스크립트
docs/              작업 히스토리(HISTORY.md), 필요사양(REQUIREMENTS.md)
```

## 주의 / 한계

- 오픈채팅 자동화는 **카톡 약관 위반**이라 계정 정지 위험이 있다 → 부계정 사용.
- DB 스키마·피드 포맷·키 구조는 **PC 카톡 26.9.1 실측 기준**. 카톡 버전이 올라가면 재확인이 필요하다.
- 방식 C 의 **메모리 키추출**은 카톡 빌드·OS 메모리 배치에 영향을 받는다. 32/64비트
  포인터를 모두 시도하고 실패 시 자동 재추출하지만, 구조체가 크게 바뀌면 보정 필요.
- 이 앱은 **로컬에서만** 동작하며 어떤 데이터도 외부로 보내지 않는다. 로컬 API 는
  `127.0.0.1` 에만 열리고, 외부 웹페이지의 설정 변경 요청(CSRF)은 차단한다.
- 개발·테스트는 **테스트 계정**으로 한다. 실계정 대화방 이름·닉네임이 화면과 로그에 노출될 수 있다.
- 복호화는 [jiru/kakaodecrypt](https://github.com/jiru/kakaodecrypt) (WTFPL) 사용(방식 A·B).
- **공개 저장소**다. 로그인 세션·DB·추출 바이너리·커널 이미지·빌드 산출물은 커밋하지
  않으며(`.gitignore`), 실데이터(userId·닉네임 등)는 문서·예시에도 넣지 않는다.
- 작업 경과와 남은 과제는 [`docs/HISTORY.md`](docs/HISTORY.md) 참고.
