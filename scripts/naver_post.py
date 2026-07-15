#!/usr/bin/env python3
"""
네이버 카페 글쓰기 모듈.
tenseijingo_naver 와 동일한 방식: 리프레시 토큰으로 접근 토큰을 갱신한 뒤
카페 게시판(clubid/menuid)에 subject/content 를 POST 한다.

필요 환경변수(GitHub Secrets):
  NAVER_REFRESH_TOKEN      - 네이버 로그인(카페) OAuth 리프레시 토큰
  NAVER_LOGIN_CLIENT_ID    - 네이버 로그인용 애플리케이션 Client ID
  NAVER_LOGIN_CLIENT_SECRET- 네이버 로그인용 애플리케이션 Client Secret
  NAVER_CAFE_CLUB_ID       - 카페 클럽 ID
  NAVER_CAFE_MENU_ID       - 게시판(메뉴) ID

이미 tenseijingo 에서 발급/보관 중인 값을 그대로 재사용하면 됩니다.
"""
import os
import json
import urllib.parse
import urllib.request

TOKEN_URL = "https://nid.naver.com/oauth2.0/token"
ARTICLE_URL = "https://openapi.naver.com/v1/cafe/{club}/menu/{menu}/articles"

# 제목 인코딩 방식: "utf-8" | "euc-kr" | "ascii"  (깨지면 값만 바꿔 재실행)
SUBJECT_ENCODING = "euc-kr"


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
    """인코딩 추측을 피하기 위해, ASCII 가 아닌 모든 글자(한글/일본어/기호)를
    HTML 숫자 참조(&#54620;)로 바꾼 뒤 URL 인코딩한다.
    결과 바디는 순수 ASCII 라 서버가 UTF-8 로 읽든 EUC-KR 로 읽든 바이트가 같아 깨지지 않고,
    브라우저가 렌더링할 때 원래 글자로 복원된다."""
    out = []
    for ch in text:
        if ord(ch) < 128:
            out.append(ch)
        else:
            out.append("&#%d;" % ord(ch))
    return urllib.parse.quote("".join(out), encoding="ascii")


def _subject_quote(text):
    """제목 인코딩 방식. 제목은 HTML 렌더링이 되지 않으므로 숫자참조를 쓸 수 없다.
    SUBJECT_ENCODING 을 바꿔가며 어떤 방식이 맞는지 확인한다.
      "utf-8"  : UTF-8 로 URL 인코딩  (현재 시험 중)
      "euc-kr" : EUC-KR 로 URL 인코딩 (utf-8 이 깨지면 이걸로)
      "ascii"  : 비ASCII 제거(최후 수단)
    """
    if SUBJECT_ENCODING == "euc-kr":
        # EUC-KR 에 없는 글자(일본어 등)는 ? 로 대체
        safe = []
        for ch in text:
            try:
                ch.encode("euc-kr"); safe.append(ch)
            except UnicodeEncodeError:
                safe.append("?")
        return urllib.parse.quote("".join(safe), encoding="euc-kr")
    if SUBJECT_ENCODING == "ascii":
        return urllib.parse.quote("".join(c for c in text if ord(c) < 128))
    return urllib.parse.quote(text, encoding="utf-8")


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
    # subject/content 를 ASCII(HTML 숫자참조) 로 URL 인코딩하여 폼 바디로 전송
    body = "subject=" + _subject_quote(subject)
    body += "&content=" + _ascii_quote(content_html)
    if open_to_public:
        body += "&openyn=true"

    req = urllib.request.Request(
        url, data=body.encode("ascii"),  # 퍼센트 인코딩 결과라 항상 ASCII
        headers={
            "Authorization": "Bearer " + token,
            "X-Naver-Client-Id": os.environ.get("NAVER_LOGIN_CLIENT_ID", "").strip(),
            "X-Naver-Client-Secret": os.environ.get("NAVER_LOGIN_CLIENT_SECRET", "").strip(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        print(f"[ok] 카페 게시 완료: {res}")
        return res
    except Exception as e:
        print(f"[warn] 카페 게시 실패: {e}")
        return None
