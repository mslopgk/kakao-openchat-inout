# 필요 사양 (방식별)

## 방식 A — Windows + Android SDK 에뮬레이터(AVD)

AVD는 **완전한 시스템 에뮬레이터**라 CPU 가상화가 필수고 자원을 꽤 먹는다.

| 항목 | 최소 | 권장 |
|---|---|---|
| CPU | x86_64 + 하드웨어 가상화(Intel **VT-x** / AMD-V, BIOS 활성) | 4코어+ |
| 가속 | WHPX(Windows Hypervisor Platform) 또는 AEHD/HAXM | WHPX |
| RAM | 8GB (AVD에 4GB 할당 + Windows) | 16GB |
| 디스크 | ~20GB 여유 (SDK + API34 이미지 ~2GB + AVD data 8GB) | SSD |
| GPU | `-gpu auto` (없으면 swiftshader 소프트웨어 폴백) | 호스트 GPU |
| OS | Windows 10/11, 상시 켜둠 | — |

- Hyper-V/WSL2 와 WHPX 가 가상화를 공유하므로 둘 다 켜져 있어도 동작.
- 노트북/데스크톱 한 대로 바로 된다는 게 장점. 단 **항상 켜져 있어야** 감지가 유지됨.

## 방식 B — Linux VPS + Redroid

Redroid 는 **호스트 커널을 공유하는 컨테이너형 안드로이드**다. 그래서 VPS 종류를 많이 탄다.

### ⚠️ 가장 중요한 제약 — VPS 가상화 종류

| VPS 종류 | 가능? | 이유 |
|---|---|---|
| **KVM / 전용서버 / 베어메탈** | ✅ | 커널 모듈 로드 가능, `/dev/binder` 생성 가능 |
| **OpenVZ / LXC 컨테이너형** | ❌ | 커널 공유라 모듈 로드 불가, binder 장치 못 만듦 → Redroid 자체가 안 뜸 |

> 저렴한 "컨테이너 VPS"는 대부분 OpenVZ/LXC → **피해야 함.** 반드시 **KVM** 이상.
> Redroid 는 에뮬레이터가 아니므로 **중첩가상화(nested KVM)는 불필요** — 일반 KVM VPS면 충분.

### 커널 요구사항

- `binder_linux` 모듈 (devices `binder,hwbinder,vndbinder`) — 최신 Ubuntu 22.04/24.04 generic 커널에 모듈로 포함.
  ```bash
  sudo modprobe binder_linux devices="binder,hwbinder,vndbinder"
  grep binder /proc/filesystems   # binderfs 확인
  ```
- 구버전 커널은 `ashmem_linux` 도 필요하지만, 5.x+ 는 `use_memfd=1` 로 대체.
- 커널에 없으면 모듈 설치(`linux-modules-extra-$(uname -r)`)나 재컴파일 필요.
  (WSL2 는 기본 커널에 binder 가 없어 **직접 빌드**했음 — `linux-redroid/build_kernel.sh`. 일반 VPS는 보통 모듈만 로드하면 됨.)

### CPU 아키텍처 — x86 vs ARM (중요)

카톡 APK 는 **arm64 전용**이다.

| 호스트 | 추가 필요 | 비고 |
|---|---|---|
| **x86_64 VPS** | ARM→x86 번역(`libndk_translation`) 오버레이 | 번역 오버헤드 ↑, 불안정 가능 |
| **ARM64 VPS** (권장) | 없음 — 네이티브 arm64 실행 | 가볍고 안정적 |

> **권장: ARM64 VPS.** 번역 계층 없이 카톡이 네이티브로 돈다.
> 예) Oracle Cloud **Ampere A1**(무료 티어 4 vCPU/24GB), AWS Graviton, Hetzner Ampere, Azure Dpsv5.

### 사양

| 항목 | 최소 | 권장 |
|---|---|---|
| vCPU | 2 | 4 (x86 번역 쓰면 여유 더) |
| RAM | 2GB (Redroid ~1.5–2GB/인스턴스) | 4GB |
| 디스크 | 10GB (이미지 ~2GB + /data) | 20GB SSD |
| 소프트웨어 | Docker, KVM 커널 | — |

### 보안 (VPS라서 더 중요)

- **adb 포트(5555)를 절대 공개 노출 금지.** `127.0.0.1` 바인드 또는 VPN/방화벽 뒤로.
  (공개 adb = 누구나 기기 장악) → `-p 127.0.0.1:5600:5555`
- 로그인 세션이 들어있으므로 디스크/스냅샷 접근 통제.

## 요약 비교

| | 방식 A (Win+AVD) | 방식 B (Linux VPS+Redroid) |
|---|---|---|
| 형태 | 풀 에뮬레이터(GUI) | 컨테이너(헤드리스) |
| 가상화 | VT-x/WHPX 필수 | KVM VPS 필수(OpenVZ 불가), nested 불필요 |
| RAM | 8–16GB | 2–4GB |
| ARM 번역 | 이미지 내장(x86) | ARM VPS면 불필요 / x86면 오버레이 |
| 상시가동 | 내 PC 켜둠 | VPS가 24/7 (장점) |
| 난이도 | 낮음(바로 됨) | 중(커널·VPS 종류 주의) |
