"""End-to-end risk run: read artefacts, evaluate limits, write the verdict."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from finagent import config
from finagent.data.cache import ParquetCache
from finagent.data.panel import as_date
from finagent.factors.build import load_price_frame
from finagent.predictions.ledger import PredictionLedger
from finagent.risk.checks import evaluate_risk
from finagent.risk.policy import RiskPolicy, load_risk_policy


class RiskError(RuntimeError):
    """The risk report cannot be produced from the available artefacts."""


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run_risk(
    as_of: str,
    *,
    data_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
    policy: RiskPolicy | None = None,
    out_dir: str | Path | None = None,
    write: bool = True,
) -> dict:
    data_dir = Path(data_dir or config.DATA_DIR)
    cache_dir = Path(cache_dir or data_dir / "cache")
    policy = policy or load_risk_policy()
    as_of = as_date(as_of).isoformat()

    portfolio = _read_json(data_dir / "portfolio" / f"{as_of}.json")
    if portfolio is None:
        raise RiskError(
            f"no portfolio for {as_of}; run `finagent portfolio --date {as_of}` first"
        )
    health = _read_json(data_dir / "quality" / f"health_{as_of}.json")
    phase_eval = _read_json(data_dir / "quality" / f"phase_eval_{as_of}.json")
    factor = _read_json(data_dir / "quality" / f"factor_report_{as_of}.json")
    ledger = PredictionLedger(data_dir / "predictions").summary(as_of)

    symbols = [str(item.get("symbol")) for item in portfolio.get("holdings", [])]
    prices = None
    if symbols and cache_dir.exists():
        try:
            prices = load_price_frame(ParquetCache(cache_dir), symbols, as_of)
        except ValueError:
            prices = None

    result = evaluate_risk(
        as_of=as_of,
        portfolio=portfolio,
        policy=policy,
        prices=prices,
        health=health,
        phase_eval=phase_eval,
        ledger=ledger,
        factor=factor,
    )
    result["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    result["inputs"] = {
        "portfolio": str(data_dir / "portfolio" / f"{as_of}.json"),
        "health": str(data_dir / "quality" / f"health_{as_of}.json") if health else None,
        "phase_eval": (
            str(data_dir / "quality" / f"phase_eval_{as_of}.json") if phase_eval else None
        ),
        "factor": (
            str(data_dir / "quality" / f"factor_report_{as_of}.json") if factor else None
        ),
        "prices": str(cache_dir) if prices is not None else None,
    }

    if write:
        target = Path(out_dir or data_dir / "quality")
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"risk_{as_of}.json"
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result["risk_file"] = str(path)
    return result


def format_risk(result: dict) -> str:
    counts = result["counts"]
    lines = [
        f"Risk for {result['as_of']}  status={result['status']}  "
        f"policy={result['policy']['name']} ({result['policy_fingerprint']})",
        f"Hard: {counts['hard'] - counts['hard_failed']}/{counts['hard']} passed   "
        f"Soft: {counts['soft'] - counts['soft_failed']}/{counts['soft']} passed   "
        f"Info: {counts['info']}",
    ]
    failed = [
        check
        for check in result["checks"]
        if not check["passed"] and check["level"] in ("hard", "soft")
    ]
    if failed:
        lines.append("Failed checks:")
        for check in failed:
            lines.append(
                f"  - [{check['level']}] {check['id']}: {check['message']} "
                f"(value={check['value']}, limit={check['limit']})"
            )
    else:
        lines.append("No failed checks.")
    notes = [
        check
        for check in result["checks"]
        if check["level"] == "info" and not check["passed"]
    ]
    for check in notes:
        lines.append(f"Note: {check['id']}: {check['message']}")
    validation = result["validation"]
    remaining = ", ".join(validation["remaining"]) or "none"
    lines.append(
        f"Validation: eligible={str(validation['eligible']).lower()}  "
        f"remaining={remaining}  validated=false"
    )
    if result.get("risk_file"):
        lines.append(f"JSON: {result['risk_file']}")
    return "\n".join(lines)
