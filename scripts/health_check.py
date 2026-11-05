#!/usr/bin/env python
"""Daily data-health check with optional Feishu alert.

Exit code 1 means at least one error-level check failed, so cron can page.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from finagent import config
from finagent.data.akshare_provider import default_provider
from finagent.data.health import check_health
from finagent.data.universe import load_universe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--universe", default=None)
    ap.add_argument("--alert", choices=["none", "feishu"], default="none")
    args = ap.parse_args()

    provider = default_provider()
    as_of = date.fromisoformat(args.date) if args.date else provider.last_trading_day()
    universe = load_universe(args.universe or config.CONFIG_DIR / "universe.yaml")
    report = check_health(provider, provider.cache, universe, as_of)

    out = config.QUALITY_DIR / f"health_{report['as_of']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not report["ok"]:
        bad = [c for c in report["checks"] if c["level"] in ("error", "warning")]
        lines = [f"[finagent] 数据健康检查失败 {report['as_of']}"]
        for c in bad[:15]:
            lines.append(f"- {c['dataset']}/{c['key']}: {c['last_date']} lag={c['lag_days']} {c['message']}")
        text = "\n".join(lines)
        print(text, file=sys.stderr)
        if args.alert == "feishu":
            try:
                from finagent.integrations.feishu import send_text

                sent = send_text(text)
                print(f"feishu alert sent={sent}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001 - alerting must not mask the failure
                print(f"feishu alert failed: {exc}", file=sys.stderr)
    else:
        print(f"data health OK for {report['as_of']} (warnings={report['warnings']})")

    print(f"report: {out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
