"""Single-account Naver session: manual login -> cookie capture -> verify.

No CAPTCHA bypass and no automation of the login itself: a real browser opens,
the operator logs in by hand (solving any CAPTCHA / 2-step / protection prompt),
then we capture the cookies. This mirrors the proven, low-risk approach in the
existing naver_cafe_session_program scaffold.
"""
from __future__ import annotations

from pathlib import Path

# 만료·지문 판정은 공용 코어로 이관됐다(navercafe_core.sessioninfo).
# 여기서는 재수출만 한다 — keepalive/watcher 등 기존 임포트 경로를 깨지 않기 위해서다.
from navercafe_core.sessioninfo import (
    AUTH_COOKIES,
    EXPIRY_WARN_DAYS,
    VerifyResult,
    auth_expiry,
    auth_fingerprint,
    auth_token,
    days_left,
    describe as _describe,
    has_login_cookies,
    merge_expiry,
)

from .cookie_store import CookieStore, SessionRecord
from . import cafe_api

NAVER_LOGIN = "https://nid.naver.com/nidlogin.login"
NAVER_HOME = "https://www.naver.com/"

__all__ = ["SessionManager", "VerifyResult", "AUTH_COOKIES", "EXPIRY_WARN_DAYS",
           "auth_expiry", "auth_token", "days_left", "auth_fingerprint",
           "has_login_cookies", "merge_expiry"]


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
        """세션 파일 상태 판정.

        `ok`는 "쿠키를 실어서 써볼 만한가"만 뜻한다 — 만료가 지났다고 False로 내리지 않는다.
        호출부 6곳이 `verify().ok`로 쿠키 로딩 자체를 막고 있어서, 여기서 만료를 이유로
        거절하면 크롤러가 통째로 익명 모드가 된다. 실제로 네이버는 만료가 지난 쿠키도
        서버 세션이 살아 있으면 받아준다(실측). 만료는 `expiring`/`days_left`로 따로 알린다.
        """
        if not self.store.exists(account_id):
            return VerifyResult(False, "저장된 세션 없음")
        return _describe(self.store.load(account_id).cookies)

    def persist(self, account_id: str, client, *, prev: str | None = None) -> str | None:
        """네이버가 갱신한 쿠키를 세션 파일에 되쓴다.

        반환값은 저장한 지문(= 다음 호출에 `prev`로 넘기면 중복 저장을 건너뛴다).
        저장하지 않았으면 None.

        저장을 건너뛰는 경우 두 가지:
          - 쿠키자에 로그인 쿠키가 없음 → 로그아웃 상태의 쿠키로 멀쩡한 세션 파일을
            덮어쓰면 복구가 안 된다. 덮어쓰지 않는 쪽이 항상 안전하다.
          - 지문이 이전과 같음 → 네이버가 아직 안 굴렸다. 쓸 이유가 없다.
        """
        cookies = cafe_api.dump_cookies(client)
        if not has_login_cookies(cookies):
            return None
        cookies = self._merge_expiry(account_id, cookies)
        fp = auth_fingerprint(cookies)
        if prev is not None and fp == prev:
            return None
        self.store.save(account_id, cookies)
        return fp

    def _merge_expiry(self, account_id: str, cookies: list[dict]) -> list[dict]:
        """만료를 잃은 쿠키에 파일에 있던 만료를 되살려 넣는다.

        make_client()가 쿠키를 실을 때 만료를 일부러 버리기 때문에, 그 요청에 네이버가
        Set-Cookie를 안 내려주면 쿠키자에는 만료 없는 NID_AUT만 남는다. 그대로 저장하면
        멀쩡한 만료정보를 가진 파일을 만료 미상으로 덮어써서, 만료 경고가 영영 안 뜬다.
        네이버가 새 만료를 준 경우에는 그쪽이 항상 더 최신이므로 그대로 둔다.
        """
        try:
            previous = self.store.load(account_id).cookies
        except Exception:
            return cookies
        return merge_expiry(cookies, previous)
