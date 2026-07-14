# 인기글 트래커 — 작업 진행 현황

> 네이버 카페 인기글/게시판 실시간 추적·크롤링·분류 시스템
> Repo: https://github.com/jingonpak-del/cafeinkigul (main)
> 최종 갱신: 2026-07-14

---

## ✅ 완료된 작업

### 코어 크롤링·저장
- **실시간 새글 탐지**: 워처(단일 스레드 라운드로빈 폴링)가 등록된 게시판을 순회하며 새글 감지
- **본문·댓글 크롤링**: 감지 즉시 본문 + 댓글 수집 → SQLite(WAL) 저장(`data/tracker.db`)
- **4시간 후 재방문**: 조회수 증가(delta) 측정으로 반응 좋은 글 판별
- **인기글 수집**: 매일 2시·16시 WeeklyPopular API로 인기글 누적
- **급상승/호응 점수**: 게시판별 평균+2σ 이상치 = 급상승, 카페별 백분위 속도 정규화 = 호응점수

### 대시보드 (웹 UI)
- 2패널 레이아웃(좌=일반글, 우=인기글), 모바일 카드 뷰 + 탭 전환
- 열 너비 드래그 조절(localStorage 저장, 서버 부하 0), 제목 2줄 표시
- 최신순/급상승/호응순 탭, 제목 검색, 미사용만 보기 필터
- WebSocket 실시간 연결, 원고 복사 + 사용 체크(중복 사용 방지)
- **카테고리 상단 탭 필터**(전체 + 분류별): 일반글은 분류로, 인기글은 별도 컬럼으로 표시

### 분류(카테고리) 시스템
- **보드 기반 분류**: 각 게시판에 `category` 지정 → 그 게시판에서 감지된 글이 자동 분류(내용분석 대비 100% 정확)
- 동적 분류: 핫딜 · 앱체크 · 유머 · 일반인기글 (UI로 추가/삭제 가능)

### ⚙️ 설정 화면 (master 전용) — **직전 완료**
- `body.ismaster` 토글로 master 로그인 시에만 노출
- **분류 관리**: 칩 추가/삭제 → `POST /api/admin/categories`, 대시보드 탭 즉시 갱신
- **카페 게시판 등록**: 카페 주소 입력 → `GET /api/admin/cafe-boards`로 게시판 자동 추출
  (메뉴ID·이름) → 수집 체크 + 분류 드롭다운 + 인기글 체크 → `POST /api/admin/save-cafe`
  → 워처 핫리로드로 재시작 없이 자동 반영
- **등록된 카페 목록**: 클릭 시 편집기에 로드, 게시판 검색 필터
- 커밋: `1ad8dd0`

### 인프라·안정화
- **Cloudflare 명명 터널**: dashboard.whitedr.com 로 사내/집 공유
- **폼+쿠키 로그인**: 카카오톡 인앱브라우저의 Basic Auth 팝업 불가 문제 해결
- **다중 계정/권한**: master + 그룹별 계정(접속현황 확인)
- **supervisor.ps1**: 4개 서비스 감시 실행, 대시보드(8090)는 `noreload=$true`
- **워처 크래시 수정**: uvicorn 기동 시 `_force_utf8()`를 startup 이벤트에서 호출(cp949 인코딩 크래시 해결)
- **인기글 수집이 일반 폴링 차단하던 버그** 수정(수집 시작 시점에 last_popular_run 설정)

---

## 🔧 진행 중인 작업

- 없음 (직전 요청이던 설정 화면 Phase 4 완료)

---

## ⏭ 다음 할 일

1. **미분류 게시판 분류 채우기** — 설정 화면에서 카페별로 [불러오기 → 분류 지정 → 저장].
   아직 분류 없는 카페: 맘이베베, 핫딜언니, 몰테일, 페밀리세일, 맘스홀릭, 레몬테라스,
   천안줌마·부경맘(정보방), 줌마렐라(menu 70)
2. 설정 화면 실사용 검증(카페 불러오기 → 저장 → 워처 반영 확인)
3. (선택) 분류별 통계/집계, 인기글 분류 세분화 등 추가 요구 대응

---

## 📌 중요한 결정사항

- **분류 저장소**: 현재 config 파일(`config/targets.json`) 유지 (DB 아님)
- **게시판 반영 방식**: 자동 — 워처가 config mtime 감시 후 핫리로드(재시작 불필요)
- **분류 체계**: 핫딜 · 앱체크 · 유머 · 일반인기글 (동적, UI로 변경 가능)
- **분류 방식**: 내용 분석이 아닌 **게시판(보드) 기반** — 정확도 우선
- **"일상인기글" = "일반인기글"** = 인기글 보드(`popular_category`)
- **인증**: 폼+쿠키(SESSIONS 인메모리 토큰). Basic Auth는 인앱브라우저 호환 문제로 폐기
- **화면 레이아웃**: 카테고리는 상단 탭 필터 방식

---

## ⚠️ 개발 시 주의점 (운영 노트)

- `server.py` 수정 후에는 **수동 서버 재시작** 필요
  (`src.poc.server` 매칭 python kill → supervisor가 ~16~20초 후 재기동).
  `index.html`은 매번 fresh 서빙되므로 브라우저 새로고침만 하면 됨
- 커밋 후 동기화: `git pull --rebase origin main` → `git push origin main` (분리 실행)
  — 린터가 `config/targets.json`을 재수정해 커밋 전 pull이 실패하는 경우가 있음
- 시스템 리마인더로 자동 수정 표시되는 파일(dashboard_auth.json, config.yml,
  keepalive vbs)은 되돌리지 말 것

---

## 주요 엔드포인트/파일

| 구분 | 위치 |
|---|---|
| 서버 | `src/poc/server.py` (FastAPI) |
| 워처 | `src/poc/watcher.py` (폴링+핫리로드) |
| 네이버 API | `src/poc/cafe_api.py` (게시판추출: `cafe-cafemain-api/.../menus` + `X-Cafe-Product: pc`) |
| DB | `src/poc/db.py` (SQLite WAL) |
| 프론트 | `src/poc/static/index.html` |
| 설정 | `config/targets.json` |
| 감시자 | `C:\Users\USER\svc\supervisor.ps1` |
| 관리 API | `/api/admin/config`, `/api/admin/cafe-boards`, `/api/admin/save-cafe`, `/api/admin/categories` (모두 master 전용) |
