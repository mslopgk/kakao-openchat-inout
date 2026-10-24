#!/usr/bin/env bash
# 밤새 원본 데이터 수집: 방 멤버 스냅샷 변화 + 새 chat_logs 행(원문 그대로)
ADB=/d/Android/Sdk/platform-tools/adb.exe
OUT=/d/Android/kakaobot/raw
mkdir -p "$OUT"
DB=/data/data/com.kakao.talk/databases/KakaoTalk.db
last_id=0
prev=""
while true; do
  ts=$(date '+%F %T')
  rooms=$($ADB shell "sqlite3 $DB \"select id,type,link_id,active_members_count,members from chat_rooms order by id;\"" 2>/dev/null | tr -d '\r')
  if [ -n "$rooms" ] && [ "$rooms" != "$prev" ]; then
    { echo "=== $ts"; echo "$rooms"; } >> "$OUT/rooms.log"
    prev="$rooms"
  fi
  rows=$($ADB shell "sqlite3 -separator ' | ' $DB \"select _id,id,type,chat_id,user_id,created_at,v,message,attachment from chat_logs where _id>$last_id order by _id;\"" 2>/dev/null | tr -d '\r')
  if [ -n "$rows" ]; then
    echo "$rows" | sed "s/^/[$ts] /" >> "$OUT/chat_logs.log"
    nid=$(echo "$rows" | tail -1 | cut -d' ' -f1)
    [[ "$nid" =~ ^[0-9]+$ ]] && last_id=$nid
  fi
  sleep 20
done
