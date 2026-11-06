"""Prediction ledger: dedupe, settlement maths, no look-ahead, calibration."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from finagent.predictions.ledger import PredictionLedger, record_settlement


def _record(signal_id: str, as_of: str, symbol: str = "A", direction: int = 1, horizon: int = 2) -> dict:
    return {
        "signal_id": signal_id,
        "as_of": as_of,
        "symbol": symbol,
        "name": symbol,
        "category": "broad",
        "direction": direction,
        "horizon": horizon,
        "execution_lag": 1,
        "composite": 1.0,
        "confidence": 0.8,
        "n_factors": 3,
        "evidence_json": "[]",
        "thesis": "test",
    }


def _close(up: float = 0.01, down: float = -0.01) -> pd.DataFrame:
    index = pd.bdate_range("2024-06-03", periods=10)
    a = 100.0 * np.cumprod(np.full(10, 1.0 + up))
    b = 100.0 * np.cumprod(np.full(10, 1.0 + down))
    return pd.DataFrame({"A": a, "B": b}, index=index)


def test_append_is_idempotent(tmp_path):
    ledger = PredictionLedger(tmp_path)
    record = _record("sig-1", "2024-06-03")
    assert ledger.append([record]) == 1
    assert ledger.append([record]) == 0
    assert len(ledger.load()) == 1


def test_settlement_uses_execution_lag_and_horizon(tmp_path):
    ledger = PredictionLedger(tmp_path)
    close = _close()
    ledger.append([_record("sig-1", "2024-06-03", horizon=2)])

    settled = ledger.settle(close, "2024-06-10")
    row = settled.iloc[0]

    entry_pos, exit_pos = 1, 3
    assert row["entry_date"] == close.index[entry_pos].date().isoformat()
    assert row["exit_date"] == close.index[exit_pos].date().isoformat()
    assert pytest.approx(row["ret"]) == float(close["A"].iloc[exit_pos] / close["A"].iloc[entry_pos] - 1)
    assert row["hit"] is True or bool(row["hit"]) is True


def test_settlement_waits_for_the_horizon(tmp_path):
    ledger = PredictionLedger(tmp_path)
    close = _close()
    ledger.append([_record("sig-1", "2024-06-03", horizon=5)])

    assert ledger.settle(close, "2024-06-05").empty  # exit position not reached
    assert ledger.settle(close, "2024-06-11").shape[0] == 1


def test_settlement_never_peeks_past_as_of(tmp_path):
    ledger = PredictionLedger(tmp_path)
    close = _close()
    ledger.append([_record("sig-1", "2024-06-03", horizon=2)])

    truncated = close.loc[: pd.Timestamp("2024-06-06")]  # only 4 rows: entry=1, exit=3 fits
    settled = ledger.settle(truncated, "2024-06-06")
    assert settled.iloc[0]["exit_date"] == truncated.index[3].date().isoformat()


def test_settlement_is_applied_once(tmp_path):
    ledger = PredictionLedger(tmp_path)
    close = _close()
    ledger.append([_record("sig-1", "2024-06-03")])

    assert len(ledger.settle(close, "2024-06-10")) == 1
    assert ledger.settle(close, "2024-06-11").empty


def test_excess_return_is_relative_to_the_universe(tmp_path):
    ledger = PredictionLedger(tmp_path)
    close = _close(up=0.01, down=-0.01)
    ledger.append([_record("sig-1", "2024-06-03", symbol="A", horizon=2)])

    row = ledger.settle(close, "2024-06-10").iloc[0]
    expected_excess = row["ret"] - float(
        ((close.iloc[3] / close.iloc[1]) - 1.0).mean()
    )
    assert pytest.approx(row["excess"]) == expected_excess


def test_short_signal_hits_when_asset_underperforms(tmp_path):
    ledger = PredictionLedger(tmp_path)
    close = _close(up=0.01, down=-0.01)
    ledger.append([_record("sig-1", "2024-06-03", symbol="B", direction=-1, horizon=2)])

    row = ledger.settle(close, "2024-06-10").iloc[0]
    assert bool(row["hit"]) is True
    assert bool(row["hit_excess"]) is True
    assert row["dir_ret"] > 0


def test_signals_are_not_settled_on_non_price_dates(tmp_path):
    ledger = PredictionLedger(tmp_path)
    close = _close()
    ledger.append([_record("sig-1", "2024-06-08")])  # a Saturday, not in the panel
    assert ledger.settle(close, "2024-06-12").empty


def test_summary_reports_hit_rate_and_calibration(tmp_path):
    ledger = PredictionLedger(tmp_path)
    close = _close()
    ledger.append([_record("sig-1", "2024-06-03", symbol="A", horizon=2)])
    ledger.append([_record("sig-2", "2024-06-03", symbol="B", horizon=2)])
    settled = ledger.settle(close, "2024-06-10")
    assert record_settlement(settled)["n_new"] == 2

    summary = ledger.summary("2024-06-10")
    assert summary["n_predictions"] == 2
    assert summary["n_settled"] == 2
    assert summary["n_pending"] == 0
    assert 0.0 <= summary["hit_rate_excess"] <= 1.0
    assert summary["brier"] is not None
    assert summary["calibration"]


def test_summary_without_settlements_is_explicit(tmp_path):
    ledger = PredictionLedger(tmp_path)
    summary = ledger.summary("2024-06-10")
    assert summary["n_settled"] == 0
    assert summary["brier"] is None
