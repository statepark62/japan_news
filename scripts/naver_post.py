# -*- coding: utf-8 -*-
"""
네이버 카페 글쓰기 모듈.

[실측으로 확정된 사실]
 1) transport 는 form-urlencoded 여야 한다.
    (이중 인코딩 / multipart 로 바꾸면 403 + 내부 500/999 로 거부됨)
 2) 서버의 charset 처리는 제어 불가능하다.
    UTF-8 로 보내도, EUC-KR 로 보내도, charset 을 명시해도 모두 깨졌다.
 3) 그러나 ASCII 는 어떤 charset 으로 읽어도 바이트가 동일하므로 절대 깨지지 않는다.
    → 본문: 비ASCII 를 HTML 숫자참조(&#51068;)로 변환. 브라우저가 렌더링할 때 원래 글자로 표시됨.
      (실제 게시글에서 본문이 정상 표시됨을 확인)
    → 제목: HTML 렌더링이 안 되므로 숫자참조를 쓸 수 없다. 제목은 ASCII 문자만 사용한다.

필요 환경변수(GitHub Secrets):
  NAVER_REFRESH_TOKEN
  NAVER_LOGIN_CLIENT_ID / NAVER_LOGIN_CLIENT_SECRET
  NAVER_CAFE_CLUB_ID / NAVER_CAFE_MENU_ID
"""
import os
import json
import time
import urllib.parse
import urllib.request
import urllib.error

TOKEN_URL = "https://nid.naver.com/oauth2.0/token"
ARTICLE_URL = "https://openapi.naver.com/v1/cafe/{club}/menu/{menu}/articles"


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
    결과가 순수 ASCII 라 서버가 어떤 charset 으로 읽어도 깨지지 않는다."""
    out = []
    for ch in text:
        out.append(ch if ord(ch) < 128 else "&#%d;" % ord(ch))
    return urllib.parse.quote("".join(out), safe="")


def _send(url, token, subject, content_html, open_to_public):
    """실제 전송. (성공 dict, None) 또는 (None, 오류설명) 반환."""
    fields = {
        "subject": _ascii_quote(subject),
        "content": _ascii_quote(content_html),
    }
    if open_to_public:
        fields["openyn"] = "true"
    body = "&".join(f"{k}={v}" for k, v in fields.items())
    print(f"[info] 전송 바디 {len(body)}자 (본문 원문 {len(content_html)}자)")

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
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            detail = "(응답 본문 없음)"
        return None, f"HTTP {e.code} / {detail[:300]}"
    except Exception as e:
        return None, str(e)


def post_article(subject, content_html, open_to_public=False):
    """카페 게시판에 글 작성. 실패 시 짧은 본문으로 한 번 재시도한다."""
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
        print("[warn] 제목에 비ASCII 문자가 있어 깨질 수 있습니다: " + subject)

    # 1차: 정상 본문
    res, err = _send(url, token, subject, content_html, open_to_public)
    if res:
        print(f"[ok] 카페 게시 완료: {res}")
        return res
    print(f"[warn] 카페 게시 실패(1차): {err}")

    # 2차: 본문을 대폭 줄여 재시도 → 성공하면 길이 문제, 실패하면 길이 무관(서버측 제한 등)
    time.sleep(5)
    short = content_html[:1500]
    if "<" in short:
        short = short.rsplit("<", 1)[0]        # 태그 중간에서 잘리지 않게
    short += "<p>(본문 일부만 게시되었습니다)</p>"
    print("[info] 짧은 본문으로 재시도합니다.")
    res2, err2 = _send(url, token, subject, short, open_to_public)
    if res2:
        print(f"[ok] 카페 게시 완료(짧은 본문): {res2}")
        print("[진단] 짧은 본문은 성공 → 본문 길이가 원인입니다. config 의 cafe.max_items 를 줄이세요.")
        return res2
    print(f"[warn] 카페 게시 실패(2차): {err2}")
    print("[진단] 짧은 본문도 실패 → 길이 문제 아님. 네이버측 일시 제한(도배 방지) 가능성이 큽니다.")
    return None
