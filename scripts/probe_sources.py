#!/usr/bin/env python
"""Probe free data sources once and record what actually works.

Free sources change shape without notice, so this script is the ground truth
for the provider layer. It runs every probe in an isolated process with a
timeout (macOS has no coreutils `timeout`) and writes a JSON report.

Usage:
    python scripts/probe_sources.py --out data/quality/source_probe.json
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

# Avoid thread oversubscription in child processes.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("OMP_NUM_THREADS", "1")

TODAY = date.today()
START = (TODAY - timedelta(days=400)).strftime("%Y%m%d")
END = TODAY.strftime("%Y%m%d")


def _probe(fn, args, kwargs):
    import akshare as ak

    target = getattr(ak, fn)
    t0 = time.time()
    df = target(*args, **kwargs)
    elapsed = time.time() - t0
    if df is None:
        return {"ok": False, "error": "returned None", "seconds": round(elapsed, 2)}
    try:
        rows = int(len(df))
    except TypeError:
        return {
            "ok": True,
            "seconds": round(elapsed, 2),
            "rows": None,
            "type": str(type(df)),
            "sample": str(df)[:400],
        }
    columns = [str(c) for c in getattr(df, "columns", [])]
    null_ratio = None
    sample = None
    if rows:
        try:
            null_ratio = round(float(df.isna().mean().mean()), 4)
        except Exception:
            null_ratio = None
        try:
            sample = json.loads(df.head(3).to_json(orient="records", force_ascii=False, date_format="iso"))
        except Exception:
            sample = str(df.head(3))[:400]
    return {
        "ok": True,
        "seconds": round(elapsed, 2),
        "rows": rows,
        "columns": columns,
        "null_ratio": null_ratio,
        "sample": sample,
    }


PROBES = [
    ("etf_hist_hfq", "fund_etf_hist_em", ("510300",), {"period": "daily", "start_date": START, "end_date": END, "adjust": "hfq"}),
    ("etf_spot", "fund_etf_spot_em", (), {}),
    ("etf_nav", "fund_etf_fund_info_em", (), {"fund": "510300", "start_date": START, "end_date": END}),
    ("index_hist", "index_zh_a_hist", (), {"symbol": "000300", "period": "daily", "start_date": START, "end_date": END}),
    ("index_value_csindex", "stock_zh_index_value_csindex", (), {"symbol": "000300"}),
    ("index_hist_csindex", "stock_zh_index_hist_csindex", (), {"symbol": "000300", "start_date": START, "end_date": END}),
    ("index_pe_lg", "stock_index_pe_lg", (), {"symbol": "沪深300"}),
    ("index_pb_lg", "stock_index_pb_lg", (), {"symbol": "沪深300"}),
    ("trade_calendar", "tool_trade_date_hist_sina", (), {}),
    ("sector_flow_rank_today", "stock_sector_fund_flow_rank", (), {"indicator": "今日", "sector_type": "行业资金流"}),
    ("sector_flow_hist", "stock_sector_fund_flow_hist", (), {"symbol": "证券Ⅱ"}),
    ("industry_names", "stock_board_industry_name_em", (), {}),
    ("market_flow", "stock_market_fund_flow", (), {}),
    ("margin_sse", "stock_margin_sse", (), {"start_date": START, "end_date": END}),
    ("macro_pmi", "macro_china_pmi", (), {}),
    ("macro_cpi", "macro_china_cpi_monthly", (), {}),
    ("macro_m2", "macro_china_money_supply", (), {}),
    ("macro_lpr", "macro_china_lpr", (), {}),
    ("bond_10y", "bond_zh_us_rate", (), {"start_date": START}),
    ("etf_scale_sse", "fund_etf_scale_sse", (), {"date": (TODAY - timedelta(days=5)).strftime("%Y%m%d")}),
]


def _worker(fn, args, kwargs, q):
    try:
        q.put(_probe(fn, args, kwargs))
    except Exception:
        q.put({"ok": False, "error": traceback.format_exc(limit=3)[-1500:]})


def run_all(timeout: float, concurrency: int) -> list[dict]:
    results: list[dict] = []
    pending = list(PROBES)
    running: list[tuple] = []

    while pending or running:
        while pending and len(running) < concurrency:
            name, fn, args, kwargs = pending.pop(0)
            q = mp.Queue()
            p = mp.Process(target=_worker, args=(fn, args, kwargs, q))
            p.start()
            running.append({"name": name, "fn": fn, "proc": p, "queue": q, "start": time.time()})

        time.sleep(0.2)
        still = []
        for item in running:
            p: mp.Process = item["proc"]
            if p.is_alive():
                if time.time() - item["start"] > timeout:
                    p.terminate()
                    p.join(1)
                    results.append(
                        {
                            "name": item["name"],
                            "fn": item["fn"],
                            "ok": False,
                            "error": f"timeout after {timeout}s",
                        }
                    )
                    continue
                still.append(item)
                continue
            p.join(1)
            try:
                res = item["queue"].get_nowait()
            except Exception:
                res = {"ok": False, "error": f"no result (exitcode={p.exitcode})"}
            res.update({"name": item["name"], "fn": item["fn"]})
            results.append(res)
        running = still

    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/quality/source_probe.json")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    print(f"Probing {len(PROBES)} AKShare endpoints (timeout={args.timeout}s)...")
    results = run_all(args.timeout, args.concurrency)
    results.sort(key=lambda r: r["name"])

    report = {
        "probed_at": datetime.now().isoformat(timespec="seconds"),
        "window": {"start": START, "end": END},
        "results": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    ok = sum(1 for r in results if r.get("ok"))
    print(f"\n{ok}/{len(results)} endpoints OK -> {out}\n")
    for r in results:
        status = "OK " if r.get("ok") else "FAIL"
        detail = (
            f"rows={r.get('rows')} cols={len(r.get('columns') or [])} {r.get('seconds', '?')}s"
            if r.get("ok")
            else (r.get("error") or "").strip().splitlines()[-1][:120]
        )
        print(f"  [{status}] {r['name']:26s} {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
