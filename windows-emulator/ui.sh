#!/usr/bin/env bash
# 사용: ui.sh ls            -> 화면의 텍스트/설명 + 중심좌표
#       ui.sh tap "텍스트"   -> 해당 텍스트(또는 content-desc) 요소 중앙 탭
#       ui.sh back
export MSYS_NO_PATHCONV=1
ADB=/d/Android/Sdk/platform-tools/adb.exe
dump() {
  $ADB shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1
  $ADB shell cat /sdcard/ui.xml | tr '>' '\n' | grep -E '(text|content-desc)="[^"]+"' |
    sed -E 's/.*text="([^"]*)".*content-desc="([^"]*)".*bounds="\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]".*/\1|\2|\3 \4 \5 \6/' |
    awk -F'|' '{split($3,b," "); printf "%s|%s|%d %d\n",$1,$2,(b[1]+b[3])/2,(b[2]+b[4])/2}'
}
case "$1" in
  ls) dump ;;
  tap)
    xy=$(dump | awk -F'|' -v t="$2" '$1==t || $2==t {print $3; exit}')
    [ -z "$xy" ] && { echo "not found: $2"; exit 1; }
    $ADB shell input tap $xy; echo "tapped $2 @ $xy" ;;
  back) $ADB shell input keyevent 4 ;;
esac
