#!/usr/bin/env python
"""Screen the whole ETF market down to a ~50-name research universe.

The screen is deliberately mechanical so the output can be reviewed and then
hand-maintained in `configs/universe.yaml`:

1. liquidity filter on the spot snapshot (free sources list ~1700 ETFs, most
   of which are too thin to trade or too young to have a factor history);
2. listing-history filter (>= MIN_DAYS_LISTED trading days);
3. duplicate-exposure filter in two passes: same-name products of one index
   (name family), then 60-day return correlation >= 0.99. Without this the
   cross-section is fake breadth — nine semiconductor ETFs with one exposure;
4. category quotas so one theme cannot dominate the universe.

Surviving pairs above 0.95 are printed as warnings: those are different enough
to keep but close enough that a human should look before confirming.

Usage:
    python scripts/screen_universe.py --date 2026-11-05

Writes data/quality/universe_candidates.csv and prints a summary table.
Network access is needed for the per-symbol history; the raw history goes to a
scratch cache (data/cache_screen) so the real cache stays clean.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from finagent import config
from finagent.data.akshare_provider import AkshareProvider
from finagent.data.cache import ParquetCache

# Quotas: ~50 names in total. Bond gets a small fixed share because dozens of
# near-identical credit products would otherwise flood the liquidity ranking
# and contribute no cross-sectional information.
QUOTAS = {
    "broad": 12,
    "sector": 20,
    "thematic": 6,
    "cross_border": 6,
    "commodity": 2,
    "bond": 4,
}

# Bond families in preference order: duration first, then the credit and
# equity-linked products that behave differently from government paper.
BOND_PRIORITY = ("十年国债", "30年国债", "可转债", "公司债", "国债", "政金债", "信用债", "科创债")

# Money-market products: not investable for a factor strategy (return is
# essentially a step function) and they dominate turnover.
EXCLUDE_KEYWORDS = ("货币", "短融", "现金", "添益", "日利", "保证金", "理财", "快线")

MIN_SPOT_AMOUNT = 1e8  # 1亿元 daily turnover
HISTORY_START = date(2022, 1, 1)

# (regex, category) — first match wins, so bond and commodity come before the
# broad/sector patterns that would otherwise claim 黄金股 or 国债.
CATEGORY_RULES: list[tuple[str, str]] = [
    (r"债", "bond"),
    (r"黄金|白银|豆粕|原油|有色期货|能源化工|商品", "commodity"),
    (r"恒生|港股|香港|中韩|纳指|纳斯达克|标普|道琼斯|中概|日经|德国|法国|东南亚|沙特|印度|越南|海外|亚太", "cross_border"),
    # Theme names come before broad ones: '创业板人工智能' is a theme, not
    # another 创业板 product.
    (r"人工智能|机器人|游戏|传媒|新能源车|光伏|芯片|军工|创新药|云计算|大数据|5G|碳中和|ESG|红利|低波|价值|成长|质量|央企|国企", "thematic"),
    (r"沪深300|中证500|中证1000|中证2000|中证A50|中证A500|中证100|上证50|上证180|上证指数|上证综指|深证100|创业板|科创50|科创100|MSCI|全指|A500|1000|500", "broad"),
]

# Industry ETFs are usually named after a THS industry. This list only drives
# the category proposal; the final YAML is reviewed by hand.
SECTOR_KEYWORDS = (
    "证券|银行|保险|半导体|医药|医疗|生物|军工|煤炭|钢铁|有色|化工|建材|地产|"
    "家电|汽车|食品|饮料|农业|养殖|环保|电力|公用|机械|建筑|交通|物流|旅游|"
    "计算机|通信|软件|消费|科技|信息|电子|纺织|零售|传媒|航空|石油|能源"
)

# Index codes we are confident about; other names keep tracked_index empty and
# are marked index_data: false so the collector does not chase a wrong code.
KNOWN_INDEX = {
    "沪深300": "000300",
    "中证500": "000905",
    "中证1000": "000852",
    "中证2000": "932000",
    "中证A500": "000510",
    "中证A50": "930050",
    "上证50": "000016",
    "上证180": "000010",
    "深证100": "399330",
    "创业板指": "399006",
    "创业板": "399006",
    "科创50": "000688",
    "科创100": "000698",
}

# '中证A500ETF国泰' -> '中证A500'; '科创50ETF华泰柏瑞' -> '科创50'
_ETF_SUFFIX = re.compile(r"ETF[一-龥]*$")
_VENDOR = re.compile(r"ETF[一-龥]{2,6}$")

CORR_DUPLICATE = 0.99
CORR_WARN = 0.95
RETURN_WINDOW = 60


@dataclass
class Candidate:
    symbol: str
    name: str
    category: str
    family: str
    amount: float
    avg_amount_60d: float
    days: int
    first_date: date


def clean_name(name: str) -> str:
    """Drop the manager suffix so names stay stable across products.

    The vendor sits after 'ETF' in Chinese ETF names, so '沪深300ETF华泰柏瑞'
    and '沪深300ETF易方达' both become '沪深300ETF'.
    """
    out = _VENDOR.sub("ETF", str(name)).strip()
    return out or str(name)


def index_family(name: str) -> str:
    """Normalise product names that refer to the same underlying index."""
    cleaned = clean_name(name)
    base = _ETF_SUFFIX.sub("", cleaned).strip()
    aliases = {
        "300": "沪深300",
        "沪深300": "沪深300",
        "500": "中证500",
        "中证500": "中证500",
        "1000": "中证1000",
        "中证1000": "中证1000",
        "2000": "中证2000",
        "中证2000": "中证2000",
        "A500": "中证A500",
        "中证A500": "中证A500",
        "A50": "中证A50",
        "中证A50": "中证A50",
        "50": "上证50",
        "上证50": "上证50",
        "创业板": "创业板指",
        "创业板指": "创业板指",
        "科创50": "科创50",
        "科创100": "科创100",
    }
    return aliases.get(base, base)


def infer_category(name: str) -> str:
    for pattern, category in CATEGORY_RULES:
        if re.search(pattern, name):
            return category
    if re.search(SECTOR_KEYWORDS, name):
        return "sector"
    return "thematic"


def load_spot(as_of: date) -> pd.DataFrame:
    path = config.CACHE_DIR / "etf_spot" / f"{as_of.isoformat()}.parquet"
    if not path.exists():
        raise SystemExit(f"missing spot snapshot: {path} (run `collect` for that day first)")
    return pd.read_parquet(path)


def load_history(provider: AkshareProvider, symbol: str, as_of: date) -> pd.DataFrame | None:
    try:
        df = provider.etf_daily([symbol], HISTORY_START, as_of)
    except Exception:
        return None
    return df if not df.empty else None


def screen(as_of: date, limit_candidates: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    spot = load_spot(as_of)
    spot = spot.dropna(subset=["symbol", "amount"])
    liquid = spot[~spot["name"].str.contains("|".join(EXCLUDE_KEYWORDS), na=False)]
    liquid = liquid[liquid["amount"] >= MIN_SPOT_AMOUNT].sort_values("amount", ascending=False)
    # Cap the network work: names below the top N by turnover cannot pass the
    # liquidity quota anyway.
    liquid = liquid.head(limit_candidates)

    provider = AkshareProvider(cache=ParquetCache(config.DATA_DIR / "cache_screen"))

    rows: list[Candidate] = []
    closes: dict[str, pd.Series] = {}
    for rec in liquid.itertuples(index=False):
        hist = load_history(provider, rec.symbol, as_of)
        if hist is None:
            continue
        hist = hist.sort_values("date")
        days = len(hist)
        if days < config.MIN_DAYS_LISTED:
            continue
        avg_amount = float(hist["amount"].tail(RETURN_WINDOW).mean())
        if avg_amount < config.MIN_AVG_AMOUNT_60D:
            continue
        name = clean_name(rec.name)
        rows.append(
            Candidate(
                symbol=str(rec.symbol),
                name=name,
                category=infer_category(name),
                family=index_family(name),
                amount=float(rec.amount),
                avg_amount_60d=avg_amount,
                days=days,
                first_date=pd.Timestamp(hist["date"].iloc[0]).date(),
            )
        )
        series = hist.set_index(pd.to_datetime(hist["date"]))["close"].astype(float)
        closes[str(rec.symbol)] = series.pct_change().tail(RETURN_WINDOW)

    frame = pd.DataFrame([c.__dict__ for c in rows])
    if frame.empty:
        raise SystemExit("screen produced no candidates; check the spot snapshot and network")

    frame = frame.sort_values("avg_amount_60d", ascending=False)
    # Pass 1: same index, different product.
    frame = frame.drop_duplicates(subset=["category", "family"], keep="first")
    # Pass 2: different name, same exposure. Greedy by liquidity.
    frame = drop_correlated(frame, closes)

    selected = apply_quotas(frame)
    warnings_df = near_duplicates(selected, closes)
    return selected, warnings_df


def drop_correlated(frame: pd.DataFrame, closes: dict[str, pd.Series]) -> pd.DataFrame:
    """Keep the most liquid member of every cluster with corr >= CORR_DUPLICATE."""
    corr = pd.DataFrame(closes).corr()
    keep: list[str] = []
    for symbol in frame["symbol"]:
        if symbol not in corr.columns:
            keep.append(symbol)
            continue
        if keep:
            peer_max = corr.loc[symbol, [k for k in keep if k in corr.columns]].max()
            if pd.notna(peer_max) and peer_max >= CORR_DUPLICATE:
                continue
        keep.append(symbol)
    return frame[frame["symbol"].isin(keep)]


def apply_quotas(frame: pd.DataFrame) -> pd.DataFrame:
    picks = []
    for category, quota in QUOTAS.items():
        subset = frame[frame["category"] == category]
        if category == "bond":
            subset = order_bond_families(subset)
        picks.append(subset.head(quota))
    selected = pd.concat(picks).sort_values(
        ["category", "avg_amount_60d"], ascending=[True, False]
    )
    return selected.reset_index(drop=True)


def order_bond_families(subset: pd.DataFrame) -> pd.DataFrame:
    """One product per bond family, in BOND_PRIORITY order, then the rest."""

    def rank(row: Candidate) -> tuple[int, float]:
        # Exact family match, so 30年国债 is not ranked as plain 国债.
        for position, keyword in enumerate(BOND_PRIORITY):
            if row.family == keyword:
                return position, -row.avg_amount_60d
        return len(BOND_PRIORITY), -row.avg_amount_60d

    ordered = sorted((r for r in subset.itertuples(index=False)), key=rank)
    seen: set[str] = set()
    unique = []
    for row in ordered:
        if row.family in seen:
            continue
        seen.add(row.family)
        unique.append(row)
    return pd.DataFrame([r._asdict() for r in unique])


def near_duplicates(selected: pd.DataFrame, closes: dict[str, pd.Series]) -> pd.DataFrame:
    """Report surviving pairs that are close but were not merged."""
    symbols = [s for s in selected["symbol"] if s in closes]
    if len(symbols) < 2:
        return pd.DataFrame(columns=["a", "b", "corr"])
    corr = pd.DataFrame({s: closes[s] for s in symbols}).corr()
    out = []
    for i, a in enumerate(symbols):
        for b in symbols[i + 1 :]:
            value = corr.loc[a, b]
            if pd.notna(value) and value >= CORR_WARN:
                out.append({"a": a, "b": b, "corr": round(float(value), 4)})
    return pd.DataFrame(out).sort_values("corr", ascending=False)


def to_yaml_entries(selected: pd.DataFrame) -> str:
    lines = []
    for row in selected.itertuples(index=False):
        index_code = KNOWN_INDEX.get(row.family)
        lines.append(f"  - symbol: \"{row.symbol}\"")
        lines.append(f"    name: {row.name}")
        lines.append(f"    category: {row.category}")
        if index_code:
            lines.append(f"    tracked_index: \"{index_code}\"")
        else:
            lines.append("    index_data: false")
        lines.append(f"    effective_from: \"{row.first_date}\"")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="spot snapshot date (default: latest on disk)")
    ap.add_argument("--limit", type=int, default=160, help="max symbols to pull history for")
    ap.add_argument("--out", default="data/quality/universe_candidates.csv")
    args = ap.parse_args()

    as_of = date.fromisoformat(args.date) if args.date else _latest_spot_date()
    selected, warnings_df = screen(as_of, args.limit)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    selected.assign(
        tracked_index=selected["family"].map(KNOWN_INDEX),
        avg_amount_60d_m=selected["avg_amount_60d"] / 1e8,
    ).to_csv(out, index=False)

    print(f"\nScreen as of {as_of}: {len(selected)} candidates -> {out}\n")
    print("by category:", selected.groupby("category").size().to_dict(), "\n")
    for row in selected.itertuples(index=False):
        print(
            f"  {row.category:13s} {row.symbol}  {row.name:18s} "
            f"{row.avg_amount_60d / 1e8:7.2f}亿/日  {row.days:4d}天  {row.family}"
        )

    if not warnings_df.empty:
        print(f"\ncorrelated pairs >= {CORR_WARN} (review for duplicate exposure):")
        for row in warnings_df.itertuples(index=False):
            print(f"  {row.a} ~ {row.b}  corr={row.corr}")

    print("\n--- universe.yaml entries (review before pasting) ---\n")
    print(to_yaml_entries(selected))
    return 0


def _latest_spot_date() -> date:
    files = sorted((config.CACHE_DIR / "etf_spot").glob("*.parquet"))
    if not files:
        raise SystemExit("no etf_spot snapshot found; run `collect` first")
    return date.fromisoformat(files[-1].stem)


if __name__ == "__main__":
    raise SystemExit(main())
