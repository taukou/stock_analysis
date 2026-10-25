"""資料模型：to_row() 的鍵對應資料表欄位，日期轉 ISO 字串。"""

from dataclasses import dataclass
from datetime import date

Num = float | int | None


@dataclass(frozen=True)
class Quote:
    stock_id: str
    name: str
    trade_date: date
    market: str
    open: Num
    high: Num
    low: Num
    close: Num
    change: Num
    change_pct: Num
    volume: Num

    def to_row(self) -> dict:
        """對應 daily_quotes（name 不是資料表欄位）。"""
        return {
            "stock_id": self.stock_id,
            "trade_date": self.trade_date.isoformat(),
            "market": self.market,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "change": self.change,
            "change_pct": self.change_pct,
            "volume": self.volume,
        }


@dataclass(frozen=True)
class InstFlow:
    stock_id: str
    trade_date: date
    foreign_net: Num
    trust_net: Num
    dealer_net: Num
    total_net: Num

    def to_row(self) -> dict:
        """對應 smart_money_flow。"""
        return {
            "stock_id": self.stock_id,
            "trade_date": self.trade_date.isoformat(),
            "foreign_net": self.foreign_net,
            "trust_net": self.trust_net,
            "dealer_net": self.dealer_net,
            "total_net": self.total_net,
        }


@dataclass(frozen=True)
class ExRight:
    stock_id: str
    ex_date: date
    kind: str
    prev_close: Num
    ref_price: Num
    total_value: Num

    def to_row(self) -> dict:
        """對應 ex_rights。"""
        return {
            "stock_id": self.stock_id,
            "ex_date": self.ex_date.isoformat(),
            "kind": self.kind,
            "prev_close": self.prev_close,
            "ref_price": self.ref_price,
            "total_value": self.total_value,
        }


@dataclass(frozen=True)
class Revenue:
    stock_id: str
    data_month: str
    revenue: Num
    mom_pct: Num
    yoy_pct: Num
    acc_yoy_pct: Num

    def to_row(self) -> dict:
        """對應 growth_momentum。"""
        return {
            "stock_id": self.stock_id,
            "data_month": self.data_month,
            "revenue": self.revenue,
            "mom_pct": self.mom_pct,
            "yoy_pct": self.yoy_pct,
            "acc_yoy_pct": self.acc_yoy_pct,
        }
