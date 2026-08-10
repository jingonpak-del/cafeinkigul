"""원본 HTML을 DB가 아니라 불변 아카이브(zstd)에 적재한다.

Phase 0(2026-08-07) 배경: 운영 DB 920MB 중 704MB가 content_html이었다. 학습에는 정규화된
텍스트만 쓰지만, 파서를 개선했을 때 다시 뽑으려면 원본이 있어야 한다. 그래서 DB에서는 빼고
날짜별 zstd 샤드로 남긴다. 실측 압축률 약 10.5배.

프레임 단위로 주기적 flush → 프로세스가 죽어도 그 시점까지는 정상적으로 읽힌다.
쓰기 주체는 워처 스레드 하나(단일 라이터)를 전제한다.
"""
from __future__ import annotations

import datetime
import io
import json
import threading
import time
from pathlib import Path

import zstandard as zstd

from .paths import RAW_DIR

FLUSH_EVERY = 50          # N건마다 프레임 종료 → 중단 내구성
FLUSH_SECONDS = 120       # 유입이 느린 시간대에도 2분 넘게 버퍼에 묵히지 않는다
ZSTD_LEVEL = 10           # 상시 쓰기라 속도/용량 절충 (콜드 이관 시 19로 재압축)


class HtmlArchive:
    """raw/html/dt=YYYY-MM-DD/part-0001.jsonl.zst 에 append."""

    def __init__(self, root=None):
        self.root = (root or RAW_DIR) / "html"
        self._lock = threading.Lock()
        self._day: str | None = None
        self._fh = None
        self._zw = None
        self._n = 0
        self._last_flush = 0.0

    def _today(self) -> str:
        return datetime.date.today().isoformat()

    def _ensure_open(self):
        day = self._today()
        if self._day == day and self._zw is not None:
            return
        self._close()
        self._day = day
        d = self.root / f"dt={day}"
        d.mkdir(parents=True, exist_ok=True)
        # 기존 파일에 append하지 않는다. 프로세스가 강제 종료되면 마지막 프레임이 잘린 채
        # 남는데, 거기에 이어 쓰면 파일 전체가 의심스러워진다. 프로세스마다 새 샤드를 쓰면
        # 깨질 수 있는 건 그 파일의 마지막 레코드 하나뿐이다.
        i = 1
        while (d / f"part-{i:04d}.jsonl.zst").exists():
            i += 1
        path = d / f"part-{i:04d}.jsonl.zst"
        self._fh = path.open("wb")
        self._zw = zstd.ZstdCompressor(level=ZSTD_LEVEL).stream_writer(self._fh)
        self._n = 0
        self._last_flush = time.monotonic()

    def write(self, *, cafe_id: int, article_id: int, write_ts, html: str | None):
        if not html:
            return
        with self._lock:
            try:
                self._ensure_open()
                line = json.dumps({
                    "schema_v": 1,
                    "doc_id": f"nc:{cafe_id}:{article_id}",
                    "cafe_id": cafe_id,
                    "article_id": article_id,
                    "write_ts": write_ts,
                    "content_html": html,
                }, ensure_ascii=False) + "\n"
                self._zw.write(line.encode("utf-8"))
                self._n += 1
                if (self._n % FLUSH_EVERY == 0
                        or time.monotonic() - self._last_flush >= FLUSH_SECONDS):
                    self._zw.flush(zstd.FLUSH_FRAME)
                    self._fh.flush()
                    self._last_flush = time.monotonic()
            except Exception:
                # 아카이브 실패가 수집을 멈추면 안 된다. 다음 건에서 재시도된다.
                self._close()

    def _close(self):
        if self._zw is not None:
            try:
                self._zw.close()
            except Exception:
                pass
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
        self._zw = self._fh = None

    def close(self):
        with self._lock:
            self._close()


ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def _decode_frames(raw: bytes) -> bytes:
    """프레임 경계에서 재동기화하며 읽을 수 있는 것만 모은다.

    프로세스가 죽으면 그 순간의 프레임이 잘린 채 남는데, 이어붙은 스트림으로 읽으면
    그 지점에서 전체가 실패한다(실측: 26줄이 멀쩡한데 0줄로 읽혔다). 프레임 시작
    표식을 찾아 하나씩 따로 풀면 손상된 프레임만 버리고 나머지를 살릴 수 있다.
    표식이 압축 데이터 안에 우연히 나올 수도 있지만, 그런 조각은 복호화에 실패해
    자연히 걸러진다."""
    offs, i = [], 0
    while True:
        j = raw.find(ZSTD_MAGIC, i)
        if j < 0:
            break
        offs.append(j)
        i = j + 4
    out = bytearray()
    d = zstd.ZstdDecompressor()
    for k, o in enumerate(offs):
        end = offs[k + 1] if k + 1 < len(offs) else len(raw)
        try:
            out += d.stream_reader(io.BytesIO(raw[o:end]),
                                   read_across_frames=False).read()
        except zstd.ZstdError:
            continue
    return bytes(out)


def read_shard(path, *, on_truncated=None):
    """샤드를 레코드 단위로 되읽는다.

    두 가지를 감안해야 한다.
      1. 주기적 flush(FLUSH_FRAME) 때문에 한 파일에 zstd 프레임이 여러 개 들어간다.
         read_across_frames를 명시하지 않으면 버전에 따라 첫 프레임만 읽고 조용히 끝난다.
      2. 프로세스가 강제 종료되면 마지막 프레임/레코드가 잘려 있을 수 있다. 그 한 건 때문에
         샤드 전체를 못 읽으면 안 되므로, 꼬리의 불완전한 부분은 건너뛰고 나머지를 살린다.
    """
    raw = Path(path).read_bytes()
    try:
        data = zstd.ZstdDecompressor().stream_reader(
            io.BytesIO(raw), read_across_frames=True).read()
    except zstd.ZstdError:
        data = _decode_frames(raw)

    text = data.decode("utf-8", errors="ignore")
    lines = text.split("\n")
    if lines and lines[-1] != "":
        lines.pop()          # 개행으로 끝나지 않은 마지막 줄 = 쓰다 만 레코드
    for line in lines:
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            if on_truncated:
                on_truncated(path, line)


_archive: HtmlArchive | None = None


def get() -> HtmlArchive:
    global _archive
    if _archive is None:
        _archive = HtmlArchive()
    return _archive
