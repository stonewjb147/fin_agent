"""Composite score: direction alignment, agreement and minimum coverage."""

from __future__ import annotations

import math

import pandas as pd

from finagent.signals.score import composite_scores


def _panel(rows: list[tuple[str, str, str, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["symbol", "factor", "date", "z_cs"])
    frame["date"] = pd.to_datetime(frame["date"])
    frame["value"] = frame["z_cs"]
    frame["rank_cs"] = 0.5
    return frame


def test_direction_is_applied_before_averaging():
    # momentum wants high values, reversal wants low values. Both symbols have
    # the same raw z pattern (A above B), so after alignment A must beat B for
    # both factors and the composite must be positive for A.
    factors = _panel(
        [
            ("A", "momentum_20", "2024-06-28", 1.0),
            ("B", "momentum_20", "2024-06-28", -1.0),
            ("A", "reversal_5", "2024-06-28", -1.0),
            ("B", "reversal_5", "2024-06-28", 1.0),
        ]
    )
    scores = composite_scores(factors)
    by_symbol = scores.set_index("symbol")

    assert by_symbol.loc["A", "composite"] == 1.0
    assert by_symbol.loc["B", "composite"] == -1.0
    assert by_symbol.loc["A", "confidence"] == 1.0
    assert by_symbol.loc["A", "n_factors"] == 2


def test_confidence_is_agreement_not_magnitude():
    factors = _panel(
        [
            ("A", "momentum_20", "2024-06-28", 2.0),
            ("A", "reversal_5", "2024-06-28", 1.0),
            ("B", "momentum_20", "2024-06-28", 1.0),
            ("B", "reversal_5", "2024-06-28", -1.0),
        ]
    )
    scores = composite_scores(factors).set_index("symbol")

    # A: aligned contributions +2 and -1 -> mean 0.5, agreement 1/3.
    assert scores.loc["A", "composite"] == 0.5
    assert math.isclose(scores.loc["A", "confidence"], 1.0 / 3.0)
    # B: both align -> agreement 1.
    assert scores.loc["B", "confidence"] == 1.0


def test_symbol_with_one_factor_is_dropped_by_min_factors():
    factors = _panel(
        [
            ("A", "momentum_20", "2024-06-28", 1.0),
            ("B", "momentum_20", "2024-06-28", 0.5),
            ("B", "reversal_5", "2024-06-28", 0.5),
        ]
    )
    scores = composite_scores(factors, min_factors=2)
    assert list(scores["symbol"]) == ["B"]


def test_zero_variance_factors_do_not_produce_infinities():
    factors = _panel(
        [
            ("A", "momentum_20", "2024-06-28", 0.0),
            ("A", "reversal_5", "2024-06-28", 0.0),
            ("B", "momentum_20", "2024-06-28", 0.0),
            ("B", "reversal_5", "2024-06-28", 0.0),
        ]
    )
    scores = composite_scores(factors)
    assert scores["composite"].abs().le(1e-12).all()
    assert scores["confidence"].between(0.0, 1.0).all()


def test_empty_input_returns_empty_frame():
    scores = composite_scores(pd.DataFrame())
    assert scores.empty
    assert list(scores.columns) == ["date", "symbol", "composite", "confidence", "n_factors"]
