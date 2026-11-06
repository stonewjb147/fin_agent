"""Portfolio weights, caps and covariance shrinkage."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from finagent.portfolio.construct import (
    apply_asset_cap,
    apply_category_caps,
    inverse_vol_weights,
    target_weights,
    tilt_multipliers,
)
from finagent.portfolio.covariance import ledoit_wolf, portfolio_vol
from finagent.portfolio.policy import PortfolioPolicy


def test_inverse_vol_gives_lower_vol_more_weight():
    weights = inverse_vol_weights(pd.Series({"A": 0.10, "B": 0.20, "C": 0.40}))
    assert pytest.approx(weights.sum()) == 1.0
    assert weights["A"] > weights["B"] > weights["C"]


def test_tilt_is_bounded():
    scores = pd.Series({"A": 5.0, "B": -5.0, "C": np.nan})
    multipliers = tilt_multipliers(scores, strength=0.15, floor=0.5, ceiling=1.5)
    assert multipliers["A"] == 1.5
    assert multipliers["B"] == 0.5
    assert multipliers["C"] == 1.0  # missing score means no tilt, not a penalty


def test_asset_cap_preserves_total_and_binds():
    weights = pd.Series({"A": 0.7, "B": 0.2, "C": 0.1})
    capped = apply_asset_cap(weights, cap=0.4)
    assert pytest.approx(capped.sum()) == 1.0
    assert capped.max() <= 0.4 + 1e-12


def test_asset_cap_raises_when_infeasible():
    with pytest.raises(ValueError):
        apply_asset_cap(pd.Series({"A": 0.6, "B": 0.4}), cap=0.3)


def test_category_cap_redistributes_to_other_categories():
    weights = pd.Series({"A": 0.4, "B": 0.4, "C": 0.1, "D": 0.1})
    categories = pd.Series({"A": "broad", "B": "broad", "C": "bond", "D": "bond"})
    capped = apply_category_caps(weights, categories, caps={"broad": 0.5, "bond": 0.5})
    exposure = capped.groupby(categories).sum()
    assert pytest.approx(capped.sum()) == 1.0
    assert exposure["broad"] <= 0.5 + 1e-9
    assert exposure["bond"] <= 0.5 + 1e-9


def test_target_weights_respect_budgets_and_caps():
    symbols = [f"S{i:02d}" for i in range(20)]
    categories = pd.Series({s: ("broad" if i < 10 else "sector") for i, s in enumerate(symbols)})
    vols = pd.Series({s: 0.15 + 0.01 * i for i, s in enumerate(symbols)})
    scores = pd.Series({s: np.linspace(-2, 2, 20)[i] for i, s in enumerate(symbols)})
    policy = PortfolioPolicy(asset_cap=0.12)

    weights = target_weights(symbols, categories, vols, scores, policy)

    assert pytest.approx(weights.sum()) == 1.0
    assert weights.max() <= 0.12 + 1e-9
    exposure = weights.groupby(categories).sum()
    # Sector's strategic budget (0.25/0.60 = 0.417) is trimmed to the 0.40
    # guardrail; the excess goes to broad.
    assert exposure["sector"] == pytest.approx(0.40, rel=1e-6)
    assert exposure["broad"] == pytest.approx(0.60, rel=1e-6)


def test_tilt_moves_weight_towards_high_scores():
    symbols = ["A", "B", "C", "D"]
    categories = pd.Series({s: "broad" for s in symbols})
    vols = pd.Series({s: 0.2 for s in symbols})

    neutral = target_weights(symbols, categories, vols, pd.Series(0.0, index=symbols), PortfolioPolicy(asset_cap=0.5))
    bullish = target_weights(
        symbols, categories, vols, pd.Series({"A": 2.0, "B": 1.0, "C": -1.0, "D": -2.0}), PortfolioPolicy(asset_cap=0.5)
    )
    assert bullish["A"] > neutral["A"]
    assert bullish["D"] < neutral["D"]


def test_ledoit_wolf_is_symmetric_positive_definite():
    rng = np.random.default_rng(7)
    returns = pd.DataFrame(rng.normal(0, 0.01, size=(40, 60)), columns=[f"S{i}" for i in range(60)])
    cov = ledoit_wolf(returns)
    matrix = cov.to_numpy()

    assert np.allclose(matrix, matrix.T)
    eigenvalues = np.linalg.eigvalsh(matrix)
    assert eigenvalues.min() > 0  # sample covariance is singular here; shrinkage fixes it


def test_ledoit_wolf_shrinks_toward_scaled_identity_when_sample_is_short():
    rng = np.random.default_rng(11)
    returns = pd.DataFrame(rng.normal(0, 0.01, size=(3, 10)), columns=[f"S{i}" for i in range(10)])
    cov = ledoit_wolf(returns).to_numpy()
    off_diagonal = cov - np.diag(np.diag(cov))
    assert np.abs(off_diagonal).max() > 0  # not fully shrunk, but positive definite
    assert np.linalg.eigvalsh(cov).min() > 0


def test_portfolio_vol_matches_manual_calculation():
    weights = pd.Series({"A": 0.5, "B": 0.5})
    cov = pd.DataFrame([[0.04, 0.0], [0.0, 0.09]], index=["A", "B"], columns=["A", "B"])
    expected = np.sqrt(0.25 * 0.04 + 0.25 * 0.09)
    assert pytest.approx(portfolio_vol(weights, cov)) == expected
