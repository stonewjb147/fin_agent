"""Evidence table for the Phase 6 narrative report.

The report may only repeat numbers that appear here. Every item has a stable
id, a human label, a display value already converted to the unit the prose will
use (percent rather than fraction), and the source artefact it came from.
Missing artefacts are recorded instead of being guessed.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from finagent import config


class EvidenceError(RuntimeError):
    """Raised when the artefact the report is supposed to describe is absent."""


@dataclass(frozen=True)
class Evidence:
    id: str
    label: str
    value: float
    unit: str = ""
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "note": self.note,
        }


@dataclass
class EvidenceBundle:
    as_of: str
    items: tuple[Evidence, ...]
    sources: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    symbols: tuple[str, ...] = ()
    ignore_terms: tuple[str, ...] = ()
    risk_status: str = ""

    def by_id(self, evidence_id: str) -> Evidence:
        for item in self.items:
            if item.id == evidence_id:
                return item
        raise KeyError(f"unknown evidence id: {evidence_id}")

    @property
    def ids(self) -> list[str]:
        return [item.id for item in self.items]

    @property
    def allowed_values(self) -> list[float]:
        return [item.value for item in self.items]

    @property
    def ignore_values(self) -> list[float]:
        """Six-digit ETF codes are identifiers, not numeric claims."""
        return [float(symbol) for symbol in self.symbols if symbol.isdigit()]

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "items": [item.as_dict() for item in self.items],
            "sources": self.sources,
            "missing": self.missing,
            "symbols": list(self.symbols),
            "ignore_terms": list(self.ignore_terms),
            "risk_status": self.risk_status,
        }


@dataclass
class ReportFacts:
    """Raw artefacts, kept so the deterministic template can choose what to say.

    Numbers are never read from here directly when rendering: the template asks
    the evidence bundle by id, which keeps prose and gate in sync.
    """

    as_of: str
    signals: dict
    portfolio: dict | None = None
    factor: dict | None = None
    health: dict | None = None
    phase_eval: dict | None = None
    risk: dict | None = None
    sources: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_optional(data_dir: Path, kind: str, relative: str, facts: ReportFacts) -> dict | None:
    path = data_dir / relative
    if not path.exists():
        facts.missing.append(kind)
        return None
    facts.sources[kind] = str(path)
    return _read_json(path)


def build_facts(as_of: str, data_dir: Path | None = None) -> ReportFacts:
    """Load the artefacts for one date; only the signals file is mandatory."""
    data_dir = Path(data_dir or config.DATA_DIR)
    signal_path = data_dir / "signals" / f"{as_of}.json"
    if not signal_path.exists():
        raise EvidenceError(
            f"no signals for {as_of} at {signal_path}; run `finagent signals --date {as_of}` first"
        )
    facts = ReportFacts(as_of=as_of, signals=_read_json(signal_path))
    facts.sources["signals"] = str(signal_path)
    facts.portfolio = _load_optional(
        data_dir, "portfolio", f"portfolio/{as_of}.json", facts
    )
    facts.factor = _load_optional(
        data_dir, "factor_report", f"quality/factor_report_{as_of}.json", facts
    )
    facts.health = _load_optional(data_dir, "health", f"quality/health_{as_of}.json", facts)
    facts.phase_eval = _load_optional(
        data_dir, "phase_eval", f"quality/phase_eval_{as_of}.json", facts
    )
    facts.risk = _load_optional(data_dir, "risk", f"quality/risk_{as_of}.json", facts)
    return facts


def _pct(value: float, digits: int = 2) -> float:
    return round(float(value) * 100, digits)


def _num(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _top_signals(signals: dict, n_long: int = 5, n_short: int = 5) -> list[dict]:
    rows = [row for row in signals.get("signals", []) if _finite(row.get("composite"))]
    longs = sorted((r for r in rows if r.get("direction", 0) > 0), key=lambda r: r["composite"], reverse=True)
    shorts = sorted((r for r in rows if r.get("direction", 0) < 0), key=lambda r: r["composite"])
    return longs[:n_long] + shorts[:n_short]


def build_evidence(facts: ReportFacts) -> EvidenceBundle:
    """Turn artefacts into the closed set of numbers the prose may cite."""
    items: list[Evidence] = []
    as_of = facts.as_of
    signals = facts.signals

    def add(evidence_id: str, label: str, value, unit: str = "", note: str = "") -> None:
        if not _finite(value):
            return
        items.append(Evidence(evidence_id, label, float(value), unit, note))

    # --- signals ---------------------------------------------------------
    add(f"signals:{as_of}:n_symbols", "股票池标的数", signals.get("n_symbols"), "只")
    add(f"signals:{as_of}:n_scored", "当日有得分的标的数", signals.get("n_scored"), "只")
    add(f"signals:{as_of}:n_signals", "当日信号条数", signals.get("n_signals"), "条")
    add(f"signals:{as_of}:horizon", "信号持有期", signals.get("horizon"), "个交易日")
    add(f"signals:{as_of}:execution_lag", "信号到执行的滞后", signals.get("execution_lag"), "个交易日")
    rows = signals.get("signals", [])
    add(f"signals:{as_of}:n_long", "看多信号数", sum(1 for r in rows if r.get("direction", 0) > 0), "条")
    add(f"signals:{as_of}:n_short", "看空信号数", sum(1 for r in rows if r.get("direction", 0) < 0), "条")
    ledger = signals.get("ledger_summary") or {}
    add(f"ledger:{as_of}:n_predictions", "预测账本条数", ledger.get("n_predictions"), "条")
    add(f"ledger:{as_of}:n_pending", "尚未结算的预测数", ledger.get("n_pending"), "条")
    add(f"ledger:{as_of}:n_settled", "已结算的预测数", ledger.get("n_settled"), "条")

    for row in _top_signals(signals):
        symbol = str(row.get("symbol", ""))
        label = f"{row.get('name', symbol)}（{symbol}）"
        add(f"signal:{symbol}:composite", f"{label} 合成得分", _num(row.get("composite"), 2), "分", str(row.get("category", "")))
        add(
            f"signal:{symbol}:confidence_pct",
            f"{label} 置信度",
            _pct(row.get("confidence", 0)),
            "%",
            str(row.get("category", "")),
        )

    # --- portfolio -------------------------------------------------------
    portfolio = facts.portfolio or {}
    add(f"portfolio:{as_of}:n_symbols", "组合可选标的数", portfolio.get("n_symbols"), "只")
    add(f"portfolio:{as_of}:n_holdings", "组合持仓数", portfolio.get("n_holdings"), "只")
    add(
        f"portfolio:{as_of}:portfolio_vol_pct",
        "组合年化波动率",
        _pct(portfolio.get("portfolio_vol", 0)) if portfolio.get("portfolio_vol") is not None else None,
        "%",
    )
    add(
        f"portfolio:{as_of}:weighted_vol_pct",
        "持仓加权平均年化波动率",
        _pct(portfolio.get("weighted_vol", 0)) if portfolio.get("weighted_vol") is not None else None,
        "%",
    )
    policy = portfolio.get("policy") or {}
    add(f"portfolio:{as_of}:asset_cap_pct", "单标的权重上限", _pct(policy.get("asset_cap", 0)) if policy.get("asset_cap") is not None else None, "%")
    for category, budget in sorted((policy.get("category_budget") or {}).items()):
        add(f"portfolio:{as_of}:budget:{category}_pct", f"{category} 类别预算", _pct(budget), "%")
    for category, exposure in sorted((portfolio.get("category_exposure") or {}).items()):
        add(f"portfolio:{as_of}:exposure:{category}_pct", f"{category} 类别实际暴露", _pct(exposure), "%")
    holdings = sorted(
        (h for h in portfolio.get("holdings", []) if _finite(h.get("weight"))),
        key=lambda h: h["weight"],
        reverse=True,
    )
    for holding in holdings[:8]:
        symbol = str(holding.get("symbol", ""))
        label = f"{holding.get('name', symbol)}（{symbol}）"
        add(f"holding:{symbol}:weight_pct", f"{label} 组合权重", _pct(holding.get("weight", 0)), "%")

    # --- factor evaluation ----------------------------------------------
    factor = facts.factor or {}
    tests = factor.get("tests", [])
    add(f"factor:{as_of}:n_factors", "参与检验的因子数", factor.get("meta", {}).get("n_factors"), "个")
    add(f"factor:{as_of}:n_tests", "因子检验总数", len(tests), "项")
    add(
        f"factor:{as_of}:n_significant",
        "BH-FDR 校正后显著的检验数",
        sum(1 for t in tests if t.get("significant_neutral")),
        "项",
    )
    add(f"factor:{as_of}:fdr_q_pct", "FDR 控制水平", _pct(factor.get("meta", {}).get("fdr_q", 0)) if factor.get("meta", {}).get("fdr_q") is not None else None, "%")
    for test in tests:
        name = str(test.get("factor", ""))
        horizon = test.get("horizon")
        prefix = f"factor:{name}:h{horizon}"
        add(f"{prefix}:horizon", f"{name} 检验持有期", horizon, "个交易日")
        add(f"{prefix}:ic_neutral", f"{name} {horizon} 日中性 IC", _num(test.get("ic_mean_neutral"), 4), "", "类别中性")
        add(f"{prefix}:q_neutral", f"{name} {horizon} 日中性 q 值", _num(test.get("q_value_neutral"), 3), "", "BH-FDR")

    # --- data health -----------------------------------------------------
    health = facts.health or {}
    if health:
        add(f"health:{as_of}:errors", "数据健康检查错误数", health.get("errors"), "项")
        add(f"health:{as_of}:warnings", "数据健康检查警告数", health.get("warnings"), "项")

    # --- Phase 7 risk ----------------------------------------------------
    risk = facts.risk or {}
    risk_counts = risk.get("counts") or {}
    add(f"risk:{as_of}:n_checks", "风控检查项数", risk_counts.get("total"), "项")
    add(f"risk:{as_of}:n_hard_failed", "风控硬约束失败项数", risk_counts.get("hard_failed"), "项")
    add(f"risk:{as_of}:n_soft_failed", "风控软约束失败项数", risk_counts.get("soft_failed"), "项")

    # --- optional Phase 1-5 evaluation ----------------------------------
    phase = facts.phase_eval or {}
    value = phase.get("value") or {}
    breadth = value.get("breadth") or {}
    add("breadth:n_eff", "组合有效标的数（相关性调整后）", _num(breadth.get("n_eff"), 2), "只")
    add("breadth:avg_corr_pct", "标的间平均相关系数", _pct(breadth.get("avg_corr", 0)), "%")
    for group in ("strategies", "benchmarks"):
        for name, payload in sorted((value.get(group) or {}).items()):
            metrics = (payload or {}).get("metrics") or {}
            add(f"backtest:{name}:cagr_pct", f"{name} 年化收益", _pct(metrics.get("cagr", 0)), "%")
            add(f"backtest:{name}:max_drawdown_pct", f"{name} 最大回撤", _pct(metrics.get("max_drawdown", 0)), "%")
    ledger_eval = value.get("ledger") or {}
    add("ledger:required_settled_5pct", "命中率 ±5% 精度所需结算样本", ledger_eval.get("required_settled_5pct"), "条")
    if ledger_eval.get("required_settled_5pct") is not None:
        add("ledger:precision_pct", "命中率精度目标", 5, "%")

    symbols = sorted(
        {str(row.get("symbol")) for row in rows if row.get("symbol")}
        | {str(h.get("symbol")) for h in portfolio.get("holdings", []) if h.get("symbol")}
    )
    # Product names such as 沪深300ETF contain index numbers that are part of
    # the identifier, not claims. Mask them (and the codes) before extraction.
    names = {
        str(row.get("name"))
        for row in rows
        if row.get("name")
    } | {str(h.get("name")) for h in portfolio.get("holdings", []) if h.get("name")}
    names |= {str(test.get("factor")) for test in tests if test.get("factor")}
    names |= set((value.get("strategies") or {}).keys())
    names |= set((value.get("benchmarks") or {}).keys())
    ignore_terms = sorted(set(symbols) | names, key=len, reverse=True)
    return EvidenceBundle(
        as_of=as_of,
        items=tuple(items),
        sources=dict(facts.sources),
        missing=list(facts.missing),
        symbols=tuple(symbols),
        ignore_terms=tuple(ignore_terms),
        risk_status=str(risk.get("status") or ""),
    )


def format_evidence(bundle: EvidenceBundle) -> str:
    """Prompt-friendly table: one line per number, id first for easy citation."""
    lines = []
    for item in bundle.items:
        value = f"{item.value:g}"
        if item.unit:
            value += item.unit
        note = f"  # {item.note}" if item.note else ""
        lines.append(f"- [snap:{item.id}] {item.label} = {value}{note}")
    return "\n".join(lines)
