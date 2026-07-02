# 인기글 트래커 (Naver Cafe Ingigeul Tracker)

등록된 여러 네이버 카페 게시판(인기글 보드 포함)의 새 글을 실시간 추적 → 본문·댓글 크롤 →
구글시트 적재하고, 최초 감지 후 4시간 뒤 재방문해 **조회수 변동폭**을 기록하는 프로그램.

> 읽기 전용 모니터링 도구입니다. 댓글 자동작성·캡챠 우회·IP 로테이션 같은 기능은 포함하지 않습니다.

## 현재 상태: PoC 검증 완료 ✅

감지 → 본문/댓글 크롤 → DB 적재 → 4h 재방문(조회수 델타) 파이프라인이 실제 카페(masanmam)에서
end-to-end 동작 확인됨. 자세한 검증 내역은 [POC_RESULTS.md](POC_RESULTS.md).

## 아키텍처 (목표)

중앙 서버 1대(상시 PC/클라우드)가 크롤링·DB·시트를 전담하고, 사용자는 브라우저로 대시보드 접속.

```
Watcher(감지·라운드로빈) → Queue → Crawl Worker(본문·댓글) → DB / Google Sheets
                                  ↘ Revisit Scheduler(4h 조회수 변동)
세션 매니저(단일 계정 쿠키)  ·  FastAPI(REST+WebSocket) → 웹 대시보드
```

- **배포**: 중앙 서버 + 웹 대시보드 / **계정**: 단일 공용 / **규모**: ~50개 보드
- **감지 분리**: 무거운 브라우저가 아니라 가벼운 인증 HTTP로 폴링 (검증됨)

## 검증된 엔드포인트

| 용도 | 엔드포인트 |
|---|---|
| clubId 해석 | `cafe.naver.com/{cluburl}` HTML 파싱 |
| 일반 보드 목록 | `apis.naver.com/cafe-web/cafe2/ArticleListV2.json` (menuid별) |
| 인기글 보드 | `apis.naver.com/cafe-web/cafe2/WeeklyPopularArticleListV3.json` |
| 본문 | `article.cafe.naver.com/gw/v4/cafes/{id}/articles/{aid}` |
| 댓글 | `article.cafe.naver.com/gw/v4/cafes/{id}/articles/{aid}/comments/pages/{n}` |

## 설치 & 실행

```powershell
python -m pip install -r requirements.txt

# 1) 로그인 1회 (브라우저 떠서 직접 로그인 → 터미널 Enter)
python -m src.poc.cli capture --account 내네이버아이디

# 2) 설정 보드 1회 조회
python -m src.poc.cli track

# 3) 전체 보드 폴링+크롤 → DB 적재 (1회)
python -m src.poc.cli sweep

# 4) 실시간 라운드로빈 폴링 (계속)
python -m src.poc.cli watch --tick 1 --gap 1

# DB 현황
python -m src.poc.cli stats

# 5) 웹 대시보드 (워처 포함) — 브라우저로 실시간 보기
python -m src.poc.server
#   → http://localhost:8000  접속
#   → 같은 네트워크의 다른 PC는 http://<서버IP>:8000
```

## 웹 대시보드

`python -m src.poc.server` 실행 시:
- 중앙 서버가 Watcher를 백그라운드로 구동하며 감지·크롤·시트적재 수행
- 브라우저로 접속하면 **WebSocket 실시간 피드**(새 글 뜨면 즉시 표시 + 토스트),
  글 목록(보드/검색 필터), 클릭 시 **본문·댓글 상세**를 볼 수 있음
- 여러 사람이 각자 PC 브라우저로 동시 접속 가능 (설치 불필요)
- 옵션: `--no-watch`(뷰어만), `--port 9000`, `--host 0.0.0.0`

추적 대상은 [config/targets.json](config/targets.json)에서 설정.

## 구조

```
src/poc/
  cafe_api.py    # clubId 해석 + 목록/본문/댓글 조회 + 정규화 (검증됨)
  session.py     # 수동 로그인 → 쿠키 캡처 → 검증 (캡챠 우회 없음)
  cookie_store.py / dpapi.py   # DPAPI 암호화 세션 저장
  db.py          # SQLite 스키마 (전역 중복방지 + 재방문 + 댓글)
  watcher.py     # 라운드로빈 폴링 + 신규감지 + 크롤 + 4h 재방문
  cli.py         # resolve/fetch/track/sweep/watch/stats
config/targets.json   # 추적 카페·보드 설정
```

## 다음 단계
- 구글시트 적재(배치) 연결
- asyncio 큐 + Crawl Worker 분리, Postgres 이관
- FastAPI + WebSocket 대시보드
- 레이트리밋/백오프/세션 자동검증 하드닝, ~50보드 스케일업
