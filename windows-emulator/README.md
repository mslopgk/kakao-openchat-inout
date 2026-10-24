# 방식 A — Windows + Android SDK 에뮬레이터

루팅폰 없이 PC 한 대로 돌리는 방식. **2026-10-25 실검증 완료** (입장/퇴장/재입장/오픈프로필 4종 교체).

## 구성

| 항목 | 값 |
|---|---|
| SDK | `D:\Android\Sdk` (cmdline-tools → platform-tools, emulator) |
| 시스템 이미지 | `system-images;android-34;google_apis;x86_64` |
| AVD | `kakaobot` (`ANDROID_AVD_HOME=D:\Android\avd`), pixel_6, RAM 4GB, data 8GB |
| 카톡 | 26.9.1 XAPK (base + `config.arm64_v8a` + en + mdpi) |

### 왜 이 이미지인가
- **google_apis** (Play 없는) 이미지는 `adb root`가 된다 → `/data/data/com.kakao.talk` 읽기 가능. Play Store 이미지는 root 불가.
- 카톡 최신은 **minSdk 32 (12L)** → API 30 이미지는 설치 불가. API 34 사용.
- 카톡 APK는 **arm64 전용**. API 34 x86_64 이미지에 `libndk_translation`(ARM→x86 번역)이 내장돼 있어 그대로 실행됨
  (`ro.dalvik.vm.native.bridge=libndk_translation.so`).

## 설치 절차

```bash
# 1) cmdline-tools (PowerShell 5.1의 Invoke-WebRequest는 매우 느림 → curl.exe)
curl.exe -sSL -o cmdtools.zip https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip
#   D:\Android\Sdk\cmdline-tools\latest\ 로 풀기

# 2) 패키지 (라이선스 동의는 Git Bash의 yes 로; PowerShell 파이프는 안 먹음)
export ANDROID_HOME=D:/Android/Sdk
yes | sdkmanager.bat --licenses
yes | sdkmanager.bat "platform-tools" "emulator" "system-images;android-34;google_apis;x86_64"

# 3) AVD
echo no | avdmanager.bat create avd -n kakaobot -k "system-images;android-34;google_apis;x86_64" -d pixel_6
#   config.ini: hw.ramSize=4096, disk.dataPartition.size=8G, hw.keyboard=yes

# 4) 기동 + root
emulator.exe -avd kakaobot -no-boot-anim -gpu auto -no-snapshot-save &
adb wait-for-device && adb root

# 5) 카톡 설치 (apkpure: d.apkpure.com 은 403, d.apkpure.net 은 됨)
curl -sSL -A "Mozilla/5.0" -o kakao.xapk "https://d.apkpure.net/b/APK/com.kakao.talk?version=latest"
unzip kakao.xapk -d kakao && cd kakao
adb install-multiple -r -g com.kakao.talk.apk config.arm64_v8a.apk config.en.apk config.mdpi.apk
adb shell dumpsys deviceidle whitelist +com.kakao.talk
```

## 로그인
- 첫 화면에서 **"보조 기기(Set as Secondary Device)"** 선택 → **QR 코드 로그인**.
- 폰 카톡 > 더보기 > 우상단 스캔 아이콘으로 QR 촬영 (QR 1분 유효).
- 보조 기기라서 **폰의 본 로그인은 유지**된다. 계정은 부계정 사용(약관상 비공식 자동화 → 정지 리스크 분산).
- 원격으로 진행할 땐 `adb exec-out screencap -p > qr.png` 로 QR을 찍어 다른 기기로 전달.

## 감지기 실행
```bash
python -m pip install pycryptodome
python -u ../detector/inout_detector.py
```
`adb shell sqlite3 -json ...` 로 3초마다 `chat_logs`를 읽는다 (에뮬레이터 이미지에 `/system/bin/sqlite3` 있음).

## UI 조작 팁 (`ui.sh`)
- 좌표 탭을 연달아 보내면 화면 전환 타이밍이 어긋나 **엉뚱한 버튼(방 삭제 등)을 누를 수 있다** — 실제로 "Delete & Leave" 확인창까지 갔었음.
- `uiautomator dump` 로 텍스트를 찾아 누르는 `ui.sh tap "텍스트"` 를 쓰고, 한 번에 한 동작씩.
- Git Bash에서 adb 쓸 때 `/sdcard/...` 가 Windows 경로로 변환되는 문제 → `MSYS_NO_PATHCONV=1`.
  (그 상태에선 로컬 경로를 `D:/...` 형태로 줘야 함)

## 장단점
- 👍 추가 장비 0, 이미 검증됨
- 👎 PC 상시 가동 필요, RAM 4GB+, 재부팅 시 에뮬레이터/감지기 재기동 필요
