"""Machine-readable conditions for flipping `validated=false`.

The flag is not a judgement call. It may only change when every criterion below
passes; until then this module lists exactly what is missing. `eligible=true`
does not flip the flag either — it says the evidence is finally sufficient for a
human to review the decision.
"""

from __future__ import annotations

from typing import Any

from finagent.risk.policy import RiskPolicy


def _criterion(
    cid: str,
    description: str,
    actual: Any,
    required: Any,
    passed: bool,
) -> dict[str, Any]:
    return {
        "id": cid,
        "description": description,
        "actual": actual,
        "required": required,
        "passed": bool(passed),
    }


def _drawdown_magnitude(phase_eval: dict | None) -> float | None:
    value = (phase_eval or {}).get("value") or {}
    strategies = value.get("strategies") or {}
    for name in ("policy_tilt", "policy_no_tilt"):
        metrics = (strategies.get(name) or {}).get("metrics") or {}
        drawdown = metrics.get("max_drawdown")
        if drawdown is not None:
            return abs(float(drawdown))
    return None


def evaluate_validation(
    *,
    policy: RiskPolicy,
    ledger: dict | None = None,
    factor: dict | None = None,
    phase_eval: dict | None = None,
    risk_status: str | None = None,
) -> dict[str, Any]:
    ledger = ledger or {}
    factor = factor or {}
    settled = int(ledger.get("n_settled") or 0)
    hit_rate = ledger.get("hit_rate_excess")
    mean_excess = ledger.get("mean_directional_excess")
    significant = sum(
        1 for test in factor.get("tests", []) if test.get("significant_neutral")
    )
    drawdown = _drawdown_magnitude(phase_eval)
    risk_ok = risk_status != "blocked"

    criteria = [
        _criterion(
            "settled_samples",
            "结算样本达到 ±5% 命中率精度所需数量",
            settled,
            policy.min_settled_samples,
            settled >= policy.min_settled_samples,
        ),
        _criterion(
            "hit_rate_excess",
            "相对等权全池的命中率",
            hit_rate,
            policy.min_hit_rate_excess,
            hit_rate is not None and float(hit_rate) >= policy.min_hit_rate_excess,
        ),
        _criterion(
            "mean_directional_excess",
            "平均方向性超额收益（扣除成本前）",
            mean_excess,
            "> 0",
            mean_excess is not None and float(mean_excess) > 0.0,
        ),
        _criterion(
            "factor_significant",
            "BH-FDR 校正后显著的中性因子检验数",
            significant,
            policy.min_factor_significant,
            significant >= policy.min_factor_significant,
        ),
        _criterion(
            "drawdown_budget",
            "策略回测最大回撤不超过预算",
            None if drawdown is None else round(-drawdown, 6),
            f"-{policy.max_drawdown:.0%}",
            drawdown is not None and drawdown <= policy.max_drawdown,
        ),
        _criterion(
            "risk_not_blocked",
            "风控硬约束全部通过",
            risk_status or "not run",
            "not blocked",
            risk_ok,
        ),
    ]
    remaining = [item["id"] for item in criteria if not item["passed"]]
    return {
        "validated": False,
        "eligible": not remaining,
        "criteria": criteria,
        "remaining": remaining,
        "note": (
            "validated stays false until every criterion passes; eligible=true "
            "only means the evidence is sufficient for a human review, not that "
            "the signals are approved."
        ),
    }
