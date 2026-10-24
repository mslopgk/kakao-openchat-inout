# 감지기 (`inout_detector.py`)

카톡 로컬 DB에서 오픈채팅 입장/퇴장 피드를 복호화해 **userId 기준으로 들낙을 판정**한다.
에뮬레이터/Redroid 공통 — 둘 다 `adb` 로 접근하므로 `ADB` 경로와 (Redroid면) `adb connect localhost:5555` 만 맞추면 된다.

## DB 구조 (KakaoTalk 26.9.1 기준, 실측)

- `/data/data/com.kakao.talk/databases/KakaoTalk.db`
  - `chat_rooms(id, type, link_id, members, active_member_ids, ...)` — 오픈채팅 그룹방 `type='OM'`
  - `chat_logs(_id, id, type, chat_id, user_id, message, attachment, created_at, v, ...)`
    - `type=0` 이 **피드(시스템 메시지)**, `type=1` 일반 텍스트
    - `message` 는 암호화(base64). `v` JSON 의 `enc` 값(관측값 31)이 암호화 타입
- `KakaoTalk2.db`
  - `open_link(id, name, url, ...)` — 오픈채팅 링크/방 이름 (`chat_rooms.link_id` 로 조인)
  - `open_chat_member`, `open_profile` 등

## 복호화
- [jiru/kakaodecrypt](https://github.com/jiru/kakaodecrypt) (WTFPL) 를 `ref/` 에 그대로 포함.
- `chat_logs` 는 **행의 `user_id`(보낸 사람)** + `enc` 로 키 유도 (PKCS12-SHA1 KDF → AES-CBC).
- 다른 테이블(`open_chat_member` 등)은 **내 user_id** 로 복호.

## 피드 포맷 (복호화 결과)

```json
{"feedType":4,"members":[{"userId":8692748093171013120,"nickName":"이지호"}]}   // 입장 — members 배열
{"feedType":2,"member":{"userId":8692748093171013120,"nickName":"이지호"}}       // 퇴장 — member 단수 객체 (!)
```

| feedType | 의미 |
|---|---|
| 1 | 초대 |
| 2 | 퇴장 |
| 4 | 입장 (오픈채팅) |
| 6 | 강퇴 |

> 처음엔 `members` 만 읽어서 퇴장을 전부 놓쳤다. 퇴장은 `member` 단수 키.

## userId 성질 (실측)
- **같은 방 안에서는** 기본 프로필 ↔ 오픈프로필 4종을 바꿔가며 들낙해도 **userId 동일** → 프로필 갈아끼우기로 못 피함.
- **방이 다르면 userId가 다르다** (같은 본계정: 방1 `8770…4245`, 방2 `8692…3120`). 오픈채팅 userId는 방(링크)별 발급 → 방 간 블랙리스트 공유 불가.

## 판정 규칙 (상수로 조정)
- `QUICK_LEAVE_SEC = 600` — 입장 후 10분 내 퇴장 → 들낙
- `REJOIN_WINDOW_SEC = 86400`, `REJOIN_COUNT = 2` — 24시간 내 2번째 입장부터 들낙

## 출력
- 콘솔 + `events.jsonl` (이벤트 1줄 1JSON), 진행상태 `state.json` (`last_id`, userId별 이력)
- 재시작하면 `last_id` 이후부터 이어서 처리 (꺼져 있던 동안의 기록도 따라잡음)

## TODO
- 알림 채널 (텔레그램/웹훅/c.kgpolsm.cloud 호출기)
- 강퇴(6) 실측, 초대(1) 포맷 확인
