"""Naver Cafe list-fetch client.

Verified endpoint (works for public boards without auth; member-only boards and
the popular board require a logged-in session's cookies):

    GET https://apis.naver.com/cafe-web/cafe2/ArticleListV2.json
        ?search.clubid={clubId}
        &search.queryType=lastArticle
        &search.menuid={menuId}      # 0 = whole cafe
        &search.page={page}
        &search.perPage={n}
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from typing import Any

import httpx
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
ARTICLE_LIST_URL = "https://apis.naver.com/cafe-web/cafe2/ArticleListV2.json"
# Popular ("인기글") board — different endpoint and slightly different schema.
POPULAR_LIST_URL = "https://apis.naver.com/cafe-web/cafe2/WeeklyPopularArticleListV3.json"
# Article body + comments live on a different gateway host (article.cafe.naver.com/gw).
ARTICLE_GW = "https://article.cafe.naver.com/gw"
GW_HEADERS = {"Referer": "https://cafe.naver.com/", "Origin": "https://cafe.naver.com"}


@dataclass(frozen=True)
class ArticleSummary:
    cafe_id: int
    menu_id: int
    menu_name: str
    article_id: int
    title: str
    writer_nickname: str
    member_key: str
    read_count: int
    comment_count: int
    like_count: int
    write_ts: int            # ms epoch
    last_comment_ts: int     # ms epoch
    is_popular: bool
    is_notice: bool          # newArticle/notice heuristics
    blinded: bool
    has_image: bool

    @property
    def url(self) -> str:
        return f"https://cafe.naver.com/ca-fe/cafes/{self.cafe_id}/articles/{self.article_id}"

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d["url"] = self.url
        return d


@dataclass(frozen=True)
class ArticleBody:
    cafe_id: int
    article_id: int
    menu_id: int
    title: str
    writer_nickname: str
    member_key: str
    write_ts: int
    read_count: int
    comment_count: int
    is_notice: bool
    content_html: str
    content_text: str


@dataclass(frozen=True)
class Comment:
    comment_id: int
    ref_id: int            # parent comment id (for replies)
    writer_nickname: str
    member_key: str
    content: str
    update_ts: int
    is_reply: bool
    is_deleted: bool
    is_article_writer: bool
    is_best: bool


def make_client(cookies: list[dict[str, Any]] | None = None) -> httpx.Client:
    """Build an httpx client. Pass cookie dicts (from CookieStore) to authenticate."""
    jar = httpx.Cookies()
    for c in cookies or []:
        try:
            jar.set(c["name"], c["value"], domain=c.get("domain", ".naver.com"), path=c.get("path", "/"))
        except Exception:
            continue
    return httpx.Client(
        headers={"User-Agent": UA, "Accept": "application/json, text/plain, */*"},
        cookies=jar, timeout=12.0, follow_redirects=True,
    )


def resolve_club_id(cluburl: str, client: httpx.Client | None = None) -> int:
    """Resolve a cafe vanity url (e.g. 'memberupup3') to its numeric clubId."""
    own = client is None
    client = client or make_client()
    try:
        r = client.get(f"https://cafe.naver.com/{cluburl}", headers={"Referer": "https://cafe.naver.com/"})
        for pat in (r"clubid\D{0,4}(\d{4,})", r"cafeId\D{0,4}(\d{4,})", r"g_sClubId\D{0,4}(\d{4,})"):
            m = re.search(pat, r.text, re.I)
            if m:
                return int(m.group(1))
        raise RuntimeError(f"could not resolve clubId for '{cluburl}'")
    finally:
        if own:
            client.close()


def fetch_article_list(
    club_id: int, menu_id: int = 0, per_page: int = 30, page: int = 1,
    client: httpx.Client | None = None,
) -> list[ArticleSummary]:
    """Fetch the latest articles of a board. menu_id=0 spans the whole cafe."""
    own = client is None
    client = client or make_client()
    try:
        params = {
            "search.clubid": club_id,
            "search.queryType": "lastArticle",
            "search.menuid": menu_id,
            "search.page": page,
            "search.perPage": per_page,
        }
        r = client.get(ARTICLE_LIST_URL, params=params,
                       headers={"Referer": f"https://cafe.naver.com/{club_id}"})
        body = r.json()
        msg = body.get("message", {})
        status = str(msg.get("status"))
        if status != "200":
            err = msg.get("error", {})
            raise RuntimeError(
                f"목록 조회 실패 (status={status}, code={err.get('code')}, msg={err.get('msg')}).\n"
                f"  원인 후보: ① menuId({menu_id})가 이 카페에 없음  "
                f"② 회원전용 보드인데 이 계정이 카페 회원이 아님  "
                f"③ menuId=0(전체)은 이 API에서 미지원\n"
                f"  → 브라우저에서 해당 보드 클릭 후 URL의 'menus/번호' 또는 'menuid=번호'를 확인하세요."
            )
        result = msg.get("result", {})
        return [_to_summary(a) for a in result.get("articleList", [])]
    finally:
        if own:
            client.close()


def fetch_popular_list(
    club_id: int, per_page: int = 30, client: httpx.Client | None = None,
) -> list[ArticleSummary]:
    """Fetch the cafe's popular ('인기글') board. Separate endpoint/schema from
    a regular menu; requires a logged-in session for member-only cafes."""
    own = client is None
    client = client or make_client()
    try:
        r = client.get(
            POPULAR_LIST_URL,
            params={"cafeId": club_id, "mobileWeb": "true", "adUnit": "PC_CAFE_BOARD", "ad": "false"},
            headers={"Referer": f"https://cafe.naver.com/f-e/cafes/{club_id}/popular"},
        )
        msg = r.json().get("message", {})
        if str(msg.get("status")) != "200":
            err = msg.get("error", {})
            raise RuntimeError(f"인기글 조회 실패 (code={err.get('code')}, msg={err.get('msg')})")
        arts = msg.get("result", {}).get("articleList", [])
        return [_to_summary(a, popular=True) for a in arts][:per_page]
    finally:
        if own:
            client.close()


def _to_summary(a: dict[str, Any], popular: bool = False) -> ArticleSummary:
    # Tolerant of both schemas: ArticleListV2 (writerNickname/likeItCount/...)
    # and WeeklyPopularArticleListV3 (nickname/upCount/lastCommentDateTimestamp).
    return ArticleSummary(
        cafe_id=a.get("cafeId", 0),
        menu_id=a.get("menuId", 0),
        menu_name=a.get("menuName", ""),
        article_id=a.get("articleId", 0),
        title=a.get("subject", ""),
        writer_nickname=a.get("writerNickname") or a.get("nickname", ""),
        member_key=a.get("memberKey", ""),
        read_count=a.get("readCount", 0),
        comment_count=a.get("commentCount", 0),
        like_count=a.get("likeItCount", a.get("upCount", 0)),
        write_ts=a.get("writeDateTimestamp", 0),
        last_comment_ts=a.get("lastCommentedTimestamp") or a.get("lastCommentDateTimestamp", 0),
        is_popular=bool(a.get("popular", popular)),
        is_notice=bool(a.get("noticeArticle", False)),
        blinded=bool(a.get("blindArticle", False)),
        has_image=bool(a.get("attachImage") or a.get("imageCount", 0)),
    )


def fetch_article_body(
    club_id: int, article_id: int, menu_id: int = 0, client: httpx.Client | None = None,
) -> ArticleBody:
    """Fetch a single article's full body via the article gateway."""
    own = client is None
    client = client or make_client()
    try:
        url = f"{ARTICLE_GW}/v4/cafes/{club_id}/articles/{article_id}"
        params = {"query": "", "menuId": menu_id, "boardType": "L",
                  "useCafeId": "true", "requestFrom": "A"}
        r = client.get(url, params=params, headers=GW_HEADERS)
        art = r.json().get("result", {}).get("article", {})
        if not art:
            raise RuntimeError(f"본문 조회 실패 (article {article_id}, status={r.status_code})")
        html = art.get("contentHtml", "") or ""
        return ArticleBody(
            cafe_id=club_id,
            article_id=art.get("id", article_id),
            menu_id=(art.get("menu") or {}).get("id", menu_id),
            title=art.get("subject", ""),
            writer_nickname=(art.get("writer") or {}).get("nick", ""),
            member_key=(art.get("writer") or {}).get("memberKey", ""),
            write_ts=art.get("writeDate", 0),
            read_count=art.get("readCount", 0),
            comment_count=art.get("commentCount", 0),
            is_notice=bool(art.get("isNotice", False)),
            content_html=html,
            content_text=html_to_text(html),
        )
    finally:
        if own:
            client.close()


def fetch_comments(
    club_id: int, article_id: int, client: httpx.Client | None = None, max_pages: int = 20,
) -> list[Comment]:
    """Fetch all comments of an article, following pagination."""
    own = client is None
    client = client or make_client()
    out: list[Comment] = []
    seen: set[int] = set()
    try:
        for page in range(1, max_pages + 1):
            url = f"{ARTICLE_GW}/v4/cafes/{club_id}/articles/{article_id}/comments/pages/{page}"
            r = client.get(url, params={"requestFrom": "A", "orderBy": "asc"}, headers=GW_HEADERS)
            comments = r.json().get("result", {}).get("comments", {})
            items = comments.get("items", []) if isinstance(comments, dict) else []
            # This endpoint clamps out-of-range pages to the last page (returns
            # duplicates), so stop once a page yields no new comment ids.
            new = [c for c in items if c.get("id") not in seen]
            if not new:
                break
            for c in new:
                w = c.get("writer") or {}
                seen.add(c.get("id", 0))
                out.append(Comment(
                    comment_id=c.get("id", 0),
                    ref_id=c.get("refId", 0),
                    writer_nickname=w.get("nick", ""),
                    member_key=w.get("memberKey", ""),
                    content=c.get("content", "") or "",
                    update_ts=c.get("updateDate", 0),
                    is_reply=c.get("id") != c.get("refId"),
                    is_deleted=bool(c.get("isDeleted", False)),
                    is_article_writer=bool(c.get("isArticleWriter", False)),
                    is_best=bool(c.get("bestComment", False)),
                ))
        return out
    finally:
        if own:
            client.close()


def html_to_text(html: str) -> str:
    """Strip Naver SmartEditor HTML to readable plain text."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)
