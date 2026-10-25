"""櫃買中心（上櫃＋興櫃）回應解析。僅含純 parse 函式；fetch_* 見檔尾。"""

from datetime import date

from sync import http
from sync.models import ExRight, InstFlow, Quote
from sync.parse import change_pct, parse_number, roc_to_date


def _rows(payload: dict) -> list:
    tables = payload.get("tables") or []
    if not tables:
        return []
    return tables[0].get("data") or []


def parse_quotes(payload: dict, d: date) -> list[Quote]:
    """上櫃日行情。漲跌欄為帶號字串；除權息日為中文（除息等）、無成交為 ---，皆視為缺值 None。"""
    out = []
    for r in _rows(payload):
        close = parse_number(r[2])
        change = parse_number(r[3]) if close is not None else None
        out.append(Quote(
            stock_id=r[0].strip(),
            name=r[1].strip(),
            trade_date=d,
            market="上櫃",
            open=parse_number(r[4]),
            high=parse_number(r[5]),
            low=parse_number(r[6]),
            close=close,
            change=change,
            change_pct=change_pct(change, close),
            volume=parse_number(r[8]),
        ))
    return out


def parse_institutional(payload: dict, d: date) -> list[InstFlow]:
    """上櫃三大法人：買賣超欄 4（外資不含外資自營商）、13（投信）、22（自營商合計）、23（三大法人合計）。"""
    return [
        InstFlow(
            stock_id=r[0].strip(),
            trade_date=d,
            foreign_net=parse_number(r[4]),
            trust_net=parse_number(r[13]),
            dealer_net=parse_number(r[22]),
            total_net=parse_number(r[23]),
        )
        for r in _rows(payload)
    ]


def parse_ex_rights(payload: dict) -> list[ExRight]:
    """上櫃除權息：種類已是 除權／除息／除權息，僅 strip。"""
    return [
        ExRight(
            stock_id=r[1].strip(),
            ex_date=roc_to_date(r[0]),
            kind=r[8].strip(),
            prev_close=parse_number(r[3]),
            ref_price=parse_number(r[4]),
            total_value=parse_number(r[7]),
        )
        for r in _rows(payload)
    ]


def parse_emerging(payload: list) -> list[Quote]:
    """興櫃當日行情（openapi，只有最新一日）。漲跌 = 最新價 − 前日均價；漲跌幅以前日均價為分母。"""
    out = []
    for r in payload or []:
        close = parse_number(r.get("LatestPrice"))
        prev = parse_number(r.get("PreviousAveragePrice"))
        change = round(close - prev, 4) if close is not None and prev is not None else None
        out.append(Quote(
            stock_id=r["SecuritiesCompanyCode"].strip(),
            name=r["CompanyName"].strip(),
            trade_date=roc_to_date(r["Date"]),
            market="興櫃",
            open=None,
            high=parse_number(r.get("Highest")),
            low=parse_number(r.get("Lowest")),
            close=close,
            change=change,
            change_pct=change_pct(change, close),
            volume=parse_number(r.get("TransactionVolume")),
        ))
    return out


_BASE = "https://www.tpex.org.tw"


def _parsed(url: str, fn, *args):
    """取 JSON 並解析；版面變動造成的解析錯誤轉成 SourceError，讓排程明確失敗。"""
    payload = http.get_json(url)
    try:
        return fn(payload, *args)
    except (IndexError, KeyError, ValueError, TypeError) as e:
        raise http.SourceError(f"解析失敗 {url}：{type(e).__name__}: {str(e)[:200]}") from e


def fetch_quotes(d: date) -> list[Quote]:
    url = f"{_BASE}/www/zh-tw/afterTrading/dailyQuotes?date={d:%Y/%m/%d}&response=json"
    return _parsed(url, parse_quotes, d)


def fetch_institutional(d: date) -> list[InstFlow]:
    url = f"{_BASE}/www/zh-tw/insti/dailyTrade?type=Daily&sect=AL&date={d:%Y/%m/%d}&response=json"
    return _parsed(url, parse_institutional, d)


def fetch_ex_rights(start: date, end: date) -> list[ExRight]:
    url = f"{_BASE}/www/zh-tw/bulletin/exDailyQ?startDate={start:%Y/%m/%d}&endDate={end:%Y/%m/%d}&response=json"
    return _parsed(url, parse_ex_rights)


def fetch_emerging() -> list[Quote]:
    return _parsed(f"{_BASE}/openapi/v1/tpex_esb_latest_statistics", parse_emerging)
