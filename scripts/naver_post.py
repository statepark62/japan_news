# -*- coding: utf-8 -*-
"""
네이버 카페 글쓰기 모듈.

tenseijingo_naver 의 "오늘도 실제로 성공하는" 경로를 그대로 복제한다.
  · requests 사용
  · data = {"subject": quote(...), "content": quote(...)}   (UTF-8 단일 퍼센트 인코딩)
  · files 에 이미지를 붙여 multipart/form-data 로 전송
    → files 가 있으면 requests 는 값을 재인코딩하지 않으므로,
      최종 전송값 = "단일 퍼센트 인코딩된 문자열" 이 된다.

이미지가 없으면 (form-urlencoded 로 빠지면서) 실패하는 사례가 있어,
첨부할 이미지가 없을 때는 작은 표지 이미지를 자동 생성해 붙인다.

필요 환경변수(GitHub Secrets):
  NAVER_REFRESH_TOKEN
  NAVER_LOGIN_CLIENT_ID / NAVER_LOGIN_CLIENT_SECRET
  NAVER_CAFE_CLUB_ID / NAVER_CAFE_MENU_ID
"""
import os
import io
import re
import time
from urllib.parse import quote

import requests

TOKEN_URL = "https://nid.naver.com/oauth2.0/token"


def _get_access_token():
    """리프레시 토큰으로 접근 토큰 발급. 실패 시 None."""
    rt = os.environ.get("NAVER_REFRESH_TOKEN", "").strip()
    cid = os.environ.get("NAVER_LOGIN_CLIENT_ID", "").strip()
    csec = os.environ.get("NAVER_LOGIN_CLIENT_SECRET", "").strip()
    if not (rt and cid and csec):
        print("[skip] 카페: 네이버 로그인 토큰/클라이언트 정보 없음")
        return None
    try:
        r = requests.get(TOKEN_URL, params={
            "grant_type": "refresh_token",
            "client_id": cid,
            "client_secret": csec,
            "refresh_token": rt,
        }, timeout=20)
        r.raise_for_status()
        j = r.json()
        if "access_token" not in j:
            print(f"[warn] 카페 토큰 갱신 실패: {j}")
            return None
        return j["access_token"]
    except Exception as e:
        print(f"[warn] 카페 토큰 갱신 실패: {e}")
        return None


def _make_cover_image(text_lines):
    """첨부용 표지 이미지를 만든다(PNG bytes). Pillow 가 없으면 None."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    W, H = 800, 420
    img = Image.new("RGB", (W, H), (15, 27, 51))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)],
               fill=(int(27*(1-t)+15*t), int(47*(1-t)+27*t), int(87*(1-t)+51*t)))
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    def _font(size):
        for p in font_paths:
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
        return ImageFont.load_default()
    d.text((48, 60), "日々の便り", font=_font(56), fill=(243, 238, 227))
    d.text((48, 140), "일본 주요 뉴스 · 한국의 시선", font=_font(28), fill=(199, 208, 228))
    y = 210
    for line in (text_lines or [])[:3]:
        d.text((48, y), ("· " + line)[:44], font=_font(22), fill=(154, 166, 200))
        y += 38
    d.ellipse([W-110, H-110, W-60, H-60], outline=(192, 54, 44), width=3)
    d.ellipse([W-93, H-93, W-77, H-77], fill=(192, 54, 44))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _headlines(content_html):
    """본문에서 굵은 제목 몇 개를 뽑아 표지 이미지에 쓴다."""
    items = re.findall(r"<b>(.*?)</b>", content_html)
    out = []
    for s in items:
        s = re.sub(r"<[^>]+>", "", s).strip()
        if s and not s.startswith("한국 보도") and not re.match(r"^\d{4}-\d{2}-\d{2}", s):
            out.append(s)
    return out[:3]


def _remove_anchors(html_text):
    """<a href=...>텍스트</a> → 텍스트  (HTML 구조는 유지, 링크만 제거)"""
    t = re.sub(r'<a\b[^>]*>(.*?)</a>', r'\1', html_text, flags=re.I | re.S)
    t = re.sub(r'https?://\S+', '', t)     # 본문에 노출된 생 URL 도 제거
    return t


def _to_plain(html_text):
    """HTML 태그와 URL 을 모두 제거한 순수 텍스트."""
    t = re.sub(r'<br\s*/?>|</p>|<hr\s*/?>', '\n', html_text, flags=re.I)
    t = re.sub(r'<[^>]+>', '', t)
    t = re.sub(r'https?://\S+', '', t)
    return re.sub(r'\n{3,}', '\n\n', t).strip()


def _try_post(url, token, subject, content, open_to_public, png, label):
    """한 번 전송하고 (성공여부, 응답/오류) 반환."""
    data = {"subject": quote(subject, safe=""), "content": quote(content, safe="")}
    if open_to_public:
        data["openyn"] = "true"
    files = {}
    if png:
        files["image"] = ("cover.png", io.BytesIO(png), "image/png")
    print(f"[info] {label} 전송 (본문 {len(content)}자)")
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {token}"},
                          data=data, files=files if files else None, timeout=60)
    except Exception as e:
        return False, f"요청 오류: {e}"
    if r.status_code != 200:
        return False, f"HTTP {r.status_code} / {r.text[:200]}"
    try:
        return True, r.json()
    except Exception:
        return True, {"raw": r.text[:200]}


def post_article(subject, content_html, open_to_public=False):
    """카페 게시판에 글 작성.
    실패하면 링크를 뺀 본문 → 순수 텍스트 순으로 재시도해 원인을 판별한다."""
    club = os.environ.get("NAVER_CAFE_CLUB_ID", "").strip()
    menu = os.environ.get("NAVER_CAFE_MENU_ID", "").strip()
    if not (club and menu):
        print("[skip] 카페: CLUB_ID/MENU_ID 없음")
        return None

    token = _get_access_token()
    if not token:
        return None

    url = f"https://openapi.naver.com/v1/cafe/{club}/menu/{menu}/articles"
    png = _make_cover_image(_headlines(content_html))
    if png:
        print(f"[info] 표지 이미지 첨부 ({len(png)}바이트)")

    # 1차: 원본 (링크 포함)
    ok, res = _try_post(url, token, subject, content_html, open_to_public, png, "1차 원본")
    if ok:
        print(f"[ok] 카페 게시 완료: {res}")
        return res
    print(f"[warn] 1차 실패: {res}")

    # 2차: 링크만 제거 (HTML 유지)
    time.sleep(5)
    ok, res = _try_post(url, token, subject, _remove_anchors(content_html),
                        open_to_public, png, "2차 링크제거")
    if ok:
        print(f"[ok] 카페 게시 완료(링크 제거본): {res}")
        print("[진단] 링크를 빼니 성공 → 외부 링크가 차단 사유입니다.")
        return res
    print(f"[warn] 2차 실패: {res}")

    # 3차: 순수 텍스트 (HTML·링크 모두 제거)
    time.sleep(5)
    ok, res = _try_post(url, token, subject, _to_plain(content_html)[:1500],
                        open_to_public, png, "3차 순수텍스트")
    if ok:
        print(f"[ok] 카페 게시 완료(순수 텍스트): {res}")
        print("[진단] HTML 을 빼니 성공 → 본문 HTML 이 차단 사유입니다.")
        return res
    print(f"[warn] 3차 실패: {res}")

    # 4차: 최소 텍스트 (내용 자체가 문제인지 최종 확인)
    time.sleep(5)
    ok, res = _try_post(url, token, subject, "오늘의 일본 뉴스 요약입니다.",
                        open_to_public, None, "4차 최소텍스트(이미지 없음)")
    if ok:
        print(f"[ok] 최소 텍스트는 게시 성공: {res}")
        print("[진단] 최소 텍스트만 성공 → 본문 내용/이미지에 차단 요인이 있습니다.")
        return res
    print(f"[warn] 4차 실패: {res}")
    print("[진단] 최소 텍스트조차 실패 → 본문 문제가 아닙니다.")
    print("[진단] 이 앱(Client ID)의 카페 글쓰기 권한 또는 API 이용 설정을 확인하세요.")
    return None
