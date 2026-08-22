"""
hibi_to_threads.py
--------------------
日々の便り 파이프라인(japan_news)이 생성하는 docs/news.json을 읽어서,
가장 상위(items[0]) 뉴스 1건만 뽑아 Threads에 "요약 + 링크" 형태로 게시합니다.

news.json 구조 예시:
{
  "items": [
    {
      "category": "문화",
      "ko_title": "한국어 제목",
      "ko_summary": "한국어 요약...",
      "link": "https://news.livedoor.com/article/...",
      "korea_related": false,
      ...
    },
    ...
  ]
}

사용 예:
    python hibi_to_threads.py --news ../../docs/news.json

기본적으로 링크는 원문 뉴스가 아니라, 오늘의 뉴스 전체와 한국 보도 비교까지
볼 수 있는 日々の便り 앱(GitHub Pages) 주소로 겁니다.
(원문 뉴스로 링크하고 싶으면 --link-mode article 사용)
"""

import argparse
import json
import sys

from threads_publish import publish_to_threads, ThreadsPublishError

HASHTAGS = "#日々の便り #일본뉴스 #일본어공부"

DEFAULT_APP_URL = "https://statepark62.github.io/japan_news/"

SUMMARY_MAX_CHARS = 150


def _shorten(text: str, max_chars: int = SUMMARY_MAX_CHARS) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def load_top_item(news_path: str) -> dict:
    with open(news_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", [])
    if not items:
        raise ValueError(f"news.json에 items가 비어 있습니다: {news_path}")

    return items[0]


def build_teaser(item: dict) -> str:
    title = item.get("ko_title", "").strip()
    summary = _shorten(item.get("ko_summary", "").strip())
    category = item.get("category", "").strip()

    parts = []
    header = f"🗞️ {title}" if title else "🗞️ 오늘의 日本 뉴스"
    if category:
        header = f"[{category}] {header}"
    parts.append(header)

    if summary:
        parts.append(summary)

    parts.append(HASHTAGS)
    return "\n\n".join(parts)


def main():
    parser = argparse.ArgumentParser(
        description="日々の便り news.json의 최상위 뉴스를 Threads에 게시합니다."
    )
    parser.add_argument("--news", required=True, help="news.json 파일 경로")
    parser.add_argument(
        "--link-mode",
        choices=["app", "article"],
        default="app",
        help="app: 日々の便り 앱(전체 다이제스트)으로 링크 / article: 원문 뉴스로 직접 링크 (기본값: app)",
    )
    parser.add_argument(
        "--app-url",
        default=DEFAULT_APP_URL,
        help=f"--link-mode app일 때 사용할 앱 주소 (기본값: {DEFAULT_APP_URL})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제로 게시하지 않고, 생성될 텍스트만 확인합니다.",
    )
    args = parser.parse_args()

    try:
        item = load_top_item(args.news)
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ {e}")
        sys.exit(1)

    if args.link_mode == "article":
        url = item.get("link", args.app_url)
    else:
        url = args.app_url

    teaser_text = build_teaser(item)

    print("----- Threads에 게시할 내용 -----")
    print(teaser_text)
    print(f"(첨부 링크: {url})")
    print("--------------------------------")

    if args.dry_run:
        print("(dry-run 모드: 실제 게시는 하지 않았습니다)")
        return

    try:
        result = publish_to_threads(teaser_text, url)
        print("✅ 게시 성공:", result)
    except ThreadsPublishError as e:
        print(f"❌ 게시 실패: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
