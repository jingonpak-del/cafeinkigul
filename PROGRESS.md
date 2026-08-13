# 인기글 트래커 — 작업 진행 현황

> 네이버 카페 **전량 수집(Lake) + 큐레이션** 시스템
> Repo: https://github.com/jingonpak-del/cafeinkigul (main)
> 데이터: `D:\cafe-corpus`(DB·raw·logs) — 코드는 C:\Users\USER\인기글
> 최종 갱신: 2026-08-11

---

## 0. 큰 그림 (아키텍처)

**한 DB(`D:\cafe-corpus\db\tracker.db`) 위에 2계층:**
- **Lake(통째 수집)** — 모든 카페의 **모든 게시판** 글을 다 축적(학습 base). 분류는 수집 전제 아님.
- **Curated(큐레이션)** — 분석으로 **승격된 게시판**만 실시간+호응도로 운영 → 대시보드 카테고리 탭.

목표 흐름: `Lake → 주기분석(가치·주제·키워드) → 추천 → 사람 승인 → 승격(Curated)`.
자세한 설계: [DESIGN_COLLECT_CURATE.md](DESIGN_COLLECT_CURATE.md) (+ DESIGN_DEAL_PIPELINE.md, DESIGN_CAFE_DISCOVERY.md).

---

## 1. 수집 경로 (4가지 → 한 DB)

| 경로 | 주기 | 대상 | 실시간 | 호응도 | 계정 | lane |
|---|---|---|:--:|:--:|---|---|
| **스트림(메뉴보드)** | 상시 라운드로빈 | 승격된 등록 게시판 | ✅ | ✅ | 스트림 계정 | stream |
| **인기글 수집** | 하루 2회(2·16시) | 전 카페 popular | ❌ | ❌ | 스트림 계정 | stream |
| **backfill(과거)** | 야간 배치 | 전 카페·전 게시판(id 역scan, 2년) | ❌ | ❌ | **4계정 병렬** | backfill |
| **frontfill(신규)** | 20분 배치 | 전 카페·전 게시판(id 헤드전진) | △ | ❌ | **4계정 병렬** | frontfill |

- **승격 게시판은 frontfill이 제외** → 스트림이 실시간+호응도 담당(선점 방지).
- 원본 HTML은 DB가 아니라 **zstd 아카이브**(`raw_archive`, 압축 ~10.5배).

---

## 2. ✅ 완료 (Phase 1~5)

### 발굴(Discovery) — 수집 대상 카페 확장
- 섹션 API 열거: `powercafes`(대표) / `region-cafes`(동네) / `themecafes`(테마 전체 자동 순회).
- `cafe_candidates` 테이블 + 2단계(열거→probe로 학습가치 심사) + 주제 다양성 상한.
- **점수상위 자동 채택**: 매일 심사 통과분을 `crawl_all`로 자동 편입.
- 설정 **🔎 카페 발굴 탭**: 후보 표 + [통째]/[선별] + 🔒가입필요 + 직접조사.

### 전량 수집 기반화 (Phase 5-1)
- **frontfill 대상 = 모든 카페 기본**(crawl_all:false로만 제외).
- 승격 게시판 frontfill 제외(`crawl_one` skip_menus) — 호응도 보호.

### 다계정 분산 (Phase 5-2) — 빠르고 안전
- **`accountpool.py`**: 아이디관리(`idstore`) 로그인 계정 풀. 카페별 접근가능 계정에 배정(회원확인 캐시, club_id 분배).
- **크롤 계정 4개 고정**: `HADLEYPARSONS/SNOWGREENT9/11/12` (config.crawl_accounts). 57개 전 카페 4계정 접근가능 확인.
- **frontfill·backfill 병렬화**: 계정별 스레드(독립 DB커넥션·rate예산) → 처리량 ~4배, 밴 위험 분산.
- **membership.py**: `account_membership` 테이블(계정↔카페 접근여부).

### 가치 분석 (Phase 3·4-1)
- **`analytics.py`** + `GET /api/admin/board-stats`: 인기글 진입률·반응·볼륨으로 게시판 가치 랭크 + 주제 롤업.
- 설정 **📊 가치 있는 게시판** 패널: ★미분류 표시 + [분류] 원클릭 + **새 분류 제안**(주제 롤업).

### 코어·안정화
- 실시간 스트림(라운드로빈)+본문·댓글+4h 재방문(호응도)+급상승/호응 점수.
- **워처 하드닝**: 주기작업 예외 격리 + 루프 백스톱 → 스레드 총정지(수집 멈춤) 방지. 시작 시 카테고리부터.
- Cloudflare 터널(dashboard.whitedr.com), 폼+쿠키 로그인, supervisor(uvicorn) 다서비스.
- 데이터 D: 이전(`paths.py`), 공유 rate limiter(스트림 우선/백필 양보).

### 분류 체계(현재)
- **핫딜/쇼핑정보 · 앱테크/이벤트 · 유머/볼거리 · 일반인기글** (동적, UI 추가/삭제).

---

## 3. 🔧 진행 중 / ⏭ 다음

- **(별도 세션) 4-2 키워드 자동 라우팅** — 게시판 지정 없이 제목/내용 키워드로 카테고리 배정. server.py·index.html 수정 중. ⚠️ 이 세션 끝날 때까지 그 두 파일 편집 회피.
- **⏭ 5-3 추천엔진(4-2 종료 후)** — 통째 corpus 분석 → 승격 게시판/새 카테고리 **추천 큐 + 승인 UI**. (analytics·board-stats가 뼈대)
- **⏭ 실시간 전용 계정 지정** — 스트림 계정이 config상 `내네이버아이디` 플레이스홀더 → 유효 계정 지정 권장(회원제 카페 승격보드 실시간 확보).
- (후속) 딜 파이프라인(링크해제·신선도), 이미지 OCR, LLM 재구성/재게시.

---

## 4. 📌 중요한 결정사항

- **통째가 기본**: 모든 카페 전 게시판 축적(학습 base). 실시간은 승격된 게시판만.
- **승격 = 게시판 단위**: 한 카페가 통째 + 승격보드 동시. 승격보드는 frontfill 제외(스트림 전담).
- **다계정 4개 고정 분산**(config.crawl_accounts), 계정별 rate 예산. 크롤 계정 ≠ 스트림 계정.
- **분류 = 게시판(보드) 기반 + (예정)키워드 라우팅**, 쿼리 시점 적용(재크롤 불필요).
- **분류/카페 저장소 = config 파일**, 워처가 mtime 감시 핫리로드.
- **목적 = 재게시 큐레이션 + 학습 코퍼스 균형**: 텍스트 영구보존 + 원본 zstd 아카이브.
- 자동 가입 안 함(CAPTCHA·약관) — 가입필요 카페는 사람이 가입 후 확인.

---

## 5. ⚠️ 운영 노트 (개발 시 주의)

- **DB·데이터는 `D:\cafe-corpus`** (paths.py). server/watcher/cli/backfill/frontfill 모두 이 경로.
- `server.py` 수정 후 **대시보드 수동 재시작** 필요:
  `powershell -Command "Get-Process python | ? { $_.CommandLine -like '*src.poc.server*' } | Stop-Process -Force"` → supervisor ~15~20초 후 재기동. `index.html`은 새로고침만.
- **커밋 시**: fork/타 세션이 `server.py·index.html·config`를 미커밋 수정 중일 수 있음 →
  **내 파일만 `git add`** 후 커밋, `git push`(가능하면 stash 없이). 그들 WIP를 stash로 건드리지 말 것.
- 크롤/발굴/백필 로그: `D:\cafe-corpus\logs`. 대시보드(워처) stdout/err: `C:\Users\USER\svc\logs\dashboard.log/.err`.
- 배치 파일은 **ASCII 콘텐츠만**(cmd가 비ASCII 줄을 깨뜨림). 파일명 한글은 무방.

---

## 6. 스케줄 잡 (배치)

| 잡 | 파일 | 주기 | 동작 |
|---|---|---|---|
| frontfill | `frontfill_실행.bat` | 20분(작업스케줄러 `frontfill`) | 다계정 병렬 신규 전진 |
| backfill | `백필_실행.bat` | 야간 | 다계정 병렬 과거 수집 |
| discovery | `발굴_실행.bat` | 일 1회 | 섹션 발굴 + 점수상위 자동채택 |
| 세션유지 | `세션유지_실행.bat` | — | 로그인 세션 keepalive |

---

## 7. 주요 파일

| 구분 | 위치 |
|---|---|
| 서버(API+워처) | `src/poc/server.py` |
| 실시간 워처 | `src/poc/watcher.py` |
| 과거/신규 수집 | `src/poc/backfill.py` · `src/poc/frontfill.py` |
| 다계정 풀·가입확인 | `src/poc/accountpool.py` · `src/poc/membership.py` · `src/poc/idstore.py` |
| 발굴 | `src/poc/discovery.py` (+ `capture_section_apis.py`) |
| 가치 분석 | `src/poc/analytics.py` |
| 네이버 API | `src/poc/cafe_api.py` |
| DB / 원본아카이브 / 경로 / 레이트 | `src/poc/db.py` · `raw_archive.py` · `paths.py` · `ratelimit.py` |
| 프론트 | `src/poc/static/index.html` |
| 설정 | `config/targets.json` (cafes · categories · crawl_accounts · discovery) |
| 감시자 | `C:\Users\USER\svc\supervisor.ps1` (+ `apps.json`) |
