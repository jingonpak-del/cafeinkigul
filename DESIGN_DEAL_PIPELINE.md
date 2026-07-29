# 설계안 — 딜/정보 활용 파이프라인 (검토용)

> 목적: 수집된 카페글에서 **검증된 사실**(살아있는 링크·가격·마감·이미지 속 텍스트)을
> 뽑아내고 → 그 사실만으로 **내 카페용 글을 최소 LLM으로 재구성**한다.
> 상태: **검토 대기**. 승인 후 A → B → C 순으로 하나씩 구현.

핵심 원칙 (전 단계 공통):
1. **DB에 이미지 원본(BLOB) 저장 금지.** URL·OCR텍스트·썸네일 경로만.
2. **LLM은 규칙으로 선별된 소수 후보에만.** 전 글에 돌리지 않는다.
3. **LLM에는 검증된 필드만 준다.** 가격·링크·마감을 지어내지 못하게.
4. 기존 구조 존중: `articles.content_html` 재사용(재크롤 X), `used/used_by` 흐름 위에 얹기,
   워처는 단일 스레드이므로 **부하가 큰 작업은 저율(rate-limited)·후보 한정**으로.

---

## A단계 — 링크 해제 + 신선도/마감 + 교차카페 (LLM 0, 최우선)

### A-0. 한눈에
```
새 딜 후보(핫딜/앱테크, body_crawled=1, link_checked=0)
   → 본문에서 링크 추출
   → 리다이렉트 끝까지 해제 → 최종 URL·도메인
   → 목적지 OG메타(제목/이미지/가격/재고) + 품절/404 감지
   → 본문·댓글에서 마감 신호 파싱 → expires_at
   → 최종 URL로 교차카페 dedup → cross_cafe_count
   → 대시보드에 🟢LIVE / ⏰마감임박 / ⚫만료 / ❌품절 뱃지 + 신선도 정렬
```

### A-1. DB 스키마 (db.py)
신규 테이블 `links` — 글 1개에 링크 N개:
```sql
CREATE TABLE IF NOT EXISTS links (
    cafe_id     INTEGER NOT NULL,
    article_id  INTEGER NOT NULL,
    seq         INTEGER NOT NULL,          -- 글 내 링크 순서(0,1,2...)
    raw_url     TEXT,                       -- 본문에서 추출한 원본
    final_url   TEXT,                       -- 리다이렉트 해제 후 최종
    domain      TEXT,                       -- 최종 호스트(coupang.com 등)
    og_title    TEXT,
    og_image    TEXT,
    price       INTEGER,                    -- 파싱 성공 시 원 단위
    in_stock    INTEGER,                    -- 1=재고 / 0=품절 / NULL=모름
    http_status INTEGER,
    status      TEXT DEFAULT 'pending',     -- pending|ok|dead|error
    checked_at  INTEGER,
    PRIMARY KEY (cafe_id, article_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_links_final ON links (final_url);
```
`articles`에 롤업 컬럼 추가(`_migrate()`에 삽입 — 기존 방식 그대로):
```
link_checked  INTEGER DEFAULT 0   -- 링크 해제 완료 여부(0=대기)
primary_domain TEXT               -- 대표 도메인(첫 유효 링크)
deal_status   TEXT                -- live|expiring|expired|dead|na
expires_at    INTEGER             -- 마감 추정 시각(ms), 없으면 NULL
deadline_text TEXT                -- 근거 문구("오늘까지" 등, 디버그용)
```
> `cross_cafe_count`는 저장 안 하고 **쿼리 시 `links.final_url` GROUP BY로 계산**(항상 최신).

### A-2. 링크 추출 (신규 `src/poc/enrich.py`)
- 입력: `articles.content_html`(없으면 `content_text`). **재크롤 안 함.**
- `<a href>` + 본문 내 맨URL(정규식) 모두 수집.
- **제외**: 네이버 카페 내부 링크(`cafe.naver.com`, `m.cafe.naver.com`), 이미지 파일 확장자,
  네이버 로그인/프로필 링크.
- **포함**: 외부 상거래/앱/이벤트 링크(단축 URL 포함: naver.me, bit.ly, 쿠팡 短링크 등).
- 순서 보존해 `links`에 `status=pending`으로 insert.

### A-3. 리다이렉트 해제 + 목적지 확인 (`enrich.py`)
- **미인증 httpx 클라이언트**(외부 상거래는 로그인 불필요; 네이버 세션 안 씀).
- `follow_redirects=True`, timeout 8s, UA 지정. HEAD 실패 시 GET 폴백.
- `final_url` → `domain` 추출. 페이지 HTML에서:
  - OG: `og:title`, `og:image`, `product:price:amount`/`og:price:amount`
  - 재고/종료: 본문에 `품절|sold ?out|판매종료|일시품절` → `in_stock=0`;
    HTTP 404/410 또는 페이지 없음 → `status=dead`.
- 실패(봇차단·타임아웃)해도 파이프라인 죽이지 않음: `status=error`로 두고 raw/domain은 보존.

**정중함·부하 억제(중요, 서버 안정성):**
- 호스트당 **초당 1~2요청**, 워처 사이클당 **최대 3건**만 처리.
- **`final_url` 캐시**: 같은 딜이 여러 카페에 있어도 목적지는 1회만 조회(메모리+DB 조회).

### A-4. 마감/신선도 파싱 (`enrich.py`)
- 본문+댓글 텍스트 정규식:
  - 절대일: `~까지`, `YYYY.MM.DD`, `M월 D일까지`
  - 상대·소진형: `오늘까지`, `내일까지`, `선착순`, `한정수량`, `조기종료`, `~시까지`
- `expires_at` 계산(명시 없으면 카테고리 기본 TTL 사용, 아래 config).
- `deal_status`:
  - `dead`(품절/404) > `expired`(now>expires_at) > `expiring`(마감 N시간 내) > `live`
  - 핫딜/앱테크가 아니면 `na`.

### A-5. config (config/targets.json)
최상위에 카테고리별 수명 추가(없으면 기본값):
```json
"deal": {
  "ttl_hours": { "핫딜/쇼핑정보": 24, "앱테크/이벤트": 24 },
  "expiring_within_hours": 3,
  "check_categories": ["핫딜/쇼핑정보", "앱테크/이벤트"]
}
```
> `_board_categories()`처럼 서버·워처가 파일을 매번 새로 읽으므로 **핫리로드로 즉시 반영**.

### A-6. 워처 통합 (src/poc/watcher.py)
- 기존 라운드로빈 루프의 **유휴 구간**에 `enrich_step()` 호출(사이클당 최대 3건).
- 후보 쿼리: `deal.check_categories`에 속하고 `body_crawled=1 AND link_checked=0`인 글.
- 처리 후 `articles.link_checked=1` + 롤업 컬럼 갱신.
- 별도 프로세스/스레드 신설 안 함(단일 루프 유지 → supervisor 구성 불변).

### A-7. 서버·API (src/poc/server.py)
- `/api/articles` 행에 계산 필드 추가: `deal_status, expires_at, primary_domain, price, cross_cafe_count`.
  - `cross_cafe_count`: `links` self-join / `final_url` 기준 DISTINCT cafe 수.
- 신규 필터 파라미터: `deal=live|expiring|all`(기본 all), 정렬 `order=fresh` 추가.
- 신규 조회: `GET /api/article/{cafe_id}/{article_id}/links` → 딜 카드 상세(도메인·가격·재고).

### A-8. 대시보드 (src/poc/static/index.html)
- 목록 뱃지: `🟢 LIVE` / `⏰ 마감임박` / `⚫ 만료` / `❌ 품절` / `🔥 N개 카페`.
- 대표 도메인·가격 인라인 표시(있을 때).
- 필터 토글: **살아있는 딜만**, 정렬 옵션: **신선도순**.
- 만료·품절은 흐리게(회색) 처리(숨김 아님 — 근거 확인용).

### A-9. 엣지 케이스
- `content_html` NULL(본문 미크롤) → `link_checked` 건드리지 않고 스킵(다음 기회에).
- 봇차단/타임아웃 → `status=error`, 도메인만이라도 보존, 재시도는 하지 않음(과부하 방지).
- 네이버 내부 단축(naver.me)만 있고 외부 없음 → 해제해서 목적지 판별.
- 링크 0개 글 → `link_checked=1`, `deal_status`는 TTL만으로 판정.

### A-10. 완료 기준(검증)
- [ ] 핫딜 글 목록에 LIVE/만료/품절 뱃지가 뜬다.
- [ ] 같은 딜이 여러 카페에 있으면 `🔥 N개 카페`가 뜬다.
- [ ] 만료 시간이 지난 딜이 자동 회색 처리된다.
- [ ] 워처 도입 후에도 폴링 주기·서버 부하에 눈에 띄는 저하가 없다(사이클당 3건 제한 확인).

---

## B단계 — 이미지: URL 전량 + 후보만 OCR/썸네일 (개요, 검토용)

### 정책 (3계층)
| 계층 | 대상 | 저장 | 비고 |
|---|---|---|---|
| 기본(전 글) | 모든 이미지 | **URL만** | `content_html`에서 파싱, 다운로드 0 |
| 후보 한정 | 핫딜 전단지·쿠폰 | **OCR 텍스트 + 1줄 캡션** | 정보가 이미지 안에 있는 경우 |
| 꼭 필요할 때만 | 대표 1~2장 | **WebP 썸네일**(파일, 경로만 DB) | 발행 예정 글 |

### 스키마(안)
```sql
CREATE TABLE IF NOT EXISTS images (
    cafe_id INTEGER, article_id INTEGER, seq INTEGER,
    url TEXT, ocr_text TEXT, caption TEXT,
    local_path TEXT, kind TEXT,          -- flyer|coupon|photo|meme
    PRIMARY KEY (cafe_id, article_id, seq)
);
```
### OCR 수단(택1, 후보에만)
- 무료·대량: Tesseract(kor) / PaddleOCR
- 정확·이해 결합: 비전 LLM 1장당 1콜(전단지에 강함) — 후보 한정이라 비용 미미
### 결정 필요 사항
- OCR 엔진 선택, 썸네일 보관 기간, 이미지 유형 자동분류(전단지 vs 짤) 규칙.

---

## C단계 — 최소 LLM으로 카페 글 재구성 (개요, 검토용)

### 파이프라인
```
후보선별(규칙: 반응도상위+미사용+미만료)  ← LLM 0
  → 구조화 추출(값싼 LLM 1회 또는 정규식)   {상품/혜택/가격/마감/링크}
  → 작성: 핫딜/앱테크=코드 템플릿(LLM 0) / 유머·일반=창작 LLM
  → 사람 검수 큐
  → 발행(기존 used 흐름)
```
### 스키마(안)
```sql
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src_keys TEXT,          -- 근거 글들 "cafe:article,..."(통합글 지원)
    gen_title TEXT, gen_body TEXT,
    model TEXT, tokens INTEGER,
    status TEXT DEFAULT 'draft',   -- draft|approved|published|rejected
    created_at INTEGER
);
```
### 비용 최소화
- **템플릿+LLM 하이브리드**(핫딜은 작성에 LLM 0), **배치 처리**(Batch API ≈50%↓),
  **프롬프트 캐싱**(템플릿 고정부), 여러 카페 같은 딜 → **1개 통합글**.
### 안전
- LLM엔 A·B에서 **검증된 필드만** 전달 + `"주어진 값만 사용, 지어내지 마"`.
### 결정 필요 사항
- 모델 선택(Gemini Flash-Lite / GPT-mini / Claude Haiku / HyperCLOVA X),
  자동화 수준(전량 검수 vs 신뢰 카테고리 자동발행), 발행 채널 연동 방식.

---

## 구현 순서 & ROI
| 순서 | 단계 | LLM | 선행조건 | 효과 |
|---|---|---|---|---|
| 1 | **A** 링크해제+신선도 | 0 | 없음 | 살아있는 딜 자동 선별(즉시 체감) |
| 2 | **B** 이미지 URL+OCR | 후보만 | A의 후보 개념 | 전단지형 딜 내용 확보 |
| 3 | **C** 초안 생성 | 소수 | A·B 검증데이터 | 발행 반자동화 완성 |

**A → B → C.** 각 단계는 앞 단계의 산출물을 재료로 쓴다.

---

## 검토 포인트 (여기에 의견 주세요)
1. A의 워처 통합 방식(단일 루프 저율 처리) vs 별도 스레드 — 부하/단순성 트레이드오프.
2. 딜 판정 카테고리를 `핫딜/쇼핑정보`+`앱테크/이벤트`로 한정 OK?
3. 기본 TTL 24h 적절한가(카테고리별로 더 세분화할지).
4. 만료/품절 글을 대시보드에서 **회색 처리**(제안) vs **숨김**.
5. B의 OCR 엔진 선호(무료 대량 vs 비전LLM 정확).
6. C의 LLM 모델·자동화 수준.
