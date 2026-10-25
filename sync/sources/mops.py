"""公開資訊觀測站月營收（上市／上櫃／興櫃）解析。僅含純 parse 函式；fetch_* 見檔尾。"""

import html as html_lib
import re
from typing import Literal

from sync import http
from sync.models import Revenue
from sync.parse import parse_number

_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
_CELL_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]*>")
_STOCK_ID_RE = re.compile(r"\d{4,6}")


def _text(cell: str) -> str:
    """去標籤、還原 &nbsp; 等字元並去除前後空白。"""
    return html_lib.unescape(_TAG_RE.sub("", cell)).replace("\xa0", " ").strip()


def parse_revenue(html: str, roc_year: int, month: int) -> list[Revenue]:
    """解析月營收頁。欄：0 代號、2 當月營收、5 上月比較%、6 去年同月%、9 前期比較%。
    只收代號為 4–6 碼數字的列（表頭與合計列自然排除）；非數字的百分比視為缺值 None。"""
    data_month = f"{roc_year}/{month:02d}"
    out = []
    for row in _ROW_RE.findall(html):
        cells = [_text(c) for c in _CELL_RE.findall(row)]
        if len(cells) < 10 or not _STOCK_ID_RE.fullmatch(cells[0]):
            continue
        out.append(Revenue(
            stock_id=cells[0],
            data_month=data_month,
            revenue=parse_number(cells[2]),
            mom_pct=parse_number(cells[5]),
            yoy_pct=parse_number(cells[6]),
            acc_yoy_pct=parse_number(cells[9]),
        ))
    return out


def fetch_revenue(roc_year: int, month: int, market: Literal["sii", "otc", "rotc"]) -> list[Revenue]:
    url = f"https://mopsov.twse.com.tw/nas/t21/{market}/t21sc03_{roc_year}_{month}_0.html"
    text = http.get_text(url, "cp950")
    if text is None:
        return []
    return http.parse_with(url, parse_revenue, text, roc_year, month)
