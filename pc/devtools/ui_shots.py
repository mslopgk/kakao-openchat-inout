"""목업 서버(8811)에 붙어 상태별 스크린샷 + 콘솔 오류 수집."""
import sys
import urllib.request
from playwright.sync_api import sync_playwright

OUT = sys.argv[1]
BASE = "http://127.0.0.1:8811"
errors = []


def phase(p):
    urllib.request.urlopen(f"{BASE}/mock/phase?p={p}").read()


with sync_playwright() as pw:
    b = pw.chromium.launch()

    def page(w=1360, h=900, theme=None):
        ctx = b.new_context(viewport={"width": w, "height": h}, locale="ko-KR")
        if theme:
            ctx.add_init_script(f"localStorage.setItem('deullak-theme','{theme}')")
        pg = ctx.new_page()
        pg.on("console", lambda m: m.type == "error" and errors.append(m.text))
        pg.on("pageerror", lambda e: errors.append(str(e)))
        return pg

    # 시작 화면
    for ph in ("scanning", "kakao_off", "no_keys", "error"):
        phase(ph)
        pg = page()
        pg.goto(BASE + "/")
        pg.wait_for_timeout(1500)
        pg.screenshot(path=f"{OUT}/boot_{ph}.png")
        pg.context.close()

    # 앱 진입(live) → 페이지별
    phase("live")
    pg = page()
    pg.goto(BASE + "/")
    pg.wait_for_selector("#app:not([hidden])", timeout=8000)
    pg.wait_for_timeout(1200)
    pg.screenshot(path=f"{OUT}/overview.png", full_page=True)
    urllib.request.urlopen(f"{BASE}/mock/add").read()
    pg.wait_for_timeout(4600)
    pg.screenshot(path=f"{OUT}/new_deullak.png")
    for p in ("blacklist", "log", "watch"):
        pg.click(f"nav button[data-page={p}]")
        pg.wait_for_timeout(500)
        pg.screenshot(path=f"{OUT}/{p}.png", full_page=True)
    # 동작: 화이트리스트 추가 → 토스트
    pg.click("nav button[data-page=blacklist]")
    pg.click("#blSeg button[data-v=all]")
    pg.click("#blBody button[data-uid='9001']")
    pg.wait_for_timeout(600)
    pg.screenshot(path=f"{OUT}/blacklist_toast.png")
    pg.click("#blBody button[data-uid='9001']")  # 원복
    # 감시 방 토글
    pg.click("nav button[data-page=watch]")
    pg.click(".rrow[data-id='1004']")
    pg.wait_for_timeout(600)
    pg.screenshot(path=f"{OUT}/watch_toggle.png")
    # 상태 배너: 카톡 꺼짐 / 오류 / 응답 지연 / 연결 끊김
    pg.click("nav button[data-page=overview]")
    for ph in ("kakao_off", "error", "stale"):
        phase(ph)
        pg.wait_for_timeout(2600)
        pg.screenshot(path=f"{OUT}/banner_{ph}.png")
    phase("live")
    pg.route("**/api/**", lambda r: r.abort())
    pg.wait_for_timeout(4500)
    pg.screenshot(path=f"{OUT}/banner_offline.png")
    pg.unroute("**/api/**")
    pg.wait_for_timeout(9000)
    pg.screenshot(path=f"{OUT}/reconnected.png")
    pg.context.close()

    # 라이트 테마 + 좁은 화면
    pg = page(theme="light")
    pg.goto(BASE + "/#overview")
    pg.wait_for_selector("#app:not([hidden])", timeout=8000)
    pg.wait_for_timeout(1200)
    pg.screenshot(path=f"{OUT}/overview_light.png", full_page=True)
    pg.context.close()
    pg = page(w=420, h=860)
    pg.goto(BASE + "/#blacklist")
    pg.wait_for_selector("#app:not([hidden])", timeout=8000)
    pg.wait_for_timeout(1200)
    pg.screenshot(path=f"{OUT}/narrow.png", full_page=True)
    pg.context.close()
    b.close()

print("errors:", errors or "none")
