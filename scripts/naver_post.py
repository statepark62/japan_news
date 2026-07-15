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

    # tenseijingo 의 실제 동작 경로와 동일:
    #   값을 UTF-8 로 "한 번" 퍼센트 인코딩하고, multipart/form-data 로 전송한다.
    #   (requests 가 files 와 함께 보낼 때 값을 재인코딩하지 않는 것과 같은 결과)
    #   multipart 는 값이 순수 ASCII 로 실려 서버 charset 해석에 영향받지 않는다.
    fields = {
        "subject": urllib.parse.quote(subject, safe=""),
        "content": urllib.parse.quote(content_html, safe=""),
    }
    if open_to_public:
        fields["openyn"] = "true"

    boundary = "----jpnewsBoundary7MA4YWxkTrZu0gW"
    parts = []
    for k, v in fields.items():
        parts.append(f"--{boundary}\r\n")
        parts.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n')
        parts.append(v + "\r\n")
    parts.append(f"--{boundary}--\r\n")
    body = "".join(parts)

    req = urllib.request.Request(
        url, data=body.encode("ascii"),
        headers={
            "Authorization": "Bearer " + token,
            "X-Naver-Client-Id": os.environ.get("NAVER_LOGIN_CLIENT_ID", "").strip(),
            "X-Naver-Client-Secret": os.environ.get("NAVER_LOGIN_CLIENT_SECRET", "").strip(),
            "Content-Type": f"multipart/form-data; boundary={boundary}",
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
