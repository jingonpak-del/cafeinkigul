"""
네이버 카페 게시글 작성 시 네트워크 요청 캡처 도구
- Playwright로 실제 브라우저를 띄움
- 직접 로그인하고 게시글 작성
- POST 요청을 자동으로 캡처해서 JSON 파일로 저장
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, Request, Response


OUTPUT_DIR = Path(__file__).parent / "captured_requests"
OUTPUT_DIR.mkdir(exist_ok=True)

# 캡처할 도메인 필터 (None이면 전체)
TARGET_DOMAINS = [
    "cafe.naver.com",
    "apis.naver.com",
    "cafes.apis.naver.com",
    "dn.cafe.naver.com",
]

captured: list[dict] = []


def is_target_request(url: str) -> bool:
    return any(domain in url for domain in TARGET_DOMAINS)


async def capture_request(request: Request):
    if not is_target_request(request.url):
        return
    if request.method not in ("POST", "PUT", "PATCH"):
        return

    entry = {
        "time": datetime.now().isoformat(),
        "method": request.method,
        "url": request.url,
        "headers": dict(request.headers),
        "post_data": None,
        "post_data_json": None,
        "resource_type": request.resource_type,
    }

    try:
        raw = request.post_data
        if raw:
            entry["post_data"] = raw
            try:
                entry["post_data_json"] = json.loads(raw)
            except Exception:
                pass
    except Exception:
        pass

    captured.append(entry)
    print(f"\n[REQUEST #{len(captured)}] {request.method} {request.url}")
    print(f"  Content-Type: {request.headers.get('content-type', '-')}")
    if entry["post_data"]:
        preview = entry["post_data"][:300]
        print(f"  Body: {preview}{'...' if len(entry['post_data']) > 300 else ''}")


async def capture_response(response: Response):
    if not is_target_request(response.url):
        return
    if response.request.method not in ("POST", "PUT", "PATCH"):
        return

    # 이미 캡처된 요청에 응답 붙이기
    matching = [e for e in captured if e["url"] == response.url]
    if not matching:
        return

    entry = matching[-1]
    entry["response_status"] = response.status
    entry["response_headers"] = dict(response.headers)

    try:
        body = await response.body()
        text = body.decode("utf-8", errors="replace")
        entry["response_body"] = text[:2000]
        try:
            entry["response_json"] = json.loads(text)
        except Exception:
            pass
    except Exception:
        pass

    print(f"  → 응답: {response.status} ({response.headers.get('content-type', '-')})")


async def main():
    print("=" * 60)
    print("네이버 카페 네트워크 캡처 도구")
    print("=" * 60)
    print()
    print("브라우저가 열리면:")
    print("  1. 네이버 로그인")
    print("  2. 원하는 카페로 이동")
    print("  3. 게시글 작성 후 제출")
    print()
    print("제출 완료 후 이 터미널에서 Enter를 눌러 저장하세요.")
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized"],
        )

        context = await browser.new_context(
            viewport=None,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )

        page = await context.new_page()
        page.on("request", capture_request)
        page.on("response", capture_response)

        await page.goto("https://nid.naver.com/nidlogin.login")

        print("브라우저에서 직접 로그인 후 게시글을 작성하세요.")
        print("완료되면 Enter를 눌러주세요...")

        await asyncio.get_event_loop().run_in_executor(None, input)

        await browser.close()

    # 결과 저장
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"capture_{timestamp}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(captured, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"캡처 완료: {len(captured)}개 요청")
    print(f"저장 위치: {out_path}")
    print()

    # 요약 출력
    print("[캡처된 요청 요약]")
    for i, entry in enumerate(captured, 1):
        print(f"  {i}. {entry['method']} {entry['url']}")
        if "response_status" in entry:
            print(f"     응답: {entry['response_status']}")
        ct = entry["headers"].get("content-type", "")
        if ct:
            print(f"     Content-Type: {ct}")


if __name__ == "__main__":
    asyncio.run(main())
