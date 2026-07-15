# -*- coding: utf-8 -*-
"""
네이버 카페 글쓰기 모듈.
tenseijingo_naver 의 검증된 방식과 동일하게 동작한다.

핵심: subject/content 는 UTF-8 로 퍼센트 인코딩한 문자열을 "폼 값"으로 넣고,
      폼을 만들 때 한 번 더 인코딩되어 전송된다(이중 인코딩). 네이버는 이를 두 번 풀어 읽는다.
      한 번만 인코딩하면 글자가 깨진다.

필요 환경변수(GitHub Secrets):
  NAVER_REFRESH_TOKEN
  NAVER_LOGIN_CLIENT_ID / NAVER_LOGIN_CLIENT_SECRET
  NAVER_CAFE_CLUB_ID / NAVER_CAFE_MENU_ID
"""
import os
import json
import urllib.parse
import urllib.request

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

    # 1차: UTF-8 퍼센트 인코딩 → 2차: urlencode 가 폼 값을 다시 인코딩 (이중 인코딩)
    fields = {
        "subject": urllib.parse.quote(subject, safe=""),
        "content": urllib.parse.quote(content_html, safe=""),
    }
    if open_to_public:
        fields["openyn"] = "true"
    body = urllib.parse.urlencode(fields)

    req = urllib.request.Request(
        url, data=body.encode("ascii"),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        print(f"[ok] 카페 게시 완료: {res}")
        return res
    except Exception as e:
        print(f"[warn] 카페 게시 실패: {e}")
        return None
