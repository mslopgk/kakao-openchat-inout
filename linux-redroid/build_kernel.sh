#!/bin/bash
# WSL 커널 + binder. 커스텀 커널은 WSL 기본 모듈과 버전이 안 맞으므로
# 모듈도 같이 빌드해서 배포판 /lib/modules/<ver> 에 설치한다.
# (=m 을 전부 =y 로 내장하면 43MB 커널이 CreateVm E_ABORT 로 부팅 실패했음)
set -e
cd /root/wslkernel/src
cp Microsoft/config-wsl .config
scripts/config --enable CONFIG_ANDROID_BINDER_IPC --enable CONFIG_ANDROID_BINDERFS \
  --set-str CONFIG_ANDROID_BINDER_DEVICES "binder,hwbinder,vndbinder" \
  --set-str CONFIG_LOCALVERSION "-binder" \
  --disable CONFIG_DEBUG_INFO_BTF --disable CONFIG_DEBUG_INFO_BTF_MODULES
make olddefconfig >/dev/null
make -j16 bzImage modules > /root/wslkernel/build.log 2>&1 || { tail -30 /root/wslkernel/build.log; exit 1; }
make modules_install > /root/wslkernel/modinst.log 2>&1
KVER=$(make -s kernelrelease)
echo "kernelrelease=$KVER"; ls /lib/modules/
mkdir -p /mnt/c/Users/user/wslkernel
cp arch/x86/boot/bzImage /mnt/c/Users/user/wslkernel/bzImage-binder-mod
ls -la /mnt/c/Users/user/wslkernel
