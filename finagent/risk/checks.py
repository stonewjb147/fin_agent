"""Portfolio and data risk checks.

Every check has an id, a level and a machine-readable value/limit. The summary
status is derived, never hand-set:

    blocked  any hard check failed
    warn     any soft check failed
    pass     otherwise

Informational checks never change the status.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from finagent.risk.policy import RiskPolicy
from finagent.risk.validation import evaluate_validation

HARD = "hard"
SOFT = "soft"
INFO = "info"


@dataclass(frozen=True)
class RiskCheck:
    id: str
    level: str
    passed: bool
    message: str
    value: Any = None
    limit: Any = None
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "level": self.level,
            "passed": self.passed,
            "message": self.message,
            "value": self.value,
            "limit": self.limit,
            "source": self.source,
        }


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _weights(portfolio: dict) -> dict[str, float]:
    return {
        str(item.get("symbol")): float(item["weight"])
        for item in portfolio.get("holdings", [])
        if _finite(item.get("weight"))
    }


def _exposures(portfolio: dict, weights: dict[str, float]) -> dict[str, float]:
    exposure = portfolio.get("category_exposure")
    if exposure:
        return {str(k): float(v) for k, v in exposure.items() if _finite(v)}
    grouped: dict[str, float] = {}
    for item in portfolio.get("holdings", []):
        weight = item.get("weight")
        if not _finite(weight):
            continue
        category = str(item.get("category") or "unknown")
        grouped[category] = grouped.get(category, 0.0) + float(weight)
    return grouped


def _liquidities(prices: pd.DataFrame | None) -> dict[str, float]:
    if prices is None or prices.empty or "amount" not in prices.columns:
        return {}
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values(["symbol", "date"])
    out: dict[str, float] = {}
    for symbol, group in frame.groupby("symbol"):
        amounts = group["amount"].tail(60).dropna()
        if len(amounts):
            out[str(symbol)] = float(amounts.mean())
    return out


def _drawdown(phase_eval: dict | None) -> tuple[str, float] | None:
    value = (phase_eval or {}).get("value") or {}
    strategies = value.get("strategies") or {}
    for name in ("policy_tilt", "policy_no_tilt"):
        metrics = (strategies.get(name) or {}).get("metrics") or {}
        drawdown = metrics.get("max_drawdown")
        if _finite(drawdown):
            return name, abs(float(drawdown))
    return None


def _breadth(phase_eval: dict | None) -> dict:
    return ((phase_eval or {}).get("value") or {}).get("breadth") or {}


def evaluate_risk(
    *,
    as_of: str,
    portfolio: dict | None,
    policy: RiskPolicy,
    prices: pd.DataFrame | None = None,
    health: dict | None = None,
    phase_eval: dict | None = None,
    ledger: dict | None = None,
    factor: dict | None = None,
) -> dict[str, Any]:
    checks: list[RiskCheck] = []

    def add(
        cid: str,
        level: str,
        passed: bool,
        message: str,
        value: Any = None,
        limit: Any = None,
        source: str = "",
    ) -> None:
        checks.append(RiskCheck(cid, level, bool(passed), message, value, limit, source))

    if portfolio is None:
        add(
            "portfolio.present",
            HARD,
            False,
            "缺少组合文件；先运行 `finagent portfolio`",
            source="portfolio",
        )
        weights: dict[str, float] = {}
        exposures: dict[str, float] = {}
    else:
        weights = _weights(portfolio)
        exposures = _exposures(portfolio, weights)
        add(
            "portfolio.present",
            HARD,
            True,
            f"{len(weights)} 个持仓",
            value=len(weights),
            source="portfolio",
        )
        negative = [symbol for symbol, weight in weights.items() if weight < -1e-9]
        add(
            "weights.non_negative",
            HARD,
            not negative,
            "所有权重非负" if not negative else f"负权重: {negative[:5]}",
            value=negative[:5] or None,
            limit=">= 0",
            source="portfolio",
        )
        total = sum(weights.values())
        add(
            "weights.sum_to_one",
            HARD,
            abs(total - 1.0) <= 0.01,
            f"权重合计 {total:.6f}",
            value=round(total, 6),
            limit="1.0 ± 0.01",
            source="portfolio",
        )
        maximum = max(weights.values()) if weights else 0.0
        add(
            "weights.asset_cap",
            HARD,
            maximum <= policy.max_asset_weight + 1e-6,
            f"最大单标的权重 {maximum:.2%}",
            value=round(maximum, 6),
            limit=policy.max_asset_weight,
            source="portfolio",
        )
        top5 = sum(sorted(weights.values(), reverse=True)[:5])
        add(
            "concentration.top5",
            SOFT,
            top5 <= policy.max_top5_weight + 1e-9,
            f"前五大权重合计 {top5:.2%}",
            value=round(top5, 6),
            limit=policy.max_top5_weight,
            source="portfolio",
        )

        for category, exposure in sorted(exposures.items()):
            cap = float(policy.category_caps.get(category, 1.0))
            add(
                f"exposure.cap.{category}",
                HARD,
                exposure <= cap + 1e-6,
                f"{category} 暴露 {exposure:.2%}",
                value=round(exposure, 6),
                limit=cap,
                source="portfolio",
            )

        budget = ((portfolio.get("policy") or {}).get("category_budget") or {})
        for category, target in sorted(budget.items()):
            actual = exposures.get(str(category))
            if actual is None:
                continue
            drift = abs(actual - float(target))
            add(
                f"exposure.drift.{category}",
                SOFT,
                drift <= policy.max_category_budget_drift + 1e-9,
                f"{category} 暴露偏离预算 {drift:.2%}",
                value=round(drift, 6),
                limit=policy.max_category_budget_drift,
                source="portfolio",
            )

    if portfolio is not None:
        vol = portfolio.get("portfolio_vol")
        add(
            "portfolio.vol_budget",
            HARD,
            _finite(vol) and float(vol) <= policy.max_portfolio_vol + 1e-9,
            f"组合年化波动率 {float(vol):.2%}" if _finite(vol) else "组合波动率缺失",
            value=round(float(vol), 6) if _finite(vol) else None,
            limit=policy.max_portfolio_vol,
            source="portfolio",
        )

    breadth = _breadth(phase_eval)
    n_eff = breadth.get("n_eff")
    add(
        "concentration.n_eff",
        SOFT if _finite(n_eff) else INFO,
        True if not _finite(n_eff) else float(n_eff) >= policy.min_n_eff,
        (
            f"相关性调整后有效标的 {float(n_eff):.2f}"
            if _finite(n_eff)
            else "有效广度不可用（缺 phase_eval）"
        ),
        value=round(float(n_eff), 4) if _finite(n_eff) else None,
        limit=policy.min_n_eff,
        source="phase_eval",
    )
    avg_corr = breadth.get("avg_corr")
    add(
        "concentration.avg_corr",
        SOFT if _finite(avg_corr) else INFO,
        True if not _finite(avg_corr) else float(avg_corr) <= policy.max_avg_corr,
        (
            f"标的平均相关系数 {float(avg_corr):.2%}"
            if _finite(avg_corr)
            else "平均相关系数不可用（缺 phase_eval）"
        ),
        value=round(float(avg_corr), 6) if _finite(avg_corr) else None,
        limit=policy.max_avg_corr,
        source="phase_eval",
    )

    drawdown = _drawdown(phase_eval)
    add(
        "portfolio.drawdown_budget",
        HARD if drawdown is not None else INFO,
        True if drawdown is None else drawdown[1] <= policy.max_drawdown + 1e-9,
        (
            f"{drawdown[0]} 回测最大回撤 -{drawdown[1]:.2%}"
            if drawdown is not None
            else "回测回撤不可用（缺 phase_eval）"
        ),
        value=round(-drawdown[1], 6) if drawdown is not None else None,
        limit=-policy.max_drawdown,
        source="phase_eval",
    )

    liquidity = _liquidities(prices)
    if liquidity and weights:
        missing = sorted(set(weights) - set(liquidity))
        add(
            "liquidity.coverage",
            HARD,
            not missing,
            "所有持仓都有 60 日成交额" if not missing else f"缺价格数据: {missing[:5]}",
            value=missing[:5] or None,
            limit="none missing",
            source="cache",
        )
        thin = sorted(
            (symbol, value)
            for symbol, value in liquidity.items()
            if symbol in weights and value < policy.min_avg_amount_60d
        )
        minimum = min((liquidity[s] for s in weights if s in liquidity), default=None)
        add(
            "liquidity.min_adv",
            HARD,
            not thin,
            (
                f"最低 60 日日均成交额 {minimum / 1e8:.2f} 亿元"
                if minimum is not None
                else "成交额不可用"
            ),
            value=round(minimum, 2) if minimum is not None else None,
            limit=policy.min_avg_amount_60d,
            source="cache",
        )
    else:
        add(
            "liquidity.min_adv",
            INFO,
            True,
            "没有价格缓存，流动性未检查",
            value=None,
            limit=policy.min_avg_amount_60d,
            source="cache",
        )

    if health:
        errors = int(health.get("errors") or 0)
        warnings = int(health.get("warnings") or 0)
        add(
            "data.health_errors",
            HARD,
            errors <= policy.max_health_errors,
            f"数据健康检查 errors={errors}",
            value=errors,
            limit=policy.max_health_errors,
            source="health",
        )
        add(
            "data.health_warnings",
            SOFT,
            warnings <= policy.max_health_warnings,
            f"数据健康检查 warnings={warnings}",
            value=warnings,
            limit=policy.max_health_warnings,
            source="health",
        )
    else:
        add(
            "data.health_errors",
            INFO,
            True,
            "没有健康检查文件，数据质量未确认",
            value=None,
            limit=policy.max_health_errors,
            source="health",
        )

    if prices is not None and not prices.empty and "date" in prices.columns:
        latest = pd.to_datetime(prices["date"]).max()
        lag = (pd.Timestamp(as_of) - latest).days
        add(
            "data.staleness",
            SOFT,
            lag <= 0,
            f"价格缓存最新日期 {latest.date()}，落后 {lag} 天",
            value=lag,
            limit="<= 0",
            source="cache",
        )

    settled = int((ledger or {}).get("n_settled") or 0)
    add(
        "validation.samples",
        INFO,
        settled >= policy.min_settled_samples,
        f"已结算样本 {settled}/{policy.min_settled_samples}",
        value=settled,
        limit=policy.min_settled_samples,
        source="ledger",
    )

    hard_failed = [c.id for c in checks if c.level == HARD and not c.passed]
    soft_failed = [c.id for c in checks if c.level == SOFT and not c.passed]
    status = "blocked" if hard_failed else ("warn" if soft_failed else "pass")
    counts = {
        "total": len(checks),
        "hard": sum(1 for c in checks if c.level == HARD),
        "soft": sum(1 for c in checks if c.level == SOFT),
        "info": sum(1 for c in checks if c.level == INFO),
        "hard_failed": len(hard_failed),
        "soft_failed": len(soft_failed),
    }
    validation = evaluate_validation(
        policy=policy,
        ledger=ledger,
        factor=factor,
        phase_eval=phase_eval,
        risk_status=status,
    )
    return {
        "as_of": as_of,
        "policy": policy.as_dict(),
        "policy_fingerprint": policy.fingerprint(),
        "status": status,
        "counts": counts,
        "checks": [check.as_dict() for check in checks],
        "failed": hard_failed + soft_failed,
        "validation": validation,
    }
