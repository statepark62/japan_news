#!/usr/bin/env python3
"""
일본 뉴스 통합 파이프라인 (비용 최적화판)
  1) 일본 RSS 수집
  2) Claude 로 한국어 요약/키워드/한일관련 분류
        · 이미 분석한 기사는 캐시 재사용 (품질 동일, 중복 호출 제거)
        · 새 기사만 여러 개씩 묶어서 분석 (반복 지시문 토큰 절약)
  3) 네이버 검색으로 한국 언론 매칭
  4) Claude 로 오늘의 일본어 단어 추출
  5) 구글 시트에 뉴스 + 단어 기록 (GAS 웹앱)
  6) 네이버 카페 게시판에 요약 글 게시
  7) docs/news.json, docs/vocab.json 출력

키/URL 이 없는 단계는 자동으로 건너뛴다(부분 동작 가능).
"""
import os
import re
import json
import time
import html
import hashlib
import datetime
import urllib.parse
import urllib.request

import feedparser
import naver_post

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
NEWS_OUT = os.path.join(ROOT, "docs", "news.json")
VOCAB_OUT = os.path.join(ROOT, "docs", "vocab.json")
CACHE_PATH = os.path.join(ROOT, "state", "analysis_cache.json")

KST = datetime.timezone(datetime.timedelta(hours=9))

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "").strip()
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "").strip()
GAS_SHEET_URL = os.environ.get("GAS_SHEET_URL", "").strip()
GAS_SHARED_SECRET = os.environ.get("GAS_SHARED_SECRET", "").strip()

ANALYSIS_FIELDS = ("ko_title", "ko_summary", "keywords", "korea_related", "korea_note")


# ----------------------------------------------------------------------------- utils
def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def clean_text(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def item_id(link):
    return hashlib.md5(link.encode("utf-8")).hexdigest()[:12]


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def claude_json(prompt, model, max_tokens=1500):
    """Claude 에 프롬프트를 보내고 JSON 을 파싱해 돌려준다. 실패 시 None."""
    if not ANTHROPIC_API_KEY:
        return None
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        }, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 응답이 길어 중간에 잘린 경우: 완성된 객체만 건져낸다(0개보다 낫다)
            salvaged = _salvage_json_array(text)
            if salvaged:
                print(f"[warn] claude 응답이 잘려 {len(salvaged)}개만 복구")
                return salvaged
            raise
    except Exception as e:
        print(f"[warn] claude 호출 실패: {e}")
        return None


def _salvage_json_array(text):
    """잘린 JSON 배열 문자열에서 완전한 { ... } 객체들만 파싱해 리스트로 돌려준다."""
    if not text.lstrip().startswith("["):
        return None
    items, depth, start, in_str, esc = [], 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    items.append(json.loads(text[start:i + 1]))
                except Exception:
                    pass
                start = None
    return items or None


# ----------------------------------------------------------------------------- 분석 캐시
def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache, cap):
    # 최근 항목 위주로 cap 개만 유지 (dict 삽입 순서 = 최신이 뒤)
    if len(cache) > cap:
        keys = list(cache.keys())[-cap:]
        cache = {k: cache[k] for k in keys}
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def empty_analysis():
    return {"ko_title": "", "ko_summary": "", "keywords": [], "korea_related": False, "korea_note": ""}


# ----------------------------------------------------------------------------- 1. RSS
def collect_feeds(cfg):
    items, seen = [], set()
    per_feed = cfg.get("max_items_per_feed", 6)
    for feed in cfg["feeds"]:
        try:
            parsed = feedparser.parse(feed["url"])
        except Exception as e:
            print(f"[warn] feed 실패 {feed['name']}: {e}")
            continue
        count = 0
        for entry in parsed.entries:
            link = entry.get("link", "").strip()
            if not link or link in seen:
                continue
            seen.add(link)
            items.append({
                "id": item_id(link),
                "source": feed["name"],
                "category": feed.get("category", ""),
                "jp_title": clean_text(entry.get("title", "")),
                "jp_summary": clean_text(entry.get("summary", entry.get("description", "")))[:400],
                "link": link,
                "published": entry.get("published", entry.get("updated", "")),
            })
            count += 1
            if count >= per_feed:
                break
        print(f"[ok] {feed['name']}: {count} items")
    return items[: cfg.get("max_total_items", 26)]


# ----------------------------------------------------------------------------- 2. 분석 (캐시 + 묶음)
def analyze_batch(subset, model):
    """여러 기사를 한 번의 호출로 분석. n(입력순번)->분석dict 반환."""
    lines = []
    for i, it in enumerate(subset, 1):
        lines.append(f"[{i}] 제목: {it['jp_title']}\n    요약: {it['jp_summary']}")
    listing = "\n".join(lines)
    prompt = f"""다음은 일본 뉴스 기사 목록입니다. 각 기사를 한국 독자를 위해 분석하세요.
각 기사에는 번호 [n] 이 있습니다. 반드시 모든 번호에 대해 하나씩, JSON 배열로만 답하세요.
설명·마크다운·코드펜스 없이 JSON 배열 하나만 출력합니다.

기사 목록:
{listing}

각 원소 형식:
{{
  "n": 기사 번호(정수),
  "ko_title": "한국어 제목 (고유명사는 한국식 표기: 岸田->기시다, 半導体->반도체)",
  "ko_summary": "한국어 2~3문장 요약",
  "keywords": ["한국 언론 검색용 키워드 2~3개 (한국식 표기, 고유명사 우선)"],
  "korea_related": true 또는 false (한국 언급/한일관계/한반도 사안이면 true),
  "korea_note": "한국과 어떤 관련이 있는지 한 줄. 없으면 빈 문자열"
}}"""
    r = claude_json(prompt, model, max_tokens=600 + 700 * len(subset))
    out = {}
    if isinstance(r, list):
        for el in r:
            try:
                n = int(el.get("n"))
            except Exception:
                continue
            out[n] = {
                "ko_title": el.get("ko_title", ""),
                "ko_summary": el.get("ko_summary", ""),
                "keywords": el.get("keywords", []),
                "korea_related": bool(el.get("korea_related", False)),
                "korea_note": el.get("korea_note", ""),
            }
    return out


def analyze_items(items, model, cfg, cache):
    """캐시에 없는 기사만 묶음 분석. items 에 분석 필드를 채우고 새 분석은 캐시에 넣는다."""
    todo = [it for it in items if it["id"] not in cache]
    cached_n = len(items) - len(todo)
    print(f"[ok] 분석: 캐시 재사용 {cached_n}건 / 신규 {len(todo)}건")

    batch_size = cfg.get("analysis_batch_size", 6)
    for batch in chunks(todo, batch_size):
        res = analyze_batch(batch, model)
        for i, it in enumerate(batch, 1):
            a = res.get(i)
            if a:
                cache[it["id"]] = a           # 성공한 것만 캐시(실패는 다음 실행에 재시도)
        time.sleep(0.3)

    # 모든 기사에 분석 적용 (캐시 우선, 없으면 빈 값)
    for it in items:
        a = cache.get(it["id"]) or empty_analysis()
        for k in ANALYSIS_FIELDS:
            it[k] = a.get(k, empty_analysis()[k])


# ----------------------------------------------------------------------------- 3. 네이버 검색
def search_naver(keywords, display):
    if not (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET) or not keywords:
        return []
    query = " ".join(keywords[:3])
    url = ("https://openapi.naver.com/v1/search/news.json?"
           + urllib.parse.urlencode({"query": query, "display": display, "sort": "sim"}))
    req = urllib.request.Request(url, headers={
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = []
        for it in data.get("items", []):
            out.append({
                "title": clean_text(it.get("title", "")),
                "desc": clean_text(it.get("description", ""))[:160],
                "link": it.get("originallink") or it.get("link", ""),
                "pub": it.get("pubDate", ""),
            })
        return out
    except Exception as e:
        print(f"[warn] naver 검색 실패: {e}")
        return []


# ----------------------------------------------------------------------------- 4. 단어 추출
def extract_vocab(items, model, n):
    titles = "\n".join(f"- {it['jp_title']}" for it in items[:20])
    prompt = f"""다음은 오늘의 일본 뉴스 제목 목록입니다.
여기서 한국인 중급~고급 학습자에게 유용한 일본어 단어/표현 {n}개를 골라 주세요.
너무 쉬운 기초어(する, ある 등)는 제외하고, 뉴스에서 자주 쓰이는 어휘 위주로.

제목 목록:
{titles}

각 단어마다 그 단어를 쓴 자연스러운 일본어 예문을 하나 만들고, 그 예문의 히라가나 읽기와
한국어 뜻도 함께 제시하세요. JLPT 레벨(N1~N5)도 추정해 주세요.

아래 JSON 형식으로만 답하세요(코드펜스 없이 JSON 배열 하나만):
[
  {{
    "word": "표제어(한자 표기)",
    "reading": "표제어 요미가나(히라가나)",
    "meaning": "한국어 뜻",
    "level": "JLPT 레벨 (N1/N2/N3/N4/N5 중 하나)",
    "example": "이 단어를 쓴 자연스러운 일본어 예문",
    "example_reading": "예문 전체의 히라가나 읽기",
    "example_meaning": "예문의 한국어 뜻"
  }}
]"""
    r = claude_json(prompt, model, max_tokens=800 + 700 * n)
    if isinstance(r, dict):
        r = r.get("words") or r.get("vocab") or []
    return r if isinstance(r, list) else []


# ----------------------------------------------------------------------------- 5. 시트 기록 (범용 GAS)
def push_rows(sheet, headers, rows, dedup_index=None, id_prefix=None):
    if not (GAS_SHEET_URL and GAS_SHARED_SECRET):
        print(f"[skip] 시트[{sheet}]: GAS_SHEET_URL/SECRET 없음")
        return
    if not rows:
        print(f"[ok] 시트[{sheet}]: 추가할 행 없음")
        return
    payload = {"secret": GAS_SHARED_SECRET, "sheet": sheet,
               "headers": headers, "rows": rows, "dedupIndex": dedup_index}
    if id_prefix:
        payload["idPrefix"] = id_prefix
    req = urllib.request.Request(
        GAS_SHEET_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        print(f"[ok] 시트[{sheet}]: {res}")
    except Exception as e:
        print(f"[warn] 시트[{sheet}] 실패: {e}")


def record_sheets(cfg, items, vocab, today):
    s = cfg.get("sheet", {})
    news_rows = []
    for it in items:
        matches = " / ".join(f"{m.get('title','')} ({m.get('link','')})" for m in it.get("kr_matches", []))
        news_rows.append([
            today, it.get("category", ""), it.get("source", ""),
            it.get("jp_title", ""), it.get("ko_title", ""), it.get("ko_summary", ""),
            "Y" if it.get("korea_related") else "N", it.get("korea_note", ""),
            it.get("link", ""), matches, it.get("id", ""),
        ])
    push_rows(
        s.get("news_sheet", "뉴스기록"),
        ["수집일", "분류", "매체", "일본어제목", "한국어제목", "한국어요약",
         "한일관련", "한일메모", "일본원문링크", "한국보도", "article_id"],
        news_rows, dedup_index=10,
    )
    # 단어장 (기존 ことば帖 구조: id | 단어 | 읽기 | 의미 | 레벨 | 예문 | 예문읽기 | 예문뜻 | 등록일)
    # id 와 등록일(맨 끝)은 GAS 가 자동 생성 → 여기서는 가운데 7칸만 보낸다.
    vocab_rows = [[
        v.get("word", ""), v.get("reading", ""), v.get("meaning", ""), v.get("level", ""),
        v.get("example", ""), v.get("example_reading", ""), v.get("example_meaning", ""),
    ] for v in vocab]
    push_rows(
        s.get("vocab_sheet", "단어장"),
        ["단어", "읽기", "의미", "레벨", "예문", "예문읽기", "예문뜻"],
        vocab_rows, dedup_index=0, id_prefix="news",
    )


# ----------------------------------------------------------------------------- 6. 카페 게시글 HTML
def build_cafe_html(cfg, items, vocab, stamp):
    c = cfg.get("cafe", {})
    include = c.get("include", "korea_first")
    limit = c.get("max_items", 10)
    korea = [x for x in items if x.get("korea_related")]
    others = [x for x in items if not x.get("korea_related")]
    if include == "korea":
        chosen = korea[:limit]
    elif include == "all":
        chosen = items[:limit]
    else:
        chosen = (korea + others)[:limit]

    def esc(s):
        return html.escape(s or "")

    parts = [f'<p><b>{esc(stamp)}</b> 기준 일본 주요 뉴스와 한국의 시선입니다.</p>']
    for it in chosen:
        badge = " [한일관련]" if it.get("korea_related") else ""
        parts.append("<hr>")
        parts.append(f'<p><b>[{esc(it.get("category",""))}]{badge} {esc(it.get("ko_title") or it.get("jp_title"))}</b></p>')
        parts.append(f'<p style="color:#555">{esc(it.get("jp_title"))}</p>')
        if it.get("ko_summary"):
            parts.append(f'<p>{esc(it["ko_summary"])}</p>')
        if it.get("korea_related") and it.get("korea_note"):
            parts.append(f'<p>↳ {esc(it["korea_note"])}</p>')
        if it.get("kr_matches"):
            links = "<br>".join(
                f'· <a href="{esc(m.get("link"))}">{esc(m.get("title"))}</a>' for m in it["kr_matches"]
            )
            parts.append(f'<p><b>한국 보도</b><br>{links}</p>')
        parts.append(f'<p><a href="{esc(it.get("link"))}">일본 원문 보기</a></p>')

    if vocab:
        parts.append("<hr><p><b>오늘의 일본어 단어</b></p>")
        rows = "".join(
            f'<tr><td>{esc(v.get("word"))}</td><td>{esc(v.get("reading"))}</td>'
            f'<td>{esc(v.get("meaning"))}</td></tr>' for v in vocab
        )
        parts.append(
            '<table border="1" cellpadding="5" style="border-collapse:collapse">'
            '<tr><th>표제어</th><th>읽기</th><th>뜻</th></tr>' + rows + '</table>'
        )
    parts.append('<hr><p style="color:#888">자동 생성 게시물 · 日々の便り</p>')
    return "".join(parts)


# ----------------------------------------------------------------------------- main
def main():
    cfg = load_config()
    model = cfg.get("claude_model", "claude-sonnet-5")
    today = datetime.datetime.now(KST).strftime("%Y-%m-%d")
    stamp = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    items = collect_feeds(cfg)

    cache = load_cache()
    analyze_items(items, model, cfg, cache)
    save_cache(cache, cfg.get("analysis_cache_cap", 600))

    for it in items:
        it["kr_matches"] = search_naver(it.get("keywords"), cfg.get("naver_matches_per_item", 3))
        time.sleep(0.2)

    vocab = extract_vocab(items, model, cfg.get("vocab_per_day", 8))
    print(f"[ok] 단어 추출: {len(vocab)}개")

    record_sheets(cfg, items, vocab, today)

    if cfg.get("cafe", {}).get("enabled"):
        # 제목은 HTML 렌더링이 되지 않고, 서버 charset 처리를 제어할 수 없어
        # 한글을 넣으면 반드시 깨진다. 따라서 ASCII 문자만 사용한다.
        title = f"{cfg['cafe'].get('title_prefix', '[Japan News]')} {today}"
        html_body = build_cafe_html(cfg, items, vocab, stamp)
        naver_post.post_article(title, html_body, cfg["cafe"].get("open_to_public", False))

    os.makedirs(os.path.dirname(NEWS_OUT), exist_ok=True)
    with open(NEWS_OUT, "w", encoding="utf-8") as f:
        json.dump({
            "app_title": cfg.get("app_title", "일본 뉴스"),
            "app_subtitle": cfg.get("app_subtitle", ""),
            "generated_at": stamp,
            "count": len(items),
            "items": items,
        }, f, ensure_ascii=False, indent=2)
    with open(VOCAB_OUT, "w", encoding="utf-8") as f:
        json.dump({"generated_at": stamp, "date": today, "words": vocab}, f, ensure_ascii=False, indent=2)
    print(f"[done] {len(items)} news, {len(vocab)} words 저장 완료")


if __name__ == "__main__":
    main()
