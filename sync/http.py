"""節流＋重試的 HTTP 用戶端。所有來源共用一個全域節流時間戳（請求間隔 ≥ MIN_INTERVAL 秒）。"""

import time
from typing import Any

import requests

MIN_INTERVAL = 3.0
RETRIES = 3
TIMEOUT = 30
BACKOFF = (5, 15, 45)
_HEADERS = {"User-Agent": "Mozilla/5.0"}

_session = requests.Session()
_last_request: float | None = None


class SourceError(Exception):
    """資料來源請求或解析失敗。"""


def _snip(s: str, n: int = 200) -> str:
    return s[:n]


def _throttle() -> None:
    global _last_request
    if _last_request is not None:
        wait = MIN_INTERVAL - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
    _last_request = time.monotonic()


def _fetch(url: str, handle, accept_404: bool = False):
    """通用重試迴圈。handle(resp) 回傳結果，或拋 ValueError 表示此次視為失敗。"""
    global _last_request
    last = "unknown"
    for attempt in range(RETRIES):
        _throttle()
        try:
            resp = _session.get(url, headers=_HEADERS, timeout=TIMEOUT)
            _last_request = time.monotonic()
            if resp.status_code == 404 and accept_404:
                return None
            if resp.status_code != 200:
                last = f"HTTP {resp.status_code}"
            else:
                return handle(resp)
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {_snip(str(e))}"
            _last_request = time.monotonic()
        except ValueError as e:
            last = str(e)
        if attempt < RETRIES - 1:
            time.sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
    raise SourceError(f"請求失敗 {url}（{RETRIES} 次）：{last}")


def get_json(url: str) -> Any:
    def handle(resp):
        try:
            return resp.json()
        except ValueError:
            raise ValueError(f"回應不是 JSON：{_snip(resp.text)!r}")

    return _fetch(url, handle)


def get_text(url: str, encoding: str) -> str | None:
    return _fetch(url, lambda r: r.content.decode(encoding, errors="replace"), accept_404=True)
