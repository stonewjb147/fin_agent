#!/usr/bin/env python
"""Cron entry point: collect the latest trading day and report status."""

from __future__ import annotations

import argparse
import json
from datetime import date

from finagent import config
from finagent.data.akshare_provider import default_provider
from finagent.data.collect import collect
from finagent.data.universe import load_universe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None, help="defaults to 3 years before end")
    ap.add_argument("--end", default=None)
    ap.add_argument("--snapshots", choices=["auto", "on", "off"], default="auto")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    provider = default_provider()
    end = date.fromisoformat(args.end) if args.end else provider.last_trading_day()
    start = date.fromisoformat(args.start) if args.start else date(end.year - 3, 1, 1)
    universe = load_universe(config.CONFIG_DIR / "universe.yaml")

    result = collect(provider, universe, start, end, snapshots=args.snapshots, force=args.force)
    print(json.dumps({k: v for k, v in result.to_dict().items() if k != "datasets"}, ensure_ascii=False, indent=2))

    errors = [f for f in result.failures if f["kind"] == "error"]
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
