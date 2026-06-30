# PoC 결과 — 핵심 가정 검증 완료 ✅

**가정**: 단일 네이버 계정 세션으로, 무거운 브라우저가 아니라 **가벼운 인증 HTTP**로
보드의 최신 글 목록을 실시간 폴링할 수 있는가?

**결론**: **가능.** 공개 보드는 로그인 없이도 되고, 회원전용/인기글 보드는 캡처한 쿠키로 처리.

## 검증된 엔드포인트

### 1) clubId 해석 (cafe vanity url → 숫자 ID)
`https://cafe.naver.com/{cluburl}` HTML에서 정규식 추출.
- `memberupup3` → `29827664` ✅

### 2) 보드 최신 글 목록 (핵심)
```
GET https://apis.naver.com/cafe-web/cafe2/ArticleListV2.json
    ?search.clubid={clubId}&search.queryType=lastArticle
    &search.menuid={menuId}&search.page=1&search.perPage={N}
```
- 공개 보드(menu 1): **쿠키 없이 200 + 데이터** ✅
- 회원전용 보드(menu 15): 쿠키 없으면 9999 오류 → **로그인 쿠키 필요** (예상대로)
- `menuId=0` = 카페 전체

### 3) 응답에서 바로 얻는 필드 (Watcher가 필요한 전부)
`articleId`(중복키), `subject`(제목), `writerNickname`/`memberKey`(작성자),
`readCount`(조회수→4h 변동폭), `commentCount`, `likeItCount`,
`writeDateTimestamp`/`lastCommentedTimestamp`, `popular`(인기글 플래그),
`attachImage` 등 첨부, `blindArticle`, `hasNext`(페이징).

## 만들어진 모듈 (`src/poc/`)
| 파일 | 역할 |
|---|---|
| `cafe_api.py` | clubId 해석 + 목록 조회 + `ArticleSummary` 정규화 (검증됨) |
| `session.py` | 수동 로그인 → 쿠키 캡처 → 검증 (캡챠 우회 없음) |
| `cookie_store.py` / `dpapi.py` | DPAPI 암호화 세션 저장 (기존 코드 이식) |
| `cli.py` | resolve / fetch / capture / verify |

## 실행법
```powershell
python -m src.poc.cli resolve --cafe memberupup3
python -m src.poc.cli fetch   --cafe memberupup3 --menu 1 --n 30
python -m src.poc.cli capture --account NAVER_ID    # 브라우저 로그인
python -m src.poc.cli verify  --account NAVER_ID
python -m src.poc.cli fetch   --cafe memberupup3 --menu 15 --account NAVER_ID   # 인증
```

## 인증 경로 + 두 보드 유형 검증 완료 ✅✅ (masanmam, club_id=14793916)
- **일반 게시판 (menu 70)**: `capture`한 세션으로 인증 조회 성공 → 실제 글/조회수/댓글수 반환.
- **인기글 보드**: 전용 엔드포인트 확정 →
  `cafe2/WeeklyPopularArticleListV3.json?cafeId={clubId}&mobileWeb=true&adUnit=PC_CAFE_BOARD&ad=false`
  (CDP 네트워크 캡처로 발견; `queryType=popular`은 무시되는 가짜였음). 228개 인기글 반환.
  스키마 차이: `nickname`/`upCount`/`lastCommentDateTimestamp` → `_to_summary()`가 양쪽 호환 처리.
- **설정파일 구동**: `config/targets.json` → `python -m src.poc.cli track`으로 두 보드 동시 조회 성공.
- **중복 발견**: 같은 글이 일반게시판과 인기글에 동시 노출됨 → **중복키는 (cafe_id, article_id) 전역**으로,
  "어느 보드에서 감지됐는지"는 별도(다대다)로 기록해야 함.

## (이전) 인증 메커니즘 1차 확인
- 실제 계정으로 `capture` 성공 → NID_AUT/NID_SES 쿠키 12개 저장됨.
- 인증 조회 시 서버가 로그인을 인식하고 `cafeMember` 값을 정확히 반환 → **세션/쿠키 메커니즘 정상.**
- memberupup3의 회원전용 보드가 막힌 것은 세션 문제가 아니라 **테스트 계정이 그 카페(남의 테스트 카페) 회원이 아니기 때문**(`cafeMember: False`).
- **남은 1가지**: 본인이 실제 가입한 카페의 회원전용 보드로 최종 확인 (방법은 아래).

### 메뉴 ID 찾는 법 (전용 API가 까다로워 브라우저 방식 채택)
브라우저에서 카페의 원하는 보드를 클릭 → 주소창의 `menus/{번호}` 또는 `menuid={번호}` 숫자가 menuId.

## 남은 검증 (다음 단계)
- [ ] **인증 경로 최종**: 본인 가입 카페의 회원전용 보드 `fetch --account` 성공 확인
- [ ] **인기글 보드 전용 쿼리**: `popular` 플래그 외에 인기글 메뉴 자체의 menuId/쿼리 확인
- [ ] **본문 + 댓글 API**: 글 1건의 본문/댓글 조회 엔드포인트 확정
- [ ] **레이트리밋 감 잡기**: ~50보드 라운드로빈 시 안전한 초당 요청 수
