"""Single-account Naver session: manual login -> cookie capture -> verify.

No CAPTCHA bypass and no automation of the login itself: a real browser opens,
the operator logs in by hand (solving any CAPTCHA / 2-step / protection prompt),
then we capture the cookies. This mirrors the proven, low-risk approach in the
existing naver_cafe_session_program scaffold.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .cookie_store import CookieStore, SessionRecord
from . import cafe_api

NAVER_LOGIN = "https://nid.naver.com/nidlogin.login"
NAVER_HOME = "https://www.naver.com/"


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    reason: str


def _make_driver():
    # Plain Selenium is enough for manual login capture. undetected-chromedriver
    # can be swapped in here later if Naver starts flagging the session.
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument("--lang=ko-KR")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    return webdriver.Chrome(options=options)


class SessionManager:
    def __init__(self, session_dir: Path) -> None:
        self.store = CookieStore(session_dir)

    def capture(self, account_id: str) -> Path:
        driver = _make_driver()
        try:
            driver.get(NAVER_LOGIN)
            input("브라우저에서 직접 로그인(캡챠/보호조치 통과)한 뒤, 여기서 Enter: ")
            driver.get(NAVER_HOME)
            cookies = driver.get_cookies()
            if not cookies:
                raise RuntimeError("쿠키를 가져오지 못했습니다.")
            return self.store.save(account_id, cookies)
        finally:
            driver.quit()

    def load_cookies(self, account_id: str) -> list[dict]:
        return self.store.load(account_id).cookies

    def verify(self, account_id: str) -> VerifyResult:
        if not self.store.exists(account_id):
            return VerifyResult(False, "저장된 세션 없음")
        cookies = self.store.load(account_id).cookies
        # A logged-in session carries NID_AUT / NID_SES cookies.
        names = {c["name"] for c in cookies}
        if "NID_AUT" not in names or "NID_SES" not in names:
            return VerifyResult(False, "로그인 쿠키(NID_AUT/NID_SES) 없음 — 재로그인 필요")
        return VerifyResult(True, f"쿠키 {len(cookies)}개 보유 (로그인 쿠키 확인됨)")
