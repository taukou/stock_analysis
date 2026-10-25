"""證交所（上市）回應解析。僅含純 parse 函式；fetch_* 見檔尾。"""

import re
from datetime import date

from sync import http
from sync.models import ExRight, InstFlow, Quote
from sync.parse import change_pct, parse_number, parse_twse_sign, roc_to_date

_TAG_RE = re.compile(r"<[^>]*>")
_KIND = {"息": "除息", "權": "除權", "權息": "除權息"}


def _find_quote_table(payload: dict) -> dict | None:
    for t in payload.get("tables") or []:
        fields = t.get("fields") or []
        if len(fields) == 16 and fields[0] == "證券代號":
            return t
    return None


def _quote_change(sign_raw: str, diff_raw: str, close):
    """漲跌價差：有正負號才有值；除權息日（X）與無成交為 None；收盤有值且符號空白、價差 0 視為平盤 0。"""
    diff = parse_number(diff_raw)
    if close is None or diff is None:
        return None
    sign = parse_twse_sign(sign_raw)
    if sign is not None:
        return sign * abs(diff)
    if _TAG_RE.sub("", sign_raw).strip() == "" and diff == 0:
        return 0.0
    return None


def parse_quotes(payload: dict, d: date) -> list[Quote]:
    table = _find_quote_table(payload)
    if table is None:
        return []
    out = []
    for r in table.get("data") or []:
        close = parse_number(r[8])
        change = _quote_change(r[9], r[10], close)
        out.append(Quote(
            stock_id=r[0].strip(),
            name=r[1].strip(),
            trade_date=d,
            market="上市",
            open=parse_number(r[5]),
            high=parse_number(r[6]),
            low=parse_number(r[7]),
            close=close,
            change=change,
            change_pct=change_pct(change, close),
            volume=parse_number(r[2]),
        ))
    return out


def parse_institutional(payload: dict, d: date) -> list[InstFlow]:
    return [
        InstFlow(
            stock_id=r[0].strip(),
            trade_date=d,
            foreign_net=parse_number(r[4]),
            trust_net=parse_number(r[10]),
            dealer_net=parse_number(r[11]),
            total_net=parse_number(r[18]),
        )
        for r in payload.get("data") or []
    ]


def parse_ex_rights(payload: dict) -> list[ExRight]:
    out = []
    for r in payload.get("data") or []:
        kind = r[6].strip()
        out.append(ExRight(
            stock_id=r[1].strip(),
            ex_date=roc_to_date(r[0]),
            kind=_KIND.get(kind, kind),
            prev_close=parse_number(r[3]),
            ref_price=parse_number(r[4]),
            total_value=parse_number(r[5]),
        ))
    return out


_BASE = "https://www.twse.com.tw/rwd/zh"



def fetch_quotes(d: date) -> list[Quote]:
    url = f"{_BASE}/afterTrading/MI_INDEX?date={d:%Y%m%d}&type=ALLBUT0999&response=json"
    return http.parse_with(url, parse_quotes, http.get_json(url), d)


def fetch_institutional(d: date) -> list[InstFlow]:
    url = f"{_BASE}/fund/T86?date={d:%Y%m%d}&selectType=ALL&response=json"
    return http.parse_with(url, parse_institutional, http.get_json(url), d)


def fetch_ex_rights(start: date, end: date) -> list[ExRight]:
    url = f"{_BASE}/exRight/TWT49U?startDate={start:%Y%m%d}&endDate={end:%Y%m%d}&response=json"
    return http.parse_with(url, parse_ex_rights, http.get_json(url))
