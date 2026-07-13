# 日々の便り — 일본 뉴스 통합 파이프라인

정해진 시각에 일본 주요 뉴스를 모아 다음을 한 번에 처리합니다.

1. **한국어 요약 + 한국 언론 매칭** — 각 기사를 Claude 로 요약하고, 같은 사안의 한국 보도를 네이버 검색으로 찾음
2. **구글 시트 기록** — 뉴스 전체를 `뉴스기록` 시트에, 오늘의 단어를 `단어장` 시트에 누적 (중복 제거)
3. **네이버 카페 게시** — tenseijingo 처럼 게시판에 요약 글 자동 작성 (한일 관련 우선)
4. **일본어 단어 업데이트** — 오늘 뉴스에서 학습용 단어를 뽑아 시트·`vocab.json` 갱신 (ことば帖 연동용)
5. **GitHub Pages** — `docs/index.html` 이 `news.json` 을 읽어 카드로 표시 (한일 관련엔 붉은 도장 印)

## 전체 흐름

```
GitHub Actions (매일 아침 7시 KST 1회, 또는 수동 실행)
   └─ scripts/collect.py
        1) NHK RSS 6종 수집
        2) Claude: 한국어 요약·키워드·한일관련 분류
           · 이미 분석한 기사는 캐시 재사용(state/analysis_cache.json) — 품질 동일, 중복 호출 제거
           · 새 기사만 6개씩 묶어 분석 — 반복 지시문 토큰 절약
        3) 네이버 검색: 한국 보도 매칭
        4) Claude: 오늘의 일본어 단어 추출
        5) GAS 웹앱 → 구글 시트(뉴스기록 / 단어장) 누적
        6) naver_post.py → 카페 게시판에 요약 글 게시
        7) docs/news.json, docs/vocab.json 출력 → Pages 반영
```

## 파일 구성

```
config.json              소스·처리량·시트·카페 설정
scripts/collect.py       메인 오케스트레이터
scripts/naver_post.py    네이버 카페 글쓰기(토큰 갱신 포함)
gas/Code.gs              구글 시트 수집 웹앱(범용, 여러 시트 처리)
docs/index.html          Pages 프론트
docs/news.json           생성물(뉴스)
docs/vocab.json          생성물(단어) — ことば帖 에서 읽어 쓸 수 있음
.github/workflows/build.yml  크론 + 수동 실행
```

## 설치

### A. 기본 (뉴스 수집 + Pages)
1. 저장소에 업로드 → **Settings → Pages** → 브랜치 배포, 폴더 `/docs`.
2. **Secrets** 등록:
   - `ANTHROPIC_API_KEY`
   - `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` (네이버 개발자센터 "검색" API)
3. **Actions → build-news → Run workflow** 로 첫 실행.

### B. 구글 시트 기록
1. 스프레드시트 생성 → 확장 프로그램 → Apps Script → `gas/Code.gs` 붙여넣기.
2. `SHEET_ID`, `SHARED_SECRET` 채우기 → 웹 앱으로 배포(액세스: 모든 사용자).
3. Secrets: `GAS_SHEET_URL`(웹앱 URL), `GAS_SHARED_SECRET`(같은 비밀문자열).
   - `뉴스기록`(전체, 한일관련 Y/N 열 포함) + `단어장` 시트가 자동 생성됩니다.

### C. 네이버 카페 게시 (tenseijingo 값 재사용)
Secrets:
- `NAVER_REFRESH_TOKEN` — 네이버 로그인(카페) OAuth 리프레시 토큰
- `NAVER_LOGIN_CLIENT_ID` / `NAVER_LOGIN_CLIENT_SECRET` — "네이버 아이디로 로그인" 애플리케이션
- `NAVER_CAFE_CLUB_ID` / `NAVER_CAFE_MENU_ID` — 카페/게시판 ID

> 카페 글쓰기는 검색 API 와 별개로 "네이버 아이디로 로그인 + 카페" 권한이 필요합니다.
> 이미 tenseijingo_naver 에서 발급/보관 중인 토큰과 클럽/메뉴 ID 를 그대로 넣으면 됩니다.
> 접근 토큰은 리프레시 토큰으로 매 실행마다 자동 갱신됩니다.

각 단계는 해당 Secret 이 없으면 자동으로 건너뜁니다. A → B → C 순으로 하나씩 붙여도 됩니다.

## 조절 (config.json)

- `feeds` / `max_items_per_feed` / `max_total_items` — 소스와 처리량(=API 비용)
- `naver_matches_per_item` — 기사당 한국 보도 매칭 개수
- `vocab_per_day` — 하루 추출 단어 수
- `claude_model` — 기본 `claude-sonnet-5`(신형, 8/31까지 도입가 $2/$10)
- `analysis_batch_size` — 한 번 호출에 묶어 분석할 기사 수(기본 6)
- `analysis_cache_cap` — 분석 캐시 보관 개수(기본 600)
- `cafe.include` — `korea_first`(기본) / `korea`(한일만) / `all`
- `cafe.max_items` — 카페 글에 넣을 기사 수
- `cafe.enabled` — 카페 게시 on/off

## 비용과 품질

품질(요약·번역)은 그대로 두고 낭비만 줄이도록 설계했습니다.
- **모델**: Sonnet 5 — 신형이라 품질 저하 없이 현재 더 저렴(도입가). Haiku 로 낮추지 않음.
- **분석 캐시**: 어제 처리한 기사가 오늘 피드에 남아 있어도 다시 분석하지 않고 재사용.
- **묶음 분석**: 기사별 분석 깊이는 유지하되 호출 수를 줄여 반복 지시문 토큰 절약.

하루 1회 기준 대략 월 수천 원 수준이며, 캐시가 쌓일수록 신규 기사만 분석해 더 낮아집니다.
`state/analysis_cache.json` 은 매 실행 후 자동 갱신·커밋되므로 직접 건드릴 필요 없습니다.

## 天声人語 시스템과의 관계

이 저장소는 tenseijingo_naver 와 **별개**입니다. 천성인어 글 1편과 이 뉴스 글 1편이
각각 독립적으로 카페에 올라갑니다(합치지 않음). 두 시스템은 서로 영향을 주지 않습니다.

## 뉴스 소스에 관하여

현재 **NHK** 6개 카테고리(종합·정치·경제·국제·사회·과학문화). 아사히·마이니치·요미우리는
공개 RSS 를 중단했고, Yahoo! Japan 은 약관상 취득 정보로 앱을 만들어 공개하는 것을 금지합니다.
백제·유물 등 문화 교류 뉴스는 NHK **과학문화(cat7)** 피드가 잘 잡습니다.

## 로컬 미리보기

```bash
cd docs && python3 -m http.server   # http://localhost:8000
```
