#!/bin/bash
set -e
mkdir -p /root/redroid-build
rsync -a --delete /mnt/d/Android/redroid/ndk /mnt/d/Android/redroid/Dockerfile /root/redroid-build/
cd /root/redroid-build
docker build -t redroid-kakao:14 . 2>&1 | tail -5
docker images redroid-kakao
