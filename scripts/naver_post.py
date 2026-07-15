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

    # 전송 방식 정리 (실측 근거)
    #  - form-urlencoded 로 보낸 시도들은 항상 "게시 성공"했다(글자만 깨짐).
    #  - 이중 인코딩 / multipart 로 바꾸자 403(내부 500/999) 로 거부됐다.
    #    → transport 는 반드시 form-urlencoded 여야 한다.
    #  - 깨짐 양상이 서로 모순(UTF-8→CP949로 읽힘 / EUC-KR→UTF-8로 읽다 실패)인 것은
    #    네이버가 charset 을 추측하기 때문. 그래서 charset 을 명시해 추측을 없앤다.
    fields = {
        "subject": urllib.parse.quote(subject, safe="", encoding="utf-8"),
        "content": urllib.parse.quote(content_html, safe="", encoding="utf-8"),
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
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            res = json.loads(resp.read().decode("utf-8"))
        print(f"[ok] 카페 게시 완료: {res}")
        return res
    except urllib.error.HTTPError as e:
        # 네이버가 보낸 실제 사유를 그대로 출력 (원인 파악에 필수)
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            detail = "(응답 본문 없음)"
        print(f"[warn] 카페 게시 실패: HTTP {e.code}")
        print(f"[warn] 네이버 응답: {detail[:800]}")
        print(f"[info] 전송 바디 길이: {len(body)}자")
        return None
    except Exception as e:
        print(f"[warn] 카페 게시 실패: {e}")
        return None
