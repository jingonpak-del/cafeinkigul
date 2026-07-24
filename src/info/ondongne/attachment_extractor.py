from __future__ import annotations

import io
import re
import zlib
from dataclasses import dataclass
from urllib.parse import urlparse, unquote
from urllib.request import Request, urlopen


MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


@dataclass
class AttachmentExtraction:
    url: str
    filename: str
    text: str = ""
    method: str = "none"
    error: str = ""


def filename_from_url(url: str) -> str:
    path = unquote(urlparse(url).path or "")
    name = path.rsplit("/", 1)[-1]
    return name or url


def fetch_attachment_bytes(url: str, timeout: int = 20, max_bytes: int = MAX_ATTACHMENT_BYTES) -> bytes:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 OndongneBot/0.2"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read(max_bytes + 1)[:max_bytes]


def extract_pdf_text(data: bytes, max_pages: int = 3) -> str:
    try:
        import fitz  # PyMuPDF
    except Exception:
        return ""
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        chunks: list[str] = []
        for page in doc[:max_pages]:
            chunks.append(page.get_text("text"))
        return _clean_text("\n".join(chunks))
    except Exception:
        return ""


def extract_hwp_text(data: bytes) -> str:
    """Best-effort HWP v5 text extraction from OLE BodyText streams.

    This handles many Korean public-sector .hwp attachments without external
    converters. If the file is encrypted, too new, or non-OLE, it returns ''.
    """
    try:
        import olefile
    except Exception:
        return ""
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception:
        return ""
    if not ole.exists("FileHeader"):
        return ""
    try:
        header = ole.openstream("FileHeader").read()
        compressed = bool(header[36] & 0x01) if len(header) > 36 else False
        texts: list[str] = []
        body_streams = sorted(
            "/".join(path) for path in ole.listdir()
            if len(path) == 2 and path[0] == "BodyText" and path[1].startswith("Section")
        )
        for stream_name in body_streams[:5]:
            raw = ole.openstream(stream_name).read()
            if compressed:
                try:
                    raw = zlib.decompress(raw, -15)
                except zlib.error:
                    continue
            texts.append(_decode_hwp_records(raw))
        return _clean_text("\n".join(texts))
    except Exception:
        return ""


def _decode_hwp_records(section: bytes) -> str:
    out: list[str] = []
    pos = 0
    while pos + 4 <= len(section):
        header = int.from_bytes(section[pos:pos + 4], "little")
        tag_id = header & 0x3ff
        size = (header >> 20) & 0xfff
        pos += 4
        if size == 0xfff:
            if pos + 4 > len(section):
                break
            size = int.from_bytes(section[pos:pos + 4], "little")
            pos += 4
        payload = section[pos:pos + size]
        pos += size
        # HWPTAG_PARA_TEXT = 67
        if tag_id == 67 and payload:
            try:
                out.append(payload.decode("utf-16le", errors="ignore"))
            except Exception:
                pass
    return "\n".join(out)


def extract_image_ocr_text(data: bytes) -> str:
    """Optional local OCR. Returns '' when pytesseract/Pillow/tesseract is absent."""
    try:
        from PIL import Image
        import pytesseract
    except Exception:
        return ""
    try:
        return _clean_text(pytesseract.image_to_string(Image.open(io.BytesIO(data)), lang="kor+eng"))
    except Exception:
        return ""


def extract_attachment_text(url: str, data: bytes | None = None) -> AttachmentExtraction:
    filename = filename_from_url(url)
    lower = filename.lower()
    try:
        blob = data if data is not None else fetch_attachment_bytes(url)
    except Exception as exc:
        return AttachmentExtraction(url=url, filename=filename, error=str(exc))

    text = ""
    method = "none"
    if lower.endswith(".pdf") or blob.startswith(b"%PDF"):
        text = extract_pdf_text(blob)
        method = "pdf-pymupdf" if text else "pdf-empty"
    elif lower.endswith((".hwp", ".hwpx")) or b"HWP Document File" in blob[:512]:
        text = extract_hwp_text(blob)
        method = "hwp-ole" if text else "hwp-empty"
    elif lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        text = extract_image_ocr_text(blob)
        method = "image-ocr" if text else "image-ocr-unavailable"
    return AttachmentExtraction(url=url, filename=filename, text=text, method=method)


def extract_many_attachment_texts(
    urls: list[str], *, max_files: int = 2, fetcher=None
) -> list[AttachmentExtraction]:
    results: list[AttachmentExtraction] = []
    for url in urls[:max_files]:
        if fetcher:
            try:
                data = fetcher(url)
            except Exception as exc:
                results.append(AttachmentExtraction(url=url, filename=filename_from_url(url), error=str(exc)))
                continue
            results.append(extract_attachment_text(url, data))
        else:
            results.append(extract_attachment_text(url))
    return results


def append_attachment_text(body_text: str, extracted: list[AttachmentExtraction], max_chars: int = 1600) -> str:
    chunks = [body_text.strip()] if body_text.strip() else []
    for item in extracted:
        if item.text:
            chunks.append(f"[첨부추출:{item.filename}]\n{item.text[:max_chars]}")
        elif item.filename:
            chunks.append(f"[첨부파일:{item.filename}]")
    return _clean_text("\n".join(chunks))


def _clean_text(text: str) -> str:
    text = re.sub(r"\x00", "", text or "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
