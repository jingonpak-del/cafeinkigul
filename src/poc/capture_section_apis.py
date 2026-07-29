"""섹션 API 자동 캡처 — 일회성 개발 도구 (발굴 설계 0단계).

크롤 계정 세션으로 크롬창을 띄워 카페 섹션 페이지(파워/동네/테마)를 열고,
페이지가 호출하는 apis.naver.com XHR **주소**를 리소스 타이밍으로 수집한다.
그 다음 같은 세션 쿠키로 각 주소를 다시 받아 **응답 일부**를 파일에 남긴다.

실행:
    python -m src.poc.capture_section_apis

결과:
    data/section_capture.txt  ← 이 파일 내용을 그대로 붙여주면
    discovery.py 의 '매일 자동 5건 열거' 로직을 완성한다.

브라우저 자동화는 목록 화면을 여는 데만 쓰고(로그인·캡차 자동화 없음),
사장님이 이미 저장해 둔 로그인 세션 쿠키를 재사용한다.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "targets.json"
SESS_DIR = ROOT / "data" / "sessions"
OUT = ROOT / "data" / "section_capture.txt"

SECTION_PAGES = [
    ("powers_popular", "https://section.cafe.naver.com/ca-fe/home/powers/popular"),
    ("areas",          "https://section.cafe.naver.com/ca-fe/home/areas"),
    ("themes_2",       "https://section.cafe.naver.com/ca-fe/home/themes/2?type=ar"),
]

# 재조회할 가치가 있는 apis.naver.com 경로 힌트(카페 목록/랭킹 계열)
KEEP_HINTS = ("cafe", "home", "theme", "area", "power", "popular", "rank",
              "section", "mega", "recommend", "directory")
# 잡음(로그/광고/추적) 제외
DROP_HINTS = ("/log", "nlog", "wcs", "lcs", "/ads", "ad-", "veta", "sitrain",
              "pcr", "/count", "beacon")


def _iter_saved_sessions():
    from .dpapi import unprotect
    for p in SESS_DIR.glob("*.session"):
        try:
            rec = json.loads(unprotect(p.read_bytes()).decode("utf-8"))
            yield rec.get("account_id"), rec.get("cookies", [])
        except Exception:
            continue


def load_cookies():
    """config account 우선, 실패 시 저장된 세션 중 로그인 쿠키 보유분 사용."""
    from .session import SessionManager
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    acct = cfg.get("account")
    sm = SessionManager(SESS_DIR)
    if acct and sm.verify(acct).ok:
        return acct, sm.load_cookies(acct)
    for aid, cookies in _iter_saved_sessions():
        names = {c.get("name") for c in cookies}
        if "NID_AUT" in names and "NID_SES" in names:
            return aid, cookies
    return None, []


def _chrome_major():
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                k = winreg.OpenKey(hive, r"Software\Google\Chrome\BLBeacon")
                ver, _ = winreg.QueryValueEx(k, "version")
                return int(ver.split(".")[0])
            except Exception:
                continue
    except Exception:
        pass
    return None


def _interesting(url: str) -> bool:
    if "apis.naver.com" not in url:
        return False
    low = url.lower()
    if any(d in low for d in DROP_HINTS):
        return False
    return any(h in low for h in KEEP_HINTS)


def _collect_urls_via_browser(cookies):
    """크롬창을 띄워 각 섹션 페이지를 열고, 발생한 리소스 URL을 모은다.
    반환: {section_label: [url, ...]}"""
    import undetected_chromedriver as uc

    options = uc.ChromeOptions()
    for a in ("--lang=ko-KR", "--window-size=1400,1000",
              "--disable-blink-features=AutomationControlled"):
        options.add_argument(a)
    driver = uc.Chrome(options=options, version_main=_chrome_major())
    result: dict[str, list[str]] = {}
    try:
        # 쿠키 주입: naver 홈에서 먼저 심는다(.naver.com 쿠키가 전 서브도메인 커버).
        driver.get("https://www.naver.com")
        time.sleep(1.0)
        for c in cookies:
            ck = {"name": c.get("name"), "value": c.get("value"), "path": c.get("path", "/")}
            if c.get("domain"):
                ck["domain"] = c["domain"]
            try:
                driver.add_cookie(ck)
            except Exception:
                ck.pop("domain", None)
                try:
                    driver.add_cookie(ck)
                except Exception:
                    pass

        for label, url in SECTION_PAGES:
            print(f"[열기] {label}: {url}")
            try:
                driver.get(url)
            except Exception as e:
                print(f"   (로드 경고: {e})")
            # XHR가 충분히 발생하도록 대기 + 스크롤
            for _ in range(4):
                time.sleep(1.5)
                try:
                    driver.execute_script("window.scrollBy(0, 1200)")
                except Exception:
                    pass
            time.sleep(1.5)
            try:
                urls = driver.execute_script(
                    "return window.performance.getEntriesByType('resource').map(e=>e.name)")
            except Exception:
                urls = []
            uniq = sorted({u for u in urls if _interesting(u)})
            print(f"   apis.naver.com 후보 {len(uniq)}건")
            result[label] = uniq
        return result
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def _refetch(cookies, url, referer):
    """세션 쿠키로 URL을 다시 받아 (status, 응답스니펫) 반환."""
    from . import cafe_api
    cl = cafe_api.make_client(cookies)
    try:
        r = cl.get(url, headers={"Referer": referer, "X-Cafe-Product": "pc"}, timeout=12)
        body = r.text
        return r.status_code, body[:1600]
    except Exception as e:
        return None, f"(재조회 실패: {e})"
    finally:
        cl.close()


def run():
    acct, cookies = load_cookies()
    if cookies:
        print(f"세션 사용: {acct} (쿠키 {len(cookies)}개)")
    else:
        print("경고: 로그인 세션을 못 찾음 — 공개 목록만 잡힐 수 있음(계속 진행)")

    found = _collect_urls_via_browser(cookies)

    lines: list[str] = ["=== 카페 섹션 API 캡처 결과 ===", ""]
    page_url = {label: url for label, url in SECTION_PAGES}
    for label, urls in found.items():
        lines.append(f"\n########## [{label}] {page_url.get(label,'')} ##########")
        if not urls:
            lines.append("  (apis.naver.com 후보 없음 — 로그인/렌더 대기 확인 필요)")
            continue
        for u in urls:
            status, snippet = _refetch(cookies, u, page_url.get(label, "https://cafe.naver.com/"))
            lines.append(f"\n--- URL ---\n{u}\n--- HTTP {status} 응답(앞 1600자) ---\n{snippet}\n")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n저장 완료: {OUT}")
    print("이 파일 내용을 그대로 붙여주시면 섹션 열거 로직을 완성합니다.")


if __name__ == "__main__":
    run()
