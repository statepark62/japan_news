"""
threads_publish.py
-------------------
Threads(스레드)에 텍스트 게시물을 자동으로 올리는 재사용 모듈.
天声人語, 日々の便り, bite-size-japanese 등 어느 파이프라인에서든
이 모듈의 publish_to_threads() 함수 하나만 불러다 쓰면 됩니다.

필요한 환경변수 (GitHub Actions Secrets에 등록):
    THREADS_ACCESS_TOKEN : 발급받은 장기 액세스 토큰
    THREADS_USER_ID      : Threads 사용자 ID (예: 27326433150368539)

사용 예:
    from threads_publish import publish_to_threads
    result = publish_to_threads("오늘의 天声人語 요약...\\n\\n전문 보기: https://...")
    print(result)  # {"id": "게시물ID"} 또는 {"error": "..."}
"""

import os
import time
import requests

THREADS_API_BASE = "https://graph.threads.net/v1.0"
MAX_THREADS_LENGTH = 500  # Threads 게시물 글자수 제한 (안전 마진 포함)


class ThreadsPublishError(Exception):
    """Threads 게시 과정에서 발생한 오류를 나타냅니다."""
    pass


def _get_credentials():
    """환경변수에서 토큰과 사용자 ID를 가져옵니다."""
    token = os.environ.get("THREADS_ACCESS_TOKEN")
    user_id = os.environ.get("THREADS_USER_ID")
    if not token or not user_id:
        raise ThreadsPublishError(
            "THREADS_ACCESS_TOKEN 또는 THREADS_USER_ID 환경변수가 설정되어 있지 않습니다. "
            "GitHub Actions Secrets에 두 값을 등록했는지 확인하세요."
        )
    return token, user_id


def truncate_for_threads(text: str, url: str = None, max_length: int = MAX_THREADS_LENGTH) -> str:
    """
    본문이 500자를 넘으면 안전하게 잘라내고, URL이 있으면 항상 끝에 붙입니다.
    URL 자체 길이는 Threads에서 짧게 표시되지만, 안전하게 계산에 포함합니다.
    """
    suffix = f"\n\n{url}" if url else ""
    available = max_length - len(suffix) - 1  # 말줄임표(…) 여유 1자

    if len(text) <= available:
        return text + suffix

    truncated = text[:available].rstrip() + "…"
    return truncated + suffix


def create_container(text: str, retries: int = 3, backoff_seconds: int = 5) -> str:
    """
    1단계: Threads 게시 컨테이너를 생성하고 creation_id를 반환합니다.
    일시적인 네트워크/서버 오류에 대비해 재시도 로직을 포함합니다.
    """
    token, user_id = _get_credentials()
    url = f"{THREADS_API_BASE}/{user_id}/threads"
    payload = {
        "media_type": "TEXT",
        "text": text,
        "access_token": token,
    }

    last_error = None
    for attempt in range(1, retries + 1):
        response = requests.post(url, data=payload, timeout=30)
        if response.status_code == 200 and "id" in response.json():
            return response.json()["id"]

        last_error = response.text
        if attempt < retries:
            time.sleep(backoff_seconds)

    raise ThreadsPublishError(f"컨테이너 생성 실패 (재시도 {retries}회 소진): {last_error}")


def publish_container(creation_id: str, retries: int = 3, backoff_seconds: int = 5) -> dict:
    """
    2단계: 생성된 컨테이너를 실제로 발행합니다.
    """
    token, user_id = _get_credentials()
    url = f"{THREADS_API_BASE}/{user_id}/threads_publish"
    payload = {
        "creation_id": creation_id,
        "access_token": token,
    }

    last_error = None
    for attempt in range(1, retries + 1):
        response = requests.post(url, data=payload, timeout=30)
        if response.status_code == 200 and "id" in response.json():
            return response.json()

        last_error = response.text
        if attempt < retries:
            time.sleep(backoff_seconds)

    raise ThreadsPublishError(f"게시 발행 실패 (재시도 {retries}회 소진): {last_error}")


def publish_to_threads(text: str, url: str = None) -> dict:
    """
    전체 게시 흐름을 한 번에 처리하는 함수.
    text가 500자를 넘으면 자동으로 잘라내고, url이 주어지면 본문 끝에 덧붙입니다.

    반환값 예: {"id": "18616746442031448"}
    실패 시 ThreadsPublishError 예외를 발생시킵니다.
    """
    final_text = truncate_for_threads(text, url)
    creation_id = create_container(final_text)
    # Threads API는 컨테이너 생성 직후 바로 발행하면 간헐적으로 실패하는 경우가 있어
    # 짧은 대기 시간을 둡니다.
    time.sleep(2)
    result = publish_container(creation_id)
    return result


if __name__ == "__main__":
    # 단독 실행 테스트용 (실제 파이프라인에서는 import해서 사용)
    import sys

    test_text = sys.argv[1] if len(sys.argv) > 1 else "threads_publish.py 테스트 게시입니다."
    test_url = sys.argv[2] if len(sys.argv) > 2 else None
    try:
        result = publish_to_threads(test_text, test_url)
        print("게시 성공:", result)
    except ThreadsPublishError as e:
        print("게시 실패:", e)
        sys.exit(1)
