"""핫딜 원고작성 스튜디오 — 수집 데이터에서 글감을 뽑고 테스트하는 도구.

LLM 없이 먼저 검증할 수 있는 것부터 담는다:
  - extract_material : 저장된 content_html에서 외부링크·이미지 URL 추출(재크롤 불필요)
  - unfurl          : 링크 리다이렉트 끝까지 추적 → 최종 URL·도메인·OG메타·가격·생사 판정
  - drafts          : 작업대에서 만든 초안 저장/조회 (drafts 테이블)

세 가지 아이디어(링크해제/이미지관리/LLM재구성)를 실제 데이터로 눌러보며
어떤 방법이 쓸 만한지 고르기 위한 실험용 백엔드다. 방식이 정해지면 워처/발행
파이프라인에 정식 편입한다.
"""
from __future__ import annotations

import re
import sqlite3
import time
from urllib.parse import urlsplit

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 딜이 죽었는지(품절/종료) 페이지 텍스트로 판정하는 신호어.
_DEAD_SIGNALS = ("품절", "일시품절", "판매종료", "판매 종료", "판매중지", "sold out",
                 "품절되었", "재고가 없", "구매할 수 없")
_PRICE_RE = re.compile(r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,7})\s*원")


def _dedup(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def extract_material(content_html: str | None, content_text: str | None) -> dict:
    """본문 HTML에서 외부 링크와 이미지 URL을 뽑는다. HTML 없으면 텍스트에서 URL만."""
    links: list[dict] = []
    images: list[str] = []
    if content_html:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content_html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if href.startswith("http"):
                links.append({"url": href, "text": a.get_text(" ", strip=True)[:80]})
        for img in soup.find_all("img"):
            src = (img.get("src") or img.get("data-src") or img.get("data-lazy-src") or "").strip()
            if src.startswith("http"):
                images.append(src)
    # HTML에 앵커가 없어도 본문 텍스트에 노출된 raw URL을 잡는다(네이버는 종종 텍스트로 붙음).
    if content_text:
        for m in re.findall(r"https?://[^\s\"'<>）)]+", content_text):
            if not any(l["url"] == m for l in links):
                links.append({"url": m, "text": ""})

    seen, ulinks = set(), []
    for l in links:
        if l["url"] not in seen:
            seen.add(l["url"])
            ulinks.append(l)
    return {"links": ulinks, "images": _dedup(images)}


def unfurl(url: str) -> dict:
    """링크를 리다이렉트 끝까지 따라가 최종 목적지와 메타·생사를 판정한다.
    사람이 일일이 클릭해 확인하던 걸 대신한다. 실패해도 예외 대신 status로 표시."""
    out: dict = {"input": url, "status": "error"}
    try:
        with httpx.Client(follow_redirects=True, timeout=12,
                          headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"}) as c:
            r = c.get(url)
        final = str(r.url)
        out["final_url"] = final
        out["domain"] = urlsplit(final).netloc
        out["status_code"] = r.status_code
        html = r.text or ""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        def meta(*keys) -> str:
            for k in keys:
                m = soup.find("meta", property=k) or soup.find("meta", attrs={"name": k})
                if m and m.get("content"):
                    return m["content"].strip()
            return ""

        title = meta("og:title", "twitter:title")
        if not title and soup.title and soup.title.string:
            title = soup.title.string.strip()
        out["title"] = title[:200]
        out["image"] = meta("og:image", "twitter:image")
        out["desc"] = meta("og:description", "description")[:300]
        out["price"] = (meta("product:price:amount", "og:price:amount")
                        or (lambda m: m.group(0) if m else "")(_PRICE_RE.search(html)))

        text_l = soup.get_text(" ", strip=True).lower()
        dead = (r.status_code >= 400
                or any(s in text_l for s in (x.lower() for x in _DEAD_SIGNALS)))
        out["status"] = "dead" if dead else "alive"
    except Exception as e:  # 네트워크/파싱 실패는 도구 특성상 흔함 → status로만 표시
        out["error"] = str(e)[:200]
    return out


# ── 초안(글감) 저장 ─────────────────────────────────────────────────────────
def ensure_tables(db_path) -> None:
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS drafts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            cafe_id     INTEGER,
            article_id  INTEGER,
            title       TEXT,
            body        TEXT,
            meta        TEXT,          -- JSON: 소스링크/해제결과/사용모델 등 실험 메모
            created_at  INTEGER,
            updated_at  INTEGER
        )""")
        conn.commit()
    finally:
        conn.close()


def save_draft(db_path, d: dict) -> int:
    ensure_tables(db_path)
    now = int(time.time() * 1000)
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        did = d.get("id")
        if did:
            conn.execute("""UPDATE drafts SET title=?, body=?, meta=?, updated_at=?
                            WHERE id=?""",
                         (d.get("title", ""), d.get("body", ""), d.get("meta", ""), now, did))
        else:
            cur = conn.execute("""INSERT INTO drafts
                (cafe_id, article_id, title, body, meta, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?)""",
                (d.get("cafe_id"), d.get("article_id"), d.get("title", ""),
                 d.get("body", ""), d.get("meta", ""), now, now))
            did = cur.lastrowid
        conn.commit()
        return int(did)
    finally:
        conn.close()


def list_drafts(db_path, limit: int = 100) -> list[dict]:
    ensure_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""SELECT id, cafe_id, article_id, title,
                                      substr(body,1,120) AS preview, updated_at
                               FROM drafts ORDER BY updated_at DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_draft(db_path, did: int) -> dict | None:
    ensure_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute("SELECT * FROM drafts WHERE id=?", (did,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def delete_draft(db_path, did: int) -> None:
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.execute("DELETE FROM drafts WHERE id=?", (did,))
        conn.commit()
    finally:
        conn.close()
