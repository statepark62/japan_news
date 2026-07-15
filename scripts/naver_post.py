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


def post_article(subject, content_html, open_to_public=False):
    """카페 게시판에 글 작성. 성공 시 응답 dict, 실패 시 None."""
    club = os.environ.get("NAVER_CAFE_CLUB_ID", "").strip()
    menu = os.environ.get("NAVER_CAFE_MENU_ID", "").strip()
    if not (club and menu):
        print("[skip] 카페: CLUB_ID/MENU_ID 없음")
        return None

    token = _get_access_token()
    if not token:
        return None

    url = ARTICLE_URL.format(club=club, menu=menu)

    # 제목에 비ASCII 가 있으면 숫자참조가 그대로 노출되므로 미리 경고
    if any(ord(c) > 127 for c in subject):
        print("[warn] 제목에 비ASCII 문자가 있어 깨질 수 있습니다: " + subject)

    fields = {
        "subject": _ascii_quote(subject),
        "content": _ascii_quote(content_html),
    }
    if open_to_public:
        fields["openyn"] = "true"
    body = "&".join(f"{k}={v}" for k, v in fields.items())

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
            res = json.loads(resp.read().decode("utf-8"))
        print(f"[ok] 카페 게시 완료: {res}")
        return res
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            detail = "(응답 본문 없음)"
        print(f"[warn] 카페 게시 실패: HTTP {e.code}")
        print(f"[warn] 네이버 응답: {detail[:500]}")
        return None
    except Exception as e:
        print(f"[warn] 카페 게시 실패: {e}")
        return None
