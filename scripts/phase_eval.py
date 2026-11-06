#!/usr/bin/env python
"""Evaluate Phases 1-4 on the real cache and print the value scorecard.

Read-only with respect to the cache; writes `data/quality/phase_eval_<end>.json`.
Run `--strict` in CI-like settings to fail on any hard check.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from finagent import config
from finagent.backtest.costs import cost_from_bps
from finagent.data.cache import ParquetCache
from finagent.data.universe import load_universe
from finagent.evaluation.report import format_eval, run_phase_eval


def _latest_cached_date(cache_dir: Path) -> date:
    for symbol in ("510300", "511010"):
        frame = ParquetCache(cache_dir).read("etf_daily_hfq", symbol)
        if frame is not None and not frame.empty and "date" in frame.columns:
            return pd.to_datetime(frame["date"]).max().date()
    raise SystemExit("no cached ETF data; run `collect` first")


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 1-4 acceptance and value evaluation")
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default=None, help="defaults to the latest cached date")
    ap.add_argument("--universe", default=None)
    ap.add_argument("--cost-bps", type=float, default=7.0, help="one-way cost in basis points")
    ap.add_argument("--bond", default=None, help="override the 60/40 bond leg")
    ap.add_argument("--out", default=None, help="directory for the JSON report")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any hard check fails")
    args = ap.parse_args()

    universe = load_universe(args.universe or config.CONFIG_DIR / "universe.yaml")
    problems = universe.validate()
    if problems:
        print("Universe validation failed:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    end = date.fromisoformat(args.end) if args.end else _latest_cached_date(config.CACHE_DIR)
    payload = run_phase_eval(
        universe,
        start=date.fromisoformat(args.start),
        end=end,
        cost=cost_from_bps(args.cost_bps),
        bond_symbol=args.bond,
        write=not args.no_write,
        out_dir=args.out,
    )
    print(format_eval(payload))
    failed = payload["summary"]["checks_hard_failed"]
    return 1 if (args.strict and failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
