#!/bin/bash
# Redroid(카톡 감지용) 기동. 데이터는 /root/redroid-data 에 영속.
set -e
grep -q binder /proc/filesystems || { echo "binder 미지원 커널"; exit 1; }
docker rm -f redroid-kakao >/dev/null 2>&1 || true
mkdir -p /root/redroid-data
docker run -d --name redroid-kakao --privileged --restart unless-stopped \
  -v /root/redroid-data:/data \
  -p 5600:5555 \
  redroid-kakao:14 \
  androidboot.redroid_width=720 androidboot.redroid_height=1280 androidboot.redroid_dpi=320 \
  androidboot.use_memfd=1 \
  ro.product.cpu.abilist=x86_64,arm64-v8a \
  ro.product.cpu.abilist64=x86_64,arm64-v8a \
  ro.product.cpu.abilist32= \
  ro.dalvik.vm.isa.arm64=x86_64 \
  ro.enable.native.bridge.exec=1 \
  ro.dalvik.vm.native.bridge=libndk_translation.so \
  ro.ndk_translation.version=0.2.3
docker ps --filter name=redroid-kakao --format '{{.Names}} {{.Status}}'
