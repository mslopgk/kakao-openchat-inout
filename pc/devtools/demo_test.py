"""데모 모드 검증: 켜기/끄기, 가상 이벤트 증가, 데모 중 서버 POST 없음, 시작 화면에서 진입."""
import sys
import urllib.request
from playwright.sync_api import sync_playwright

OUT = sys.argv[1]
BASE = "http://127.0.0.1:8811"
errors, posts = [], []

with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1360, "height": 900})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("request", lambda r: r.method == "POST" and posts.append(r.url))

    # 1) 실제 데이터 화면에서 데모 켜기
    urllib.request.urlopen(f"{BASE}/mock/phase?p=live").read()
    pg.goto(BASE + "/#log")
    pg.wait_for_selector("#app:not([hidden])")
    pg.wait_for_timeout(800)
    pg.click("#demoRow")
    pg.wait_for_timeout(800)
    n0 = pg.locator("#logBody tr").count()
    pg.screenshot(path=f"{OUT}/demo_log.png", full_page=True)
    pg.wait_for_timeout(13000)          # 6초 틱 2번
    n1 = pg.locator("#logBody tr").count()
    pg.screenshot(path=f"{OUT}/demo_log_later.png")
    # 데모 중 동작: 화이트리스트 + 감시 방 → 서버 POST 가 없어야 함
    pg.click("nav button[data-page=blacklist]")
    pg.click("#blBody button[data-uid]")
    pg.click("nav button[data-page=watch]")
    pg.click(".rrow >> nth=1")
    pg.wait_for_timeout(500)
    demo_posts = list(posts)
    pg.click("nav button[data-page=overview]")
    pg.wait_for_timeout(500)
    pg.screenshot(path=f"{OUT}/demo_overview.png", full_page=True)
    # 끄기 → 실제(목업) 데이터 복귀
    pg.click("#bannerAct")
    pg.wait_for_timeout(1500)
    real_rooms = pg.locator("#roomSel option").all_inner_texts()
    pill = pg.inner_text("#pill")
    pg.screenshot(path=f"{OUT}/demo_off.png")

    # 2) 카톡 꺼짐 시작 화면에서 '데모로 둘러보기'
    urllib.request.urlopen(f"{BASE}/mock/phase?p=kakao_off").read()
    pg2 = b.new_page(viewport={"width": 1360, "height": 900})
    pg2.on("pageerror", lambda e: errors.append(str(e)))
    pg2.goto(BASE + "/")
    pg2.wait_for_timeout(1500)
    pg2.click("#bootDemo")
    pg2.wait_for_timeout(1000)
    boot_hidden = pg2.locator("#boot").is_hidden()
    pg2.screenshot(path=f"{OUT}/demo_from_boot.png")
    urllib.request.urlopen(f"{BASE}/mock/phase?p=live").read()
    b.close()

print(f"rows on={n0} later={n1} | demo POSTs={demo_posts} | after off rooms={real_rooms} pill={pill!r}"
      f" | boot hidden={boot_hidden} | errors={errors or 'none'}")
