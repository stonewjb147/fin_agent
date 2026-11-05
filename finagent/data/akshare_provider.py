"""AKShare-backed provider with retries, degradation and a Parquet cache.

Reality on this machine (probed 2026-11-05, AKShare 1.18.64):
  * `fund_etf_hist_em` (ETF daily, hfq) works.
  * Eastmoney `push2*.eastmoney.com` endpoints are blocked by the network /
    a dead local proxy (sector flow rank, ETF spot, index_zh_a_hist).
  * Working fallbacks: `stock_zh_index_daily_em` (push2his), CSIndex history,
    THS industry fund flow, Sina ETF snapshot, SSE ETF scale.
The provider encodes these fallbacks explicitly instead of pretending every
endpoint is equally reliable.

Adjusted-price caveat: AKShare computes hfq prices with the latest adjustment
factor, so historical rows are rewritten when a distribution happens. We
therefore refresh the full ETF history rather than appending increments.
"""

from __future__ import annotations

import os
import signal
import threading
import time
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd

from finagent import config
from finagent.data.cache import ParquetCache
from finagent.data.provider import (
    DataNotAvailable,
    ETF_DAILY_COLUMNS,
    ProviderError,
    StaleDataWarning,
)

# Domestic quote hosts are reached directly; the local HTTP proxy is unstable
# and eastmoney's push2 cluster rejects proxied requests.
_NO_PROXY_HOSTS = (
    ".eastmoney.com",
    ".sse.com.cn",
    ".szse.cn",
    ".csindex.com.cn",
    ".10jqka.com.cn",
    ".sina.com.cn",
    ".sinajs.cn",
)

DEFAULT_HISTORY_START = date(2018, 1, 1)

_EM_HISTORY_MAP = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "pct_change",
    "涨跌额": "change",
    "换手率": "turnover",
}


def configure_no_proxy() -> None:
    parts = [p.strip() for p in os.environ.get("NO_PROXY", "").split(",") if p.strip()]
    for host in _NO_PROXY_HOSTS:
        if host not in parts:
            parts.append(host)
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = ",".join(parts)


configure_no_proxy()


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()


def _numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _call_with_timeout(fn: Callable, timeout: float, *args, **kwargs):
    """Bound a blocking HTTP call.

    AKShare passes no timeout to requests, so a stalled endpoint can hang the
    whole daily job. SIGALRM interrupts socket waits on the main thread; when
    unavailable (worker threads, non-POSIX) we fall back to a plain call.
    """
    if timeout <= 0 or threading.current_thread() is not threading.main_thread() or not hasattr(signal, "SIGALRM"):
        return fn(*args, **kwargs)

    def _raise(signum, frame):  # noqa: ANN001
        raise TimeoutError(f"{getattr(fn, '__name__', fn)} exceeded {timeout}s")

    previous = signal.signal(signal.SIGALRM, _raise)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        return fn(*args, **kwargs)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _month_end(periods: pd.Series) -> pd.Series:
    cleaned = (
        periods.astype(str)
        .str.replace("年", "-", regex=False)
        .str.replace("月份", "", regex=False)
        .str.replace("月", "", regex=False)
        .str.strip()
    )
    return pd.to_datetime(cleaned, format="%Y-%m", errors="coerce") + pd.offsets.MonthEnd(0)


class AkshareProvider:
    """Concrete DataProvider. Network calls are isolated in `_fetch_*`."""

    def __init__(
        self,
        cache: ParquetCache | None = None,
        *,
        retries: int = 2,
        backoff: float = 1.0,
        timeout: float = 20.0,
        today: date | None = None,
        history_start: date = DEFAULT_HISTORY_START,
    ):
        self.cache = cache or ParquetCache(config.CACHE_DIR)
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout
        self._today = today or date.today()
        self.history_start = history_start

    # ------------------------------------------------------------------
    # infrastructure
    # ------------------------------------------------------------------
    def _call(self, fn: Callable, *args, **kwargs):
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                return _call_with_timeout(fn, self.timeout, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - source errors are heterogeneous
                last = exc
                if attempt < self.retries:
                    time.sleep(self.backoff * (2**attempt))
        raise ProviderError(f"{getattr(fn, '__name__', fn)} failed after retries: {last}") from last

    def _cached_fetch(
        self,
        dataset: str,
        key: str,
        *,
        params: dict,
        fetch: Callable[[], pd.DataFrame],
        date_column: str = "date",
        skip_if_fetched_today: bool = True,
        force: bool = False,
    ) -> pd.DataFrame:
        """Return cached data if fresh, otherwise fetch and write.

        On a failed fetch we fall back to the previous cached frame and raise a
        StaleDataWarning; only a cold cache turns the failure into an error.
        """
        manifest = self.cache.manifest(dataset, key)
        same_request = manifest is not None and manifest.params.get("request") == params
        fetched_today = manifest is not None and manifest.fetched_on == self._today

        if not force and same_request and (fetched_today or not skip_if_fetched_today):
            cached = self.cache.read(dataset, key)
            if cached is not None:
                return self._tag(cached, stale=False, manifest=manifest)

        try:
            frame = fetch()
            if frame is None or frame.empty:
                raise ProviderError(f"{dataset}/{key} returned no rows")
            manifest = self.cache.write(
                dataset,
                key,
                frame,
                source=self._source_name(dataset),
                params={"request": params},
                date_column=date_column,
            )
            return self._tag(frame, stale=False, manifest=manifest)
        except Exception:
            cached = self.cache.read(dataset, key)
            if cached is None:
                raise
            warnings.warn(
                f"{dataset}/{key}: fetch failed, using cached data from "
                f"{manifest.last_date if manifest else 'unknown'}",
                StaleDataWarning,
                stacklevel=2,
            )
            return self._tag(cached, stale=True, manifest=manifest)

    @staticmethod
    def _tag(df: pd.DataFrame, *, stale: bool, manifest) -> pd.DataFrame:
        df = df.copy()
        df.attrs["stale"] = stale
        df.attrs["last_date"] = manifest.last_date if manifest else None
        df.attrs["fetched_at"] = manifest.fetched_at if manifest else None
        return df

    @staticmethod
    def _source_name(dataset: str) -> str:
        return {
            "etf_daily_hfq": "akshare.fund_etf_hist_em",
            "etf_nav": "eastmoney.api.fund.lsjz",
            "etf_spot": "akshare.fund_etf_category_sina",
            "etf_scale_sse": "akshare.fund_etf_scale_sse",
            "index_daily": "akshare.stock_zh_index_daily_em",
            "index_valuation": "akshare.stock_zh_index_hist_csindex",
            "index_value_snapshot": "akshare.stock_zh_index_value_csindex",
            "sector_flow_rank": "akshare.stock_fund_flow_industry (THS)",
            "market_flow": "akshare.stock_market_fund_flow",
            "margin_sse": "akshare.stock_margin_sse",
            "trade_calendar": "akshare.tool_trade_date_hist_sina",
            "macro": "akshare.macro_china_*",
            "bond_yield": "akshare.bond_zh_us_rate",
        }.get(dataset, "akshare")

    # ------------------------------------------------------------------
    # ETF daily / NAV / snapshot / scale
    # ------------------------------------------------------------------
    def etf_daily(
        self,
        symbols: list[str],
        start: date,
        end: date,
        *,
        force: bool = False,
    ) -> pd.DataFrame:
        frames = [self._etf_daily_one(s, start, end, force=force) for s in symbols]
        frames = [f for f in frames if not f.empty]
        if not frames:
            raise ProviderError("no ETF daily data returned")
        out = pd.concat(frames, ignore_index=True)
        out["date"] = pd.to_datetime(out["date"])
        out = out[(out["date"].dt.date >= start) & (out["date"].dt.date <= end)]
        return out.sort_values(["date", "symbol"]).reset_index(drop=True)

    def _etf_daily_one(self, symbol: str, start: date, end: date, *, force: bool) -> pd.DataFrame:
        start = max(start, self.history_start)
        params = {"start": _ymd(start), "end": _ymd(end), "adjust": "hfq"}

        def fetch() -> pd.DataFrame:
            import akshare as ak

            raw = self._call(
                ak.fund_etf_hist_em,
                symbol=symbol,
                period="daily",
                start_date=params["start"],
                end_date=params["end"],
                adjust="hfq",
            )
            return self.normalize_etf_history(raw, symbol)

        return self._cached_fetch(
            "etf_daily_hfq", symbol, params=params, fetch=fetch, force=force
        )

    @staticmethod
    def normalize_etf_history(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame(columns=ETF_DAILY_COLUMNS)
        df = raw.rename(columns=_EM_HISTORY_MAP)
        df["symbol"] = str(symbol).zfill(6)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        keep = [c for c in ETF_DAILY_COLUMNS if c in df.columns]
        df = df[keep]
        df = _numeric(
            df,
            ["open", "close", "high", "low", "volume", "amount", "amplitude", "pct_change", "change", "turnover"],
        )
        df = df.dropna(subset=["date", "close"])
        return df.sort_values("date").reset_index(drop=True)

    def etf_nav(self, symbol: str, start: date, end: date, *, force: bool = False) -> pd.DataFrame:
        """Unit NAV history. The upstream AKShare helper breaks on a column
        count change, so we call the same endpoint and normalise ourselves."""
        params = {"start": _ymd(start), "end": _ymd(end), "kind": "nav"}

        def fetch() -> pd.DataFrame:
            return self._fetch_nav_em(symbol, start, end)

        return self._cached_fetch("etf_nav", symbol, params=params, fetch=fetch, force=force)

    def _fetch_nav_em(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        import math
        import time as _time

        import requests

        url = "https://api.fund.eastmoney.com/f10/lsjz"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Referer": f"https://fundf10.eastmoney.com/jjjz_{symbol}.html",
        }
        base = {
            "fundCode": symbol,
            "pageIndex": "1",
            "pageSize": "50",
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "_": int(_time.time() * 1000),
        }
        first = requests.get(url, params=base, headers=headers, timeout=20).json()
        total = int(first.get("TotalCount") or 0)
        if total == 0:
            return pd.DataFrame(columns=["date", "symbol", "unit_nav", "acc_nav", "daily_return"])
        rows = list(first.get("Data", {}).get("LSJZList", []))
        pages = math.ceil(total / 50)
        for page in range(2, pages + 1):
            payload = dict(base, pageIndex=str(page))
            rows.extend(
                requests.get(url, params=payload, headers=headers, timeout=20).json().get("Data", {}).get("LSJZList", [])
            )
        df = pd.DataFrame(rows)
        if df.empty:
            return pd.DataFrame(columns=["date", "symbol", "unit_nav", "acc_nav", "daily_return"])
        df = df.rename(
            columns={
                "FSRQ": "date",
                "DWJZ": "unit_nav",
                "LJJZ": "acc_nav",
                "JZZZL": "daily_return",
            }
        )
        df["symbol"] = str(symbol).zfill(6)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = _numeric(df, ["unit_nav", "acc_nav", "daily_return"])
        return df[["date", "symbol", "unit_nav", "acc_nav", "daily_return"]].dropna(subset=["date"])

    def etf_snapshot(self, as_of: date) -> pd.DataFrame:
        """Current ETF quotes. Eastmoney's spot endpoint is blocked here, so we
        use Sina; it lacks IOPV/premium, which is recorded as a limitation."""
        params = {"as_of": as_of.isoformat()}

        def fetch() -> pd.DataFrame:
            import akshare as ak

            raw = self._call(ak.fund_etf_category_sina, symbol="ETF基金")
            return self.normalize_etf_spot(raw, as_of)

        return self._cached_fetch("etf_spot", as_of.isoformat(), params=params, fetch=fetch)

    @staticmethod
    def normalize_etf_spot(raw: pd.DataFrame, as_of: date) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame()
        df = raw.rename(
            columns={
                "代码": "raw_symbol",
                "名称": "name",
                "最新价": "price",
                "涨跌幅": "pct_change",
                "昨收": "prev_close",
                "今开": "open",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
            }
        )
        df["symbol"] = df["raw_symbol"].astype(str).str.extract(r"(\d{6})")[0]
        df["date"] = pd.Timestamp(as_of)
        df = _numeric(df, ["price", "pct_change", "prev_close", "open", "high", "low", "volume", "amount"])
        cols = ["date", "symbol", "name", "price", "pct_change", "prev_close", "open", "high", "low", "volume", "amount"]
        return df[[c for c in cols if c in df.columns]].dropna(subset=["symbol"])

    def etf_scale_sse(self, as_of: date) -> pd.DataFrame:
        params = {"as_of": as_of.isoformat()}

        def fetch() -> pd.DataFrame:
            import akshare as ak

            raw = self._call(ak.fund_etf_scale_sse, date=_ymd(as_of))
            df = raw.rename(
                columns={
                    "基金代码": "symbol",
                    "基金简称": "name",
                    "统计日期": "date",
                    "基金份额": "shares",
                }
            )
            df["symbol"] = df["symbol"].astype(str).str.zfill(6)
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = _numeric(df, ["shares"])
            return df[["date", "symbol", "name", "shares"]].dropna(subset=["date"])

        return self._cached_fetch("etf_scale_sse", as_of.isoformat(), params=params, fetch=fetch)

    # ------------------------------------------------------------------
    # index daily / valuation
    # ------------------------------------------------------------------
    @staticmethod
    def index_symbol(index_code: str) -> str:
        code = str(index_code).strip()
        if code[:2].lower() in ("sh", "sz", "csi"):
            return code
        if code.startswith(("399", "159")):
            return f"sz{code}"
        if code.startswith(("93", "H3", "h3")):
            return f"csi{code}"
        return f"sh{code}"

    def index_daily(self, index_code: str, start: date, end: date, *, force: bool = False) -> pd.DataFrame:
        code = str(index_code).zfill(6) if str(index_code).isdigit() else str(index_code)
        params = {"start": _ymd(start), "end": _ymd(end), "index": code}

        def fetch() -> pd.DataFrame:
            import akshare as ak

            raw = self._call(
                ak.stock_zh_index_daily_em,
                symbol=self.index_symbol(code),
                start_date=_ymd(start),
                end_date=_ymd(end),
            )
            if raw is None or raw.empty:
                raise DataNotAvailable(f"index daily not available for {code}")
            df = raw.copy()
            df["index_code"] = code
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = _numeric(df, ["open", "close", "high", "low", "volume", "amount"])
            cols = ["date", "index_code", "open", "close", "high", "low", "volume", "amount"]
            return df[[c for c in cols if c in df.columns]].dropna(subset=["date", "close"])

        return self._cached_fetch("index_daily", code, params=params, fetch=fetch, force=force)

    def index_valuation(self, index_code: str, start: date, end: date, *, force: bool = False) -> pd.DataFrame:
        """CSIndex history includes rolling PE. PB/dividend yield are only
        available as a short recent snapshot on the free source, so they are
        returned as NaN rather than fabricated."""
        code = str(index_code).zfill(6)
        params = {"start": _ymd(start), "end": _ymd(end), "index": code}

        def fetch() -> pd.DataFrame:
            import akshare as ak

            raw = self._call(
                ak.stock_zh_index_hist_csindex,
                symbol=code,
                start_date=_ymd(start),
                end_date=_ymd(end),
            )
            return self.normalize_csindex_valuation(raw, code)

        return self._cached_fetch("index_valuation", code, params=params, fetch=fetch, force=force)

    @staticmethod
    def normalize_csindex_valuation(raw: pd.DataFrame, index_code: str) -> pd.DataFrame:
        if raw is None or raw.empty:
            raise DataNotAvailable(f"CSIndex valuation empty for {index_code}")
        df = raw.rename(
            columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交金额": "amount",
                "涨跌幅": "pct_change",
                "滚动市盈率": "pe",
            }
        )
        df["index_code"] = str(index_code).zfill(6)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        for col in ("pb", "dividend_yield"):
            if col not in df.columns:
                df[col] = pd.NA
        df = _numeric(df, ["open", "close", "high", "low", "volume", "amount", "pct_change", "pe", "pb", "dividend_yield"])
        cols = ["date", "index_code", "open", "close", "high", "low", "volume", "amount", "pct_change", "pe", "pb", "dividend_yield"]
        return df[[c for c in cols if c in df.columns]].dropna(subset=["date", "close"])

    def index_value_snapshot(self, index_code: str, as_of: date) -> pd.DataFrame:
        """Recent PE/dividend-yield snapshot (about 20 rows), accumulated daily."""
        code = str(index_code).zfill(6)
        params = {"symbol": code}

        def fetch() -> pd.DataFrame:
            import akshare as ak

            raw = self._call(ak.stock_zh_index_value_csindex, symbol=code)
            return self.normalize_index_value_snapshot(raw, code)

        # one snapshot per index per day; the payload itself covers ~20 days
        return self._cached_fetch(
            "index_value_snapshot", f"{code}_{as_of.isoformat()}", params=params, fetch=fetch
        )

    @staticmethod
    def normalize_index_value_snapshot(raw: pd.DataFrame, index_code: str) -> pd.DataFrame:
        """Map the CSIndex value API onto the canonical valuation schema.

        `市盈率1`/`市盈率2` are static and rolling (TTM) PE respectively, so
        `pe` takes the rolling series; `pe_static` is kept for reference. The
        endpoint publishes no PB, so `pb` is NaN rather than inferred.
        """
        if raw is None or raw.empty:
            raise DataNotAvailable(f"CSIndex value snapshot empty for {index_code}")
        df = raw.rename(
            columns={
                "日期": "date",
                "市盈率1": "pe_static",
                "市盈率2": "pe_lyr",
                "股息率1": "dividend_yield",
                "股息率2": "dividend_yield2",
            }
        )
        df["index_code"] = str(index_code).zfill(6)
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = _numeric(df, ["pe_static", "pe_lyr", "dividend_yield", "dividend_yield2"])
        df["pe"] = df.get("pe_lyr")
        df["pb"] = float("nan")
        cols = [
            "date",
            "index_code",
            "pe",
            "pe_static",
            "pe_lyr",
            "pb",
            "dividend_yield",
            "dividend_yield2",
        ]
        return df[[c for c in cols if c in df.columns]].dropna(subset=["date"])

    # ------------------------------------------------------------------
    # flows, margin, macro, yields
    # ------------------------------------------------------------------
    def sector_flow_rank(self, as_of: date, indicator: str = "即时") -> pd.DataFrame:
        params = {"as_of": as_of.isoformat(), "indicator": indicator}

        def fetch() -> pd.DataFrame:
            import akshare as ak

            raw = self._call(ak.stock_fund_flow_industry, symbol=indicator)
            if raw is None or raw.empty:
                raise DataNotAvailable("THS industry flow empty")
            df = raw.rename(
                columns={
                    "行业": "sector",
                    "行业-涨跌幅": "pct_change",
                    "净额": "net_inflow",
                    "流入资金": "inflow",
                    "流出资金": "outflow",
                    "公司家数": "company_count",
                }
            )
            df["date"] = pd.Timestamp(as_of)
            df = _numeric(df, ["pct_change", "net_inflow", "inflow", "outflow", "company_count"])
            cols = ["date", "sector", "pct_change", "net_inflow", "inflow", "outflow", "company_count"]
            return df[[c for c in cols if c in df.columns]].dropna(subset=["sector"])

        return self._cached_fetch("sector_flow_rank", as_of.isoformat(), params=params, fetch=fetch)

    def sector_flow_hist(self, sector: str, start: date, end: date) -> pd.DataFrame:
        raise DataNotAvailable(
            "Per-sector fund-flow history is unavailable: the Eastmoney push2 "
            "endpoint is unreachable and THS only publishes ranking snapshots. "
            "Use accumulated sector_flow_rank snapshots instead."
        )

    def market_flow(self, start: date, end: date, *, force: bool = False) -> pd.DataFrame:
        params = {"start": _ymd(start), "end": _ymd(end)}

        def fetch() -> pd.DataFrame:
            import akshare as ak

            raw = self._call(ak.stock_market_fund_flow)
            df = raw.rename(
                columns={
                    "日期": "date",
                    "上证-收盘价": "sh_close",
                    "上证-涨跌幅": "sh_pct",
                    "深证-收盘价": "sz_close",
                    "深证-涨跌幅": "sz_pct",
                    "主力净流入-净额": "main_net_inflow",
                    "主力净流入-净占比": "main_net_inflow_pct",
                    "超大单净流入-净额": "super_large_net_inflow",
                    "大单净流入-净额": "large_net_inflow",
                    "中单净流入-净额": "medium_net_inflow",
                    "小单净流入-净额": "small_net_inflow",
                }
            )
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = _numeric(
                df,
                [
                    "sh_close", "sh_pct", "sz_close", "sz_pct", "main_net_inflow",
                    "main_net_inflow_pct", "super_large_net_inflow", "large_net_inflow",
                    "medium_net_inflow", "small_net_inflow",
                ],
            )
            cols = [
                "date", "sh_close", "sh_pct", "sz_close", "sz_pct", "main_net_inflow",
                "main_net_inflow_pct", "super_large_net_inflow", "large_net_inflow",
                "medium_net_inflow", "small_net_inflow",
            ]
            return df[[c for c in cols if c in df.columns]].dropna(subset=["date"])

        return self._cached_fetch("market_flow", "cn", params=params, fetch=fetch, force=force)

    def margin_sse(self, start: date, end: date, *, force: bool = False) -> pd.DataFrame:
        params = {"start": _ymd(start), "end": _ymd(end)}

        def fetch() -> pd.DataFrame:
            import akshare as ak

            raw = self._call(ak.stock_margin_sse, start_date=_ymd(start), end_date=_ymd(end))
            df = raw.rename(
                columns={
                    "信用交易日期": "date",
                    "融资余额": "financing_balance",
                    "融资买入额": "financing_buy",
                    "融券余量": "securities_balance_volume",
                    "融券余量金额": "securities_balance_value",
                    "融券卖出量": "securities_sell_volume",
                    "融资融券余额": "margin_balance",
                }
            )
            df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")
            df = _numeric(df, ["financing_balance", "financing_buy", "margin_balance"])
            return df.dropna(subset=["date"])

        return self._cached_fetch("margin_sse", "sse", params=params, fetch=fetch, force=force)

    def trade_calendar(self, *, force: bool = False) -> pd.DataFrame:
        params = {"kind": "sina"}

        def fetch() -> pd.DataFrame:
            import akshare as ak

            raw = self._call(ak.tool_trade_date_hist_sina)
            df = raw.rename(columns={"trade_date": "date"})
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

        # calendar changes once a year; refresh at most weekly
        return self._cached_fetch(
            "trade_calendar", "all", params=params, fetch=fetch, skip_if_fetched_today=False, force=force
        )

    def is_trading_day(self, day: date) -> bool:
        cal = self.trade_calendar()
        return pd.Timestamp(day) in set(cal["date"])

    def last_trading_day(self, as_of: date | None = None) -> date:
        as_of = as_of or self._today
        cal = self.trade_calendar()
        candidates = cal.loc[cal["date"] <= pd.Timestamp(as_of), "date"]
        if candidates.empty:
            raise ProviderError("trade calendar has no date <= as_of")
        return candidates.max().date()

    def macro(self, name: str, *, force: bool = False) -> pd.DataFrame:
        """Normalised macro series: date (reference period), name, value,
        available_at (period end + publication lag)."""
        if name not in config.MACRO_PUBLICATION_LAG_DAYS:
            raise DataNotAvailable(f"unknown macro series: {name}")
        params = {"series": name}

        def fetch() -> pd.DataFrame:
            return self._fetch_macro(name)

        return self._cached_fetch("macro", name, params=params, fetch=fetch, force=force)

    def _fetch_macro(self, name: str) -> pd.DataFrame:
        """Normalise to period_end / available_at.

        Monthly series are aligned to month end and delayed by the publication
        lag; using the reference period directly would leak future information
        into the as_of panel. LPR is published on its quote date, so that date
        is both the period end and the availability date.
        """
        import akshare as ak

        lag = config.MACRO_PUBLICATION_LAG_DAYS[name]
        if name == "pmi":
            raw = self._call(ak.macro_china_pmi)
            df = raw.rename(columns={"月份": "period", "制造业-指数": "value"})[["period", "value"]]
            period_end = _month_end(df["period"])
        elif name == "cpi":
            raw = self._call(ak.macro_china_cpi)
            df = raw.rename(columns={"月份": "period", "全国-同比增长": "value"})[["period", "value"]]
            period_end = _month_end(df["period"])
        elif name == "ppi":
            raw = self._call(ak.macro_china_ppi)
            df = raw.rename(columns={"月份": "period", "当月同比增长": "value"})[["period", "value"]]
            period_end = _month_end(df["period"])
        elif name == "m2":
            raw = self._call(ak.macro_china_money_supply)
            df = raw.rename(columns={"月份": "period", "货币和准货币(M2)-同比增长": "value"})[["period", "value"]]
            period_end = _month_end(df["period"])
        elif name == "lpr":
            raw = self._call(ak.macro_china_lpr)
            df = raw.rename(columns={"TRADE_DATE": "date", "LPR1Y": "value"})[["date", "value"]]
            period_end = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
            lag = 0
        else:
            raise DataNotAvailable(f"macro series {name} not implemented")

        out = pd.DataFrame(
            {
                "date": period_end,
                "period_end": period_end,
                "name": name,
                "value": pd.to_numeric(df["value"], errors="coerce"),
            }
        )
        out["available_at"] = out["period_end"] + pd.to_timedelta(lag, unit="D")
        out = out.dropna(subset=["period_end", "value"])
        return out.sort_values("period_end").reset_index(drop=True)

    def bond_yield(self, start: date, end: date, *, force: bool = False) -> pd.DataFrame:
        params = {"start": _ymd(start), "end": _ymd(end)}

        def fetch() -> pd.DataFrame:
            import akshare as ak

            raw = self._call(ak.bond_zh_us_rate, start_date=_ymd(start))
            df = raw.rename(columns={"日期": "date", "中国国债收益率10年": "y10"})
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df["y10"] = pd.to_numeric(df["y10"], errors="coerce")
            df = df[["date", "y10"]].dropna(subset=["date"])
            df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
            return df.dropna(subset=["y10"]).reset_index(drop=True)

        return self._cached_fetch("bond_yield", "cn10y", params=params, fetch=fetch, force=force)


def default_provider(**kwargs) -> AkshareProvider:
    config.ensure_dirs()
    return AkshareProvider(ParquetCache(config.CACHE_DIR), **kwargs)
