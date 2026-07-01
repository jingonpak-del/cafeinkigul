"""Google Sheets 적재 (서비스계정).

쿼터 보호를 위해 행을 버퍼에 모아 batch append 한다. 시트 2개:
  - '글'   : 감지/메타/조회수 변동/본문
  - '댓글' : 글별 댓글 (first/revisit 단계 포함)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ARTICLE_HEADER = [
    "감지시각", "카페", "감지보드", "메뉴ID", "articleId", "제목", "작성자",
    "URL", "작성시각", "최초조회", "최초댓글", "추천",
    "4h후조회", "조회증가", "4h후댓글", "본문",
]
COMMENT_HEADER = [
    "articleId", "글제목", "댓글ID", "작성자", "내용", "작성시각", "답글", "단계",
]


def _ts(ms: int | None) -> str:
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


class SheetsSink:
    def __init__(self, credentials_path: str, spreadsheet_id: str | None = None,
                 share_with: str | None = None, title: str = "인기글 트래커"):
        creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
        self.gc = gspread.authorize(creds)
        if spreadsheet_id:
            self.sh = self.gc.open_by_key(spreadsheet_id)
        else:
            self.sh = self.gc.create(title)
            if share_with:
                self.sh.share(share_with, perm_type="user", role="writer")
        self.spreadsheet_id = self.sh.id
        self.url = f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}"
        self.ws_article = self._ensure_ws("글", ARTICLE_HEADER)
        self.ws_comment = self._ensure_ws("댓글", COMMENT_HEADER)

    def _ensure_ws(self, name: str, header: list[str]):
        try:
            ws = self.sh.worksheet(name)
        except gspread.WorksheetNotFound:
            ws = self.sh.add_worksheet(title=name, rows=1000, cols=len(header))
            ws.append_row(header, value_input_option="RAW")
        # 기본 Sheet1 정리
        try:
            self.sh.del_worksheet(self.sh.worksheet("Sheet1"))
        except Exception:
            pass
        return ws

    # --- 행 변환 -------------------------------------------------------------
    @staticmethod
    def article_row(meta: dict) -> list:
        return [
            _ts(meta.get("first_seen_at")), meta.get("cluburl", ""), meta.get("board_key", ""),
            meta.get("menu_id", ""), meta.get("article_id", ""), meta.get("title", ""),
            meta.get("writer_nickname", ""), meta.get("url", ""), _ts(meta.get("write_ts")),
            meta.get("first_read_count", ""), meta.get("first_comment_count", ""),
            meta.get("like_count", ""), meta.get("second_read_count", ""),
            meta.get("read_delta", ""), meta.get("second_comment_count", ""),
            (meta.get("content_text", "") or "")[:5000],
        ]

    @staticmethod
    def comment_rows(article_id, title, comments, phase) -> list[list]:
        return [[article_id, title, c.comment_id, c.writer_nickname, c.content,
                 _ts(c.update_ts), "Y" if c.is_reply else "", phase] for c in comments]

    # --- 적재 (batch) --------------------------------------------------------
    def append_articles(self, rows: list[list]):
        if rows:
            self.ws_article.append_rows(rows, value_input_option="RAW")

    def append_comments(self, rows: list[list]):
        if rows:
            self.ws_comment.append_rows(rows, value_input_option="RAW")
