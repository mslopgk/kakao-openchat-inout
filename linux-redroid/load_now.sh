#!/bin/bash
bash /mnt/d/Android/redroid/persist_modules.sh >/dev/null
while read m; do modprobe "$m" 2>&1 | head -1; done < /etc/modules-load.d/docker-redroid.conf
systemctl restart docker
