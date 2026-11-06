"""Covariance estimation.

Fifty ETFs over a 120-day window is a p/n ratio where the sample covariance is
close to singular, so we shrink it toward a scaled identity (Ledoit & Wolf 2004,
identity target). No extra dependency: the estimator is ~20 lines of numpy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from finagent import config


def ledoit_wolf(
    returns: pd.DataFrame,
    *,
    annualize: bool = True,
    periods: int = config.TRADING_DAYS_PER_YEAR,
) -> pd.DataFrame:
    """Shrink the sample covariance toward mu * I and return a pandas frame."""
    if returns.empty:
        return pd.DataFrame()
    columns = list(returns.columns)
    p = len(columns)
    clean = returns.dropna(how="any")

    if clean.shape[0] < 2:
        # Not enough overlapping observations: diagonal of pairwise variances.
        variances = returns.var(ddof=1).fillna(0.0).to_numpy(dtype=float)
        cov = np.diag(variances)
    else:
        X = clean.to_numpy(dtype=float)
        X = X - X.mean(axis=0)
        n = X.shape[0]
        sample = X.T @ X / n

        mu = float(np.trace(sample)) / p
        target = mu * np.eye(p)
        gamma = float(((sample - target) ** 2).sum())

        if gamma <= 0.0:
            # The sample covariance is already a scaled identity.
            cov = sample
        else:
            outer = X[:, :, None] * X[:, None, :]
            pi_ij = ((outer - sample) ** 2).mean(axis=0)
            pi = float(pi_ij.sum())
            rho = float(np.trace(pi_ij))
            shrinkage = float(np.clip((pi - rho) / gamma / n, 0.0, 1.0))
            cov = shrinkage * target + (1.0 - shrinkage) * sample

    if annualize:
        cov = cov * periods
    return pd.DataFrame(cov, index=columns, columns=columns)


def portfolio_vol(weights: pd.Series, cov: pd.DataFrame) -> float:
    """Annualised portfolio volatility sqrt(w' Sigma w)."""
    if weights.empty or cov.empty:
        return float("nan")
    aligned = weights.reindex(cov.index).fillna(0.0)
    w = aligned.to_numpy(dtype=float)
    sigma = cov.to_numpy(dtype=float)
    variance = float(w @ sigma @ w)
    return float(np.sqrt(max(variance, 0.0)))
