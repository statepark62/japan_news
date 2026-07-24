# -*- coding: utf-8 -*-
"""
네이버 카페 글쓰기 모듈.

[실측으로 확정된 사실]
 1) transport: form-urlencoded (urllib). multipart/이중인코딩으로 바꾸면 403.
 2) 인코딩: 비ASCII 를 HTML 숫자참조(&#51068;)로 바꿔 보내면 서버 charset 과 무관하게 안 깨진다.
    본문은 HTML 로 렌더링되므로 숫자참조가 원래 글자로 표시된다.
    제목은 렌더링되지 않으므로 ASCII 문자만 사용해야 한다.
 3) 길이: 본문이 길면 500/999 로 거부된다. HTML 원문 기준 약 1500자 이내가 안전.
    → 이 조건에서 굵은 글씨·링크가 포함된 정상 게시글이 확인되었다.

필요 환경변수(GitHub Secrets):
  NAVER_REFRESH_TOKEN
  NAVER_LOGIN_CLIENT_ID / NAVER_LOGIN_CLIENT_SECRET
  NAVER_CAFE_CLUB_ID / NAVER_CAFE_MENU_ID
"""
import os
import re
import json
import time
import urllib.parse
import urllib.request
import urllib.error

TOKEN_URL = "https://nid.naver.com/oauth2.0/token"
ARTICLE_URL = "https://openapi.naver.com/v1/cafe/{club}/menu/{menu}/articles"

BODY_CAP = 1400          # HTML 원문 기준 안전 길이
NOTE_MORE = '<p>(요약본입니다. 전체 뉴스는 <a href="https://statepark62.github.io/japan_news/">여기</a>에서)</p>'


def _get_access_token():
    """리프레시 토큰으로 접근 토큰 갱신. 실패 시 None."""
    rt = os.environ.get("NAVER_REFRESH_TOKEN", "").strip()
    cid = os.environ.get("NAVER_LOGIN_CLIENT_ID", "").strip()
    csec = os.environ.get("NAVER_LOGIN_CLIENT_SECRET", "").strip()
    if not (rt and cid and csec):
        print("[skip] 카페: 네이버 로그인 토큰/클라이언트 정보 없음")
        return None
    params = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": cid,
        "client_secret": csec,
        "refresh_token": rt,
    })
    try:
        with urllib.request.urlopen(f"{TOKEN_URL}?{params}", timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        token = data.get("access_token")
        if not token:
            print(f"[warn] 카페 토큰 갱신 응답 이상: {data}")
        return token
    except Exception as e:
        print(f"[warn] 카페 토큰 갱신 실패: {e}")
        return None


def _ascii_quote(text):
    """비ASCII 문자를 HTML 숫자참조로 바꾼 뒤 URL 인코딩.
    결과가 순수 ASCII 라 서버 charset 해석과 무관하게 깨지지 않는다."""
    out = []
    for ch in text:
        out.append(ch if ord(ch) < 128 else "&#%d;" % ord(ch))
    return urllib.parse.quote("".join(out), safe="")


def _trim_html(html_text, cap=BODY_CAP):
    """HTML 을 태그 경계에서 안전하게 잘라 cap 이내로 만든다."""
    if len(html_text) <= cap:
        return html_text
    cut = html_text[:cap]
    # 태그 중간에서 끊기지 않도록 마지막 '>' 까지만 남긴다
    if ">" in cut:
        cut = cut[: cut.rindex(">") + 1]
    # 열린 <a> 가 남았으면 닫아준다
    if cut.count("<a ") > cut.count("</a>"):
        cut += "</a>"
    return cut + NOTE_MORE


def _send(url, token, subject, body_html, open_to_public, label):
    fields = {
        "subject": _ascii_quote(subject),
        "content": _ascii_quote(body_html),
    }
    if open_to_public:
        fields["openyn"] = "true"
    body = "&".join(f"{k}={v}" for k, v in fields.items())
    print(f"[info] {label}: 본문 원문 {len(body_html)}자 / 전송 {len(body)}자")

    req = urllib.request.Request(
        url, data=body.encode("ascii"),
        headers={
            "Authorization": "Bearer " + token,
            "X-Naver-Client-Id": os.environ.get("NAVER_LOGIN_CLIENT_ID", "").strip(),
            "X-Naver-Client-Secret": os.environ.get("NAVER_LOGIN_CLIENT_SECRET", "").strip(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return True, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            detail = "(응답 없음)"
        return False, f"HTTP {e.code} / {detail[:200]}"
    except Exception as e:
        return False, str(e)


def post_article(subject, content_html, open_to_public=False):
    """카페 게시판에 글 작성. 길이를 줄여가며 최대 3회 시도."""
    club = os.environ.get("NAVER_CAFE_CLUB_ID", "").strip()
    menu = os.environ.get("NAVER_CAFE_MENU_ID", "").strip()
    if not (club and menu):
        print("[skip] 카페: CLUB_ID/MENU_ID 없음")
        return None

    token = _get_access_token()
    if not token:
        return None

    url = ARTICLE_URL.format(club=club, menu=menu)

    if any(ord(c) > 127 for c in subject):
        print("[warn] 제목에 비ASCII 가 있어 깨질 수 있습니다: " + subject)

    # 네이버의 길이 허용치가 날마다 다르게 나타난다(어제 1500자 성공, 오늘 1000자 실패).
    # 그래서 긴 것부터 차례로 줄여가며 "그날 통과하는 최대 길이"를 자동으로 찾는다.
    caps = [1400, 1200, 1000, 800, 600, 400]
    for i, cap in enumerate(caps):
        if i:
            time.sleep(8)
        body = _trim_html(content_html, cap)
        ok, res = _send(url, token, subject, body, open_to_public, f"{cap}자")
        if ok:
            print(f"[ok] 카페 게시 완료 ({cap}자): {res}")
            if i:
                print(f"[진단] {cap}자에서 통과 (앞 {i}회 실패)")
            return res
        print(f"[warn] {cap}자 실패: {res}")

    print("[진단] 모든 길이에서 실패 → 길이 외의 요인(일시적 게시 제한 등)일 수 있습니다.")
    return None
