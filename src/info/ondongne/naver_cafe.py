from __future__ import annotations

from collections import defaultdict
from datetime import datetime


def make_daily_post(events, region_name: str = "창원") -> tuple[str, str]:
    today = datetime.now().strftime("%Y.%m.%d")
    title = f"[{region_name}온동네] {today} 신규 공공 행사·교육·모집 소식 {len(events)}건"

    grouped = defaultdict(list)
    for e in events:
        grouped[e.category].append(e)

    lines: list[str] = []
    lines.append(f"안녕하세요. {region_name} 지역 공공기관에서 새로 확인된 행사·교육·모집 정보를 모았습니다.")
    lines.append("")
    lines.append("※ 자동 수집 기반 초안입니다. 일정/접수상태는 변경될 수 있으니 신청 전 반드시 원문을 확인해 주세요.")
    lines.append("")
    lines.append(f"■ 오늘 신규 업데이트: {len(events)}건")
    lines.append("")

    for category in sorted(grouped.keys()):
        lines.append(f"## {category}")
        for idx, e in enumerate(grouped[category], 1):
            date_text = e.event_start_date or e.application_end_date or "일정 원문 확인"
            price = e.price_type or "미확인"
            lines.append(f"{idx}. [{e.organization_name}] {e.title}")
            if getattr(e, "summary", ""):
                lines.append(f"   - 요약: {e.summary}")
            if e.application_start_date or e.application_end_date:
                lines.append(f"   - 접수: {e.application_start_date or '확인 필요'} ~ {e.application_end_date or '확인 필요'}")
            if e.event_start_date or e.event_end_date:
                lines.append(f"   - 일정: {e.event_start_date or '확인 필요'} ~ {e.event_end_date or '확인 필요'}")
            lines.append(f"   - 대상: {e.target_audience}")
            if getattr(e, "location_name", ""):
                lines.append(f"   - 장소: {e.location_name}")
            lines.append(f"   - 비용: {price}")
            lines.append(f"   - 원문/신청: {e.apply_url or e.source_url}")
            lines.append("")

    lines.append("---")
    lines.append("이 글은 지역 공공정보 큐레이션 서비스 ‘온동네’의 게시글 초안입니다.")
    lines.append("누락/오류가 있으면 댓글로 알려주세요.")
    return title, "\n".join(lines)
