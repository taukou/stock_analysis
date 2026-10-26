"""數值與日期解析：缺值一律回傳 None，絕不以 0 代替。"""

import re
from datetime import date

_NUMBER_RE = re.compile(r"[+-]?\d+(\.\d+)?")
_TAG_RE = re.compile(r"<[^>]*>")
_ROC_PATTERNS = (
    re.compile(r"(\d{2,3})/(\d{1,2})/(\d{1,2})"),
    re.compile(r"(\d{3})(\d{2})(\d{2})"),
    re.compile(r"(\d{2,3})年(\d{1,2})月(\d{1,2})日"),
)


def parse_number(raw: str | None) -> int | float | None:
    """去除逗號與空白後整串比對；不是純數字者（如 --、X、不適用）回傳 None。"""
    if raw is None:
        return None
    s = re.sub(r"[,\s]", "", raw)
    if not _NUMBER_RE.fullmatch(s):
        return None
    return float(s) if "." in s else int(s)


def roc_to_date(s: str) -> date:
    """民國日期轉西元：支援 115/10/22、1151022、115年07月01日。"""
    text = s.strip()
    for pattern in _ROC_PATTERNS:
        m = pattern.fullmatch(text)
        if m:
            year, month, day = (int(g) for g in m.groups())
            return date(year + 1911, month, day)
    raise ValueError(f"無法解析民國日期：{s!r}")


def date_to_roc_month(d: date) -> str:
    """西元日期轉民國年月，例如 2026-09-01 → 115/09。"""
    return f"{d.year - 1911}/{d.month:02d}"


def months_back(today: date, n: int) -> str:
    """today 往前 n 個月的月初，以民國年月表示（跨年安全）。"""
    idx = today.year * 12 + (today.month - 1) - n
    return date_to_roc_month(date(idx // 12, idx % 12 + 1, 1))


def parse_twse_sign(raw: str) -> int | None:
    """解析證交所漲跌價差符號（可能包在 HTML 標籤內）：+ → 1、- → -1，其餘 None。"""
    text = _TAG_RE.sub("", raw).strip()
    if text == "+":
        return 1
    if text == "-":
        return -1
    return None


def change_pct(change: float | None, close: float | None) -> float | None:
    """漲跌幅 (%)，四捨五入至 2 位。以前收盤價 (close - change) 為分母；分母 ≤ 0 或任一為 None 則回傳 None。"""
    if change is None or close is None:
        return None
    prev_close = close - change
    if prev_close <= 0:
        return None
    return round(change / prev_close * 100, 2)
