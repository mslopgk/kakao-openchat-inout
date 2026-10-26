# 방식 B — WSL2 + Redroid (리눅스/도커)

PC 한 대에서 **헤드리스**로 돌리는 방식. 에뮬레이터 GUI 없이 도커 컨테이너로 안드로이드를 띄우고,
`adb` 로만 붙는다. 상시 가동·자동 재시작에 유리.

> **상태: 전체 실검증 완료 (2026-10-27).** 부계정 QR 로그인 → 방 동기화 → 피드 9건 복호화 →
> 들낙 판정까지 방식 A와 동일하게 동작 확인. (프로필 4종이 전부 같은 userId로 묶임도 재확인)
> 로그인만 사람이 부계정 폰으로 QR 1회 스캔(+경우에 따라 인증번호 입력) — 자동화 불가.

## 왜 이렇게 복잡한가

Redroid 는 **호스트 커널**을 그대로 쓰는 컨테이너형 안드로이드다. 그래서 두 가지가 필요하다.

1. **커널에 binder** (`CONFIG_ANDROID_BINDER_IPC`, `CONFIG_ANDROID_BINDERFS`) — 안드로이드 IPC.
   WSL2 기본 커널엔 없다 → **직접 빌드**해서 `.wslconfig` 로 교체.
2. **ARM 번역 계층** — 카톡 APK 는 arm64 전용인데 Redroid 공식 이미지는 x86_64.
   방식 A 의 AVD(`system-images;android-34;google_apis;x86_64`)에서 `libndk_translation` 88개 파일을
   꺼내 이미지에 오버레이한다 (`Dockerfile`).

## 1) 커널 빌드 — `build_kernel.sh`

WSL 커널 소스(`/root/wslkernel/src`, `microsoft/WSL2-Linux-Kernel`)에서:

- `config-wsl` 기반으로 binder 3종(`binder,hwbinder,vndbinder`) 활성
- `LOCALVERSION=-binder`, BTF 끔 (`resolve_btfids` 빌드 에러 회피)
- **`bzImage` + `modules` 둘 다** 빌드하고 `make modules_install` 로 `/lib/modules/<ver>` 설치

> ⚠️ 처음엔 `=m` 모듈을 전부 `=y`(내장)로 바꿨더니 커널이 43MB가 되고 WSL VM이
> `CreateVm E_ABORT` 로 아예 부팅을 못 했다. → **모듈은 모듈대로 빌드·설치**하는 지금 방식으로 해결.
> 커널 릴리스: `6.6.114.1-binder+`.

`C:\Users\user\.wslconfig`:
```ini
[wsl2]
kernel=C:/Users/user/wslkernel/bzImage-binder-mod   # 경로는 슬래시(/) — 백슬래시면 무시됨
vmIdleTimeout=-1                                      # 유휴 자동종료 끔 (상시 가동)
```
적용: `wsl --shutdown` 후 재기동. 원복은 이 두 줄 지우고 `wsl --shutdown`.

## 2) 모듈 프리로드 — `persist_modules.sh`

커스텀 커널은 모듈 자동 로드가 `dockerd` 기동보다 늦어서 dockerd 가 nftables/NAT 생성에 실패했다.
`/etc/modules-load.d/docker-redroid.conf` 에 netfilter/NAT/브리지/포트포워딩 모듈을 적어
**부팅 시 systemd-modules-load 가 먼저 올리게** 한다. (`load_now.sh` 는 재부팅 없이 지금 바로 로드+도커 재시작)

## 3) 이미지 빌드 — `build_image.sh` + `Dockerfile`

```dockerfile
FROM redroid/redroid:14.0.0_64only-latest
COPY --chmod=755 ndk/system/ /system/     # AVD에서 추출한 libndk_translation 오버레이
```
`ndk/system/` 은 방식 A AVD 에서 뽑은 것(용량 커서 git 제외 — `.gitignore` 참고). → `redroid-kakao:14`.

## 4) 기동 — `run_redroid.sh`

```bash
docker run -d --name redroid-kakao --privileged --restart unless-stopped \
  -v /root/redroid-data:/data -p 5600:5555 redroid-kakao:14 \
  ... ro.dalvik.vm.native.bridge=libndk_translation.so ...
```

- **포트 5600:5555** — 방식 A 에뮬레이터가 호스트 5555 를 이미 점유 → 충돌 피하려 5600 으로.
- `--restart unless-stopped` + `vmIdleTimeout=-1` + systemd 도커 → **WSL 재부팅해도 자동 복구**.
  (`wsl --shutdown` 후 모듈·도커·컨테이너·설치된 카톡까지 복원되는 것 확인)

## 5) 접속 / 카톡 설치 / 로그인

```bash
# Windows adb 에서 WSL IP 로 붙는다. localhost:5600 은 offline 으로 뜸.
WSL_IP=$(wsl -d Ubuntu -u root -- hostname -I | awk '{print $1}')   # 예: 192.168.105.52
adb connect $WSL_IP:5600
adb -s $WSL_IP:5600 root          # Redroid adbd 는 기본 shell(uid 2000) → root 로 승격해야 /data 읽음
adb -s $WSL_IP:5600 install-multiple -r -g com.kakao.talk.apk config.arm64_v8a.apk config.en.apk config.mdpi.apk
```

> **adb root 필수.** 에뮬레이터와 달리 Redroid 는 `adb root` 를 지원한다("restarting adbd as root").
> 안 하면 adbd 가 `shell` 권한이라 `/data/data/com.kakao.talk` 를 못 읽는다.

로그인: 카톡 첫 화면에서 **Set as Secondary Device → Confirm → QR Code Log In**.
부계정 폰 카톡 > 더보기 > 우상단 스캔으로 QR 촬영(**55초 유효**). 이후 **인증번호(Registration Code, ~40초)** 가
뜨면 폰 주기기에 입력(생략되고 바로 넘어가는 경우도 있음) → 권한 안내 OK → 메인 진입 → 방 자동 동기화.

> 원격 진행 팁: `adb exec-out screencap` 는 Windows 에서 바이너리가 깨지니 `screencap -p /sdcard/x.png`
> 후 `adb pull` 로 가져온다. 인증번호는 `uiautomator dump` 로 텍스트 추출하면 OCR 없이 정확.

## 6) 감지기 실행 — **`READ_MODE=pull` 필수**

```bash
ADB_SERIAL=$WSL_IP:5600 READ_MODE=pull python -u ../detector/inout_detector.py
```

> **왜 pull 모드인가:** Redroid 내장 `sqlite3` 는 KakaoTalk.db 질의 시 **core dump(Aborted)** 로 죽는다.
> 그래서 감지기는 `adb shell sqlite3`(방식 A) 대신 **DB(+wal/shm)를 `adb pull` 로 호스트에 꺼내
> 로컬 sqlite3 로 읽는다**(`READ_MODE=pull`). `adb exec-out cat` 은 Windows 에서 바이너리가
> CRLF 로 깨지므로 반드시 `adb pull` 을 쓴다.

## 삽질 로그 (요약)

| 증상 | 원인 | 해결 |
|---|---|---|
| WSL VM `CreateVm E_ABORT` | 모듈 전부 내장해 커널 43MB | 모듈 분리 빌드 |
| `.wslconfig` kernel 무시 | 백슬래시 경로 | 슬래시(`/`)로 |
| dockerd 기동 실패 (nftables) | 모듈 로드가 docker보다 늦음 | `modules-load.d` 프리로드 |
| 포트포워딩 안 됨 | `xt_nat` 등 누락 | 모듈 목록 보강 |
| `adb localhost:5600` offline | WSL NAT | WSL IP 직결 |
| 셸 변수 `$...` 가 날아감 | `wsl.exe` 가 먼저 해석 | `.sh` 로 저장 후 `wsl ... bash x.sh` |
| `/data/data` 못 읽음 | Redroid adbd 가 shell(uid 2000) | `adb root` 로 승격 |
| 내장 `sqlite3` core dump | Redroid sqlite3 가 DB 질의 시 Abort | DB pull 후 호스트 sqlite3 (`READ_MODE=pull`) |
| `adb pull` 경로가 Windows 경로로 변환 | Git Bash 경로 변환 | `MSYS_NO_PATHCONV=1` + 로컬은 `D:/...` |

## 장단점

- 👍 헤드리스, 자동 재시작, 상시 가동에 적합
- 👎 커널 자가빌드(최초 1회) 필요, WSL IP 로만 접근, 방식 A 보다 초기 구성이 길다
