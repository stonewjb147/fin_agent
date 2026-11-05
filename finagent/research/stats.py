"""Small-sample statistics for factor evaluation.

statsmodels is not a dependency (and pulling it in for three formulas is not
worth the install), so Newey-West, Benjamini-Hochberg and the Deflated Sharpe
Ratio are implemented directly on numpy/scipy.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

from finagent import config

EULER_GAMMA = 0.5772156649015329


def newey_west_lags(n: int, horizon: int = 1) -> int:
    """Bartlett lag length.

    `horizon - 1` is a floor: h-day forward returns sampled daily overlap by
    h-1 days, so autocorrelation up to that lag is structural, not incidental.
    """
    rule = int(math.floor(4 * (n / 100) ** (2 / 9)))
    return max(horizon - 1, rule, 0)


def newey_west_tstat(
    values: Sequence[float] | pd.Series, lags: int | None = None
) -> tuple[float, float]:
    """t-statistic of the mean with a HAC standard error. Returns (t, p)."""
    x = np.asarray(pd.Series(values).dropna(), dtype=float)
    n = x.size
    if n < 3 or np.all(x == x[0]):
        return float("nan"), float("nan")
    lag = newey_west_lags(n) if lags is None else int(lags)
    lag = min(max(lag, 0), n - 1)

    demeaned = x - x.mean()
    # (n-1) denominators are the small-sample convention: at lag 0 the HAC
    # variance collapses to the textbook s^2/n.
    gamma0 = float(demeaned @ demeaned) / (n - 1)
    variance = gamma0
    for j in range(1, lag + 1):
        weight = 1.0 - j / (lag + 1.0)
        gamma_j = float(demeaned[j:] @ demeaned[:-j]) / (n - 1)
        variance += 2.0 * weight * gamma_j
    variance = max(variance, 0.0) / n
    if variance <= 0:
        return float("nan"), float("nan")
    t_stat = float(x.mean() / math.sqrt(variance))
    p_value = float(2.0 * scipy_stats.norm.sf(abs(t_stat)))
    return t_stat, p_value


def bh_fdr(pvalues: Sequence[float], q: float = 0.10) -> list[bool]:
    """Benjamini-Hochberg step-up. Returns a rejection flag per input p-value."""
    pvals = np.asarray(pvalues, dtype=float)
    m = pvals.size
    if m == 0:
        return []
    order = np.argsort(pvals)
    ranked = pvals[order]
    thresholds = q * np.arange(1, m + 1) / m
    passing = ranked <= thresholds

    reject = np.zeros(m, dtype=bool)
    if passing.any():
        cutoff = int(np.max(np.nonzero(passing)[0]))
        reject[order[: cutoff + 1]] = True
    return reject.tolist()


def sharpe_ratio(returns: Sequence[float] | pd.Series, periods: int = 252) -> float:
    """Annualised Sharpe ratio, risk-free rate taken from config."""
    x = pd.Series(returns).dropna()
    if x.size < 2 or x.std(ddof=1) == 0:
        return float("nan")
    excess = x.mean() - config.DEFAULT_RISK_FREE_RATE / periods
    return float(excess / x.std(ddof=1) * math.sqrt(periods))


def deflated_sharpe(returns: Sequence[float] | pd.Series, n_trials: int) -> dict:
    """Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio.

    Answers: given that we tried `n_trials` variants and kept the best, what is
    the probability the true Sharpe ratio exceeds zero? Uses the *daily*
    (non-annualised) Sharpe in the correction, as in the paper.
    """
    x = pd.Series(returns).dropna()
    n = x.size
    if n < 3 or x.std(ddof=1) == 0 or n_trials < 1:
        return {"sharpe": float("nan"), "dsr": float("nan"), "sr0": float("nan")}

    sr = float(x.mean() / x.std(ddof=1))
    skew = float(x.skew())
    kurt = float(x.kurtosis()) + 3.0  # pandas reports excess kurtosis
    va = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr**2
    if va <= 0:
        return {"sharpe": sharpe_ratio(x), "dsr": float("nan"), "sr0": float("nan")}

    if n_trials == 1:
        sr0 = 0.0
    else:
        sr0 = math.sqrt(va / (n - 1)) * (
            (1.0 - EULER_GAMMA) * scipy_stats.norm.ppf(1.0 - 1.0 / n_trials)
            + EULER_GAMMA * scipy_stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e))
        )
    dsr = float(scipy_stats.norm.cdf((sr - sr0) * math.sqrt(n - 1) / math.sqrt(va)))
    return {"sharpe": sharpe_ratio(x), "dsr": dsr, "sr0": sr0}
