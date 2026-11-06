"""Signal selection, thresholds and falsifiability rules."""

from __future__ import annotations

import pandas as pd
import pytest

from finagent.data.universe import ETF, Universe
from finagent.signals.build import build_signals
from finagent.signals.models import Evidence, QuantSignal


def _universe() -> Universe:
    return Universe(
        version="u-test",
        etfs=[
            ETF(symbol="510300", name="沪深300ETF", category="broad"),
            ETF(symbol="512880", name="证券ETF", category="sector"),
            ETF(symbol="511010", name="国债ETF", category="bond", index_data=False),
            ETF(symbol="518880", name="黄金ETF", category="commodity"),
        ],
    )


def _scores(values: dict[str, tuple[float, float]]) -> pd.DataFrame:
    rows = [
        {
            "date": pd.Timestamp("2024-06-28"),
            "symbol": symbol,
            "composite": composite,
            "confidence": confidence,
            "n_factors": 3,
        }
        for symbol, (composite, confidence) in values.items()
    ]
    return pd.DataFrame(rows)


def test_selects_top_longs_and_bottoms_shorts():
    scores = _scores(
        {
            "510300": (1.2, 0.9),
            "512880": (0.6, 0.8),
            "511010": (-0.8, 0.7),
            "518880": (-0.9, 0.7),
        }
    )
    signals = build_signals(scores, _universe(), "2024-06-28", n_long=1, n_short=1)

    assert [s.symbol for s in signals] == ["510300", "518880"]
    assert [s.direction for s in signals] == [1, -1]
    assert signals[0].category == "broad"
    assert signals[1].category == "commodity"


def test_weak_or_disagreeing_scores_are_not_signals():
    scores = _scores(
        {
            "510300": (0.10, 0.99),  # score below threshold
            "512880": (1.50, 0.10),  # factors disagree
            "511010": (-1.20, 0.95),
        }
    )
    signals = build_signals(scores, _universe(), "2024-06-28", min_composite=0.25, min_confidence=0.5)
    assert [s.symbol for s in signals] == ["511010"]


def test_one_category_cannot_fill_the_whole_list():
    universe = Universe(
        version="u-test",
        etfs=[
            ETF(symbol="510300", name="A", category="broad"),
            ETF(symbol="510500", name="B", category="broad"),
            ETF(symbol="159915", name="C", category="broad"),
            ETF(symbol="512880", name="D", category="sector"),
            ETF(symbol="512800", name="E", category="sector"),
        ],
    )
    scores = _scores(
        {
            "510300": (2.0, 0.9),
            "510500": (1.8, 0.9),
            "159915": (1.6, 0.9),
            "512880": (1.4, 0.9),
            "512800": (1.2, 0.9),
        }
    )
    signals = build_signals(scores, universe, "2024-06-28", n_long=4, max_per_category=2)
    categories = [s.category for s in signals]
    assert categories.count("broad") == 2
    assert categories.count("sector") == 2
    assert [s.symbol for s in signals] == ["510300", "510500", "512880", "512800"]


def test_nothing_qualifies_means_no_signals():
    scores = _scores({"510300": (0.05, 0.9), "512880": (-0.02, 0.9)})
    assert build_signals(scores, _universe(), "2024-06-28") == []


def test_signal_id_is_stable_and_direction_specific():
    scores = _scores({"510300": (1.0, 0.9)})
    first = build_signals(scores, _universe(), "2024-06-28")[0]
    second = build_signals(scores, _universe(), "2024-06-28")[0]
    assert first.signal_id == second.signal_id

    scores_short = _scores({"510300": (-1.0, 0.9)})
    short = build_signals(scores_short, _universe(), "2024-06-28")[0]
    assert short.signal_id != first.signal_id


def test_every_signal_carries_invalidation_rules():
    scores = _scores({"510300": (1.0, 0.9)})
    signal = build_signals(scores, _universe(), "2024-06-28")[0]
    kinds = {rule.kind for rule in signal.invalidation}
    assert {"score_flip", "horizon_elapsed"} <= kinds
    assert signal.validated is False


def test_signal_rejects_invalid_arguments():
    with pytest.raises(ValueError):
        QuantSignal(
            as_of=pd.Timestamp("2024-06-28").date(),
            symbol="510300",
            name="x",
            category="broad",
            direction=0,
            composite=1.0,
            confidence=0.9,
            horizon=20,
            execution_lag=1,
            evidence=(),
            invalidation=(),
            thesis="",
        )
    with pytest.raises(ValueError):
        QuantSignal(
            as_of=pd.Timestamp("2024-06-28").date(),
            symbol="510300",
            name="x",
            category="broad",
            direction=1,
            composite=1.0,
            confidence=1.5,
            horizon=20,
            execution_lag=1,
            evidence=(),
            invalidation=(),
            thesis="",
        )


def test_thesis_is_generated_from_the_evidence():
    signal = QuantSignal(
        as_of=pd.Timestamp("2024-06-28").date(),
        symbol="510300",
        name="沪深300ETF",
        category="broad",
        direction=1,
        composite=0.8,
        confidence=0.9,
        horizon=20,
        execution_lag=1,
        evidence=(Evidence("momentum_20", 0.1, 1.2, 1, 1.2),),
        invalidation=(),
        thesis="x",
    )
    from finagent.signals.build import _thesis

    text = _thesis(signal.direction, signal.composite, signal.confidence, 20, signal.evidence)
    assert "momentum_20 +1.20" in text
    assert "+0.80" in text
