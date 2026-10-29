# devtools — 대시보드 UI 검증 도구

실제 카톡 없이 **가짜 데이터**로 대시보드를 띄워 상태별 화면을 확인한다. 앱 빌드에는 포함되지 않는다.

```bash
pip install playwright && python -m playwright install chromium --only-shell

# 1) 목업 서버 (가짜 /api/*, 포트 8811)
python mock_server.py ../dashboard.html 8811

# 2) 다른 터미널에서: 상태별 스크린샷(시작 화면 4종·페이지 4종·배너 4종·라이트·420px) + JS 오류 수집
python -X utf8 ui_shots.py <출력폴더>

# 3) 데모 모드 검증(켜기/끄기, 이벤트 증가, 데모 중 서버 POST 0건, 시작 화면 진입)
python -X utf8 demo_test.py <출력폴더>
```

- 상태 전환: `GET /mock/phase?p=live|kakao_off|scanning|no_keys|error|no_rooms|starting|stale`
- 새 들낙 이벤트 주입: `GET /mock/add`
- 목업 서버는 시작 시 `dashboard.html` 을 읽으므로, UI 를 고친 뒤엔 서버를 다시 띄운다.
