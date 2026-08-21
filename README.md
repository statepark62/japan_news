# 日々の便り — 일본 뉴스 통합 파이프라인

매일 아침 정해진 시각에 일본 뉴스를 모아 한국어로 요약하고, 같은 사안의 한국 보도를 찾아 나란히 보여주는 개인용 뉴스 시스템입니다.
뉴스 → 구글 시트 기록 → 고토바초(ことば帖) 단어장 연동 → 네이버 카페 게시 → 홈 화면 앱(PWA)까지 하루 한 번 자동으로 돕니다.

## 전체 흐름

```
GitHub Actions (매일 아침 7시 KST 1회, 또는 수동 실행)
  └─ scripts/collect.py
       1) livedoor 뉴스 + NHK RSS 수집 (오래된 기사는 자동 제외)
       2) 새 기사만 원문 페이지에서 본문 전체를 가져옴 (범용 추출기)
       3) Claude: 카테고리 분류 · 한국어 요약(본문 있으면 심도 있게) · 검색 키워드 · 한일관련 여부
          · 이미 분석한 기사는 캐시 재사용 (품질 동일, 중복 호출 제거)
       4) 네이버 검색: 같은 사안의 한국 보도 매칭
       5) Claude: 오늘의 일본어 단어 추출 (일본어 원문 기사가 있는 날에만)
       6) GAS 웹앱 → 구글 시트(뉴스기록 / 단어장) 누적, 방문자 카운트
       7) naver_post.py → 카페 게시판에 요약 글 게시 (길이 자동 조절)
       8) docs/news.json, docs/vocab.json 출력 → GitHub Pages 반영
```

## 파일 구성

```
config.json                  소스·처리량·시트·카페 설정
scripts/collect.py           메인 오케스트레이터
scripts/naver_post.py        네이버 카페 글쓰기 모듈
scripts/requirements.txt     Python 의존성
gas/Code.gs                  구글 시트 수집 웹앱 (여러 시트 처리 + 방문자 카운터)
docs/index.html              PWA 프론트 (새로고침 버튼·방문자 수·중단 안내 포함)
docs/manifest.webmanifest    PWA 매니페스트
docs/sw.js                   서비스워커 (오프라인 지원, 항상 최신 우선)
docs/icons/                  앱 아이콘
docs/news.json               생성물(뉴스) — 매 실행마다 갱신
docs/vocab.json               생성물(단어) — ことば帖 연동용
state/analysis_cache.json    기사 분석 캐시 (중복 분석 방지)
state/cafe_cap.json          카페 게시 성공 길이 기록 (다음 실행의 시작점)
.github/workflows/build.yml  크론 + 수동 실행
```

## 설치

### A. 기본 (뉴스 수집 + Pages)
1. 저장소에 업로드 → **Settings → Pages** → 브랜치 배포, 폴더 `/docs`.
2. **Secrets** 등록:
   - `ANTHROPIC_API_KEY`
   - `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` (네이버 개발자센터 "검색" API 전용 애플리케이션 — 카페용 앱과 반드시 분리)
3. **Actions → build-news → Run workflow** 로 첫 실행.

### B. 구글 시트 기록 + 방문자 카운터
1. 시트를 만들고 확장 프로그램 → Apps Script → `gas/Code.gs` 붙여넣기.
2. 코드 상단 `SHEET_ID`, `SHARED_SECRET` 채우기 → 웹 앱으로 배포(액세스: 모든 사용자).
3. Secrets: `GAS_SHEET_URL`(웹앱 URL), `GAS_SHARED_SECRET`.
4. `뉴스기록` · `단어장` 탭이 자동 생성됩니다. 기존에 쓰던 단어장이 있다면 `config.json`의 `sheet.vocab_sheet` 이름을 그 탭과 맞추면 이어 붙습니다.
5. 방문자 카운터를 쓰려면 `docs/index.html`의 `COUNTER_URL`에 같은 웹앱 `/exec` 주소를 넣으세요.

### C. 네이버 카페 자동 게시
Secrets:
- `NAVER_REFRESH_TOKEN`
- `NAVER_LOGIN_CLIENT_ID` / `NAVER_LOGIN_CLIENT_SECRET` (카페 글쓰기 권한이 있는 애플리케이션 — 검색용과 별개)
- `NAVER_CAFE_CLUB_ID` / `NAVER_CAFE_MENU_ID`

각 단계는 해당 Secret이 없으면 자동으로 건너뜁니다. A → B → C 순서로 하나씩 붙여도 됩니다.

## config.json 주요 설정

| 키 | 설명 |
|---|---|
| `feeds` | 뉴스 소스 목록. 각 항목에 `lang`("ja"/"en"), `path_category`(URL로 카테고리 추정), `reclassify`(Claude가 카테고리 재분류) 지정 가능 |
| `max_items_per_feed` / `max_total_items` | 처리량(=API 비용) 조절 |
| `max_article_age_days` | 이보다 오래된 기사는 자동 제외 (날짜를 못 읽은 기사는 통과시켜 오탐 방지) |
| `fetch_full_article` | 새 기사의 원문 페이지에서 본문 전체를 가져올지 (기본 true). 끄면 RSS 짧은 요약만 사용 |
| `vocab_per_day` | 하루 추출 단어 수 (일본어 원문 기사가 있는 날에만 채워짐) |
| `claude_model` / `analysis_batch_size` / `analysis_cache_cap` | 비용·속도 조절 |
| `sheet.news_sheet` / `sheet.vocab_sheet` | 시트 탭 이름 |
| `cafe.enabled` / `cafe.include` / `cafe.max_items` / `cafe.title_prefix` | 카페 게시 on/off, 기사 선정 기준, 개수, 제목 접두어(**ASCII만** — 한글 제목은 깨짐) |

## 뉴스 소스에 관하여 — 왜 livedoor 뉴스인가

**NHK는 2025년 7월부터 클라우드 인프라(Google Cloud, Azure 등)에서 오는 RSS 요청을 의도적으로 차단하고 있습니다.**
GitHub Actions도 Azure 클라우드에서 실행되므로 이 차단 대상에 해당합니다. 캐시 우회, 헤더 위장 등을 시도했지만 `Last-Modified` 헤더가 서버 측에서 실제로 갱신을 멈춘 것으로 확인되어(중간 캐시 문제가 아님), 코드로 해결할 수 없는 사안임을 확정했습니다.

그래서 현재는 **livedoor 뉴스**(`news.livedoor.com/topics/rss.xml`, NHK와 무관한 별도 시스템)를 메인 소스로 씁니다. NHK 피드는 설정에 그대로 남아 있어 **접속이 복구되면 자동으로 다시 섞여 들어옵니다** — 별도 조치가 필요 없습니다.

아사히·마이니치·요미우리는 이미 공개 RSS를 중단했고, Yahoo! Japan은 이용약관상 이런 자동화 앱에 쓸 수 없어 제외했습니다. Japan Times(영어)도 시도했으나, 일본어 학습(단어 추출 등) 목적에 맞지 않아 최종적으로 제외했습니다.

livedoor는 카테고리별 개별 RSS가 불확실해 "종합" 하나로 수집한 뒤, **Claude가 기사 내용을 보고 정치/경제/국제/사회/문화/스포츠/과학으로 재분류**합니다. NHK처럼 이미 정확한 카테고리를 가진 소스는 건드리지 않습니다.

## 요약 품질 — 본문 전체를 읽고 요약합니다

RSS가 주는 스니펫만으로는 요약이 얕고 부정확해질 수 있어(정보가 부족하면 Claude가 문장 수를 채우려다 사실이 아닌 내용을 지어낼 위험), **새로 분석하는 기사는 원문 페이지에서 본문 전체를 긁어와** 그걸 바탕으로 요약합니다.

- 본문 추출은 특정 사이트 구조에 의존하지 않는 범용 방식(`<article>` 태그 → 본문류 class/id → body 전체에서 메뉴류 제외)이라 소스가 바뀌어도 대체로 동작합니다.
- 본문을 확보하면 **4~6문장**(배경·경위·전망 포함)으로 심도 있게, 못 구하면 **2~3문장**으로 정확하게만 — Claude에게 정보가 부족할 때 억지로 채우지 말라고 명시했습니다.
- 이미 분석된(캐시된) 기사는 본문을 다시 긁지 않아 불필요한 요청이 없습니다.

## 네이버 카페 게시 — 알아두면 좋은 것들

수십 차례 실측 끝에 확정된 사실들입니다:

- **전송 방식은 반드시 `application/x-www-form-urlencoded`** — 이중 인코딩이나 `multipart/form-data`(이미지 첨부 포함)로 바꾸면 403/500 오류가 납니다.
- **본문은 ASCII HTML 숫자참조로 인코딩**(`&#51068;` 형식)해서 보냅니다. 서버가 UTF-8이든 EUC-KR이든 어떤 charset으로 읽어도 깨지지 않는 유일한 방법입니다. 브라우저가 렌더링할 때 원래 글자로 표시됩니다.
- **제목은 ASCII 문자만 사용해야 합니다.** 제목은 HTML로 렌더링되지 않아 숫자참조를 쓸 수 없고, 어떤 인코딩 조합을 시도해도 한글 제목은 깨졌습니다. 그래서 `[Japan News] YYYY-MM-DD` 형식을 씁니다.
- **게시 가능한 본문 길이가 날마다 다릅니다** (같은 계정·앱인데도 어떤 날은 1500자가 통과하고 어떤 날은 1000자도 거부됩니다). 그래서 `naver_post.py`는 긴 것부터 시도하며 자동으로 줄여가는 사다리(`1400→1200→1000→800→600→400`)를 쓰고, **성공한 길이를 `state/cafe_cap.json`에 기억**해 다음 실행은 그 근처부터 시작해 불필요한 재시도를 줄입니다.
- 실패 시 네이버가 보낸 실제 오류 메시지를 로그에 그대로 출력하도록 되어 있어(`[warn] 카페 게시 실패: ...`), 문제가 생기면 원인 파악이 빠릅니다.

## 天声人語 시스템과의 관계

이 저장소는 tenseijingo_naver 와 **별개**입니다. 천성인어 글 1편과 이 뉴스 글 1편이 각각 독립적으로 카페에 올라갑니다(합치지 않음). 다만 카페 글쓰기 애플리케이션(Client ID/Secret)은 tenseijingo가 이미 검증해둔 것을 공유해서 씁니다 — 검색용 애플리케이션과는 반드시 분리되어 있어야 합니다.

## 앱 화면 — 서비스 일시 중단 시 동작

뉴스 소스에 문제가 생겨 그날 수집이 0건이면, 화면이 완전히 비지 않습니다:
- 예전에 성공적으로 수집된 뉴스가 브라우저에 저장되어 있으면, 그걸 계속 보여주면서 상단에 "새 뉴스 수집이 일시 중단되었습니다" 배너를 띄웁니다.
- 저장된 게 전혀 없는 첫 방문자에게는 정중한 안내 카드를 보여줍니다.
- 문제가 해결되어 다음 실행이 정상 수집되면 배너는 자동으로 사라집니다. 별도 조치가 필요 없습니다.

## 조절 예시

- **뉴스·비용을 더 줄이고 싶다면**: `max_items_per_feed`, `max_total_items`를 낮추세요. 카테고리를 고르게 가져가려면 두 값을 함께 낮추는 게 좋습니다.
- **본문 추출을 끄고 싶다면**: `fetch_full_article: false` — 비용은 줄지만 요약이 다시 얕아집니다.
- **카페 게시를 잠시 끄고 싶다면**: `cafe.enabled: false` — 뉴스·시트·앱은 그대로 돌아갑니다.

## 로컬 미리보기

```bash
cd docs && python3 -m http.server   # http://localhost:8000
```
