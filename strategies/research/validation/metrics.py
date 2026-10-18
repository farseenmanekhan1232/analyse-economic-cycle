"""Sharpe, PSR, DSR, PBO — selection-bias aware metrics (numpy only)."""

from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np


def _norm_cdf(x: float) -> float:
    return float(0.5 * (1.0 + math.erf(x / math.sqrt(2.0))))


def _norm_ppf(p: float) -> float:
    """Approximate inverse normal CDF (Beasley-Springer-Moro style, low precision OK)."""
    p = float(np.clip(p, 1e-10, 1 - 1e-10))
    # Acklam approximation
    a = [
        -3.969683028665376e1,
        2.209460984245205e2,
        -2.759285104469687e2,
        1.383577518672690e2,
        -3.066479806614736e1,
        2.506628277459239e0,
    ]
    b = [
        -5.447609879822406e1,
        1.615858368580409e2,
        -1.556989798598866e2,
        6.680131188771972e1,
        -1.328068155288572e1,
    ]
    c = [
        -7.784894002430293e-3,
        -3.223964580411365e-1,
        -2.400758277161838e0,
        -2.549732539343734e0,
        4.374664141464968e0,
        2.938163982698783e0,
    ]
    d = [
        7.784695709041462e-3,
        3.224671290700398e-1,
        2.445134137142996e0,
        3.754408661907416e0,
    ]
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = np.sqrt(-2 * np.log(p))
        return (
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        )
    if p > phigh:
        q = np.sqrt(-2 * np.log(1 - p))
        return -(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


def sharpe_ratio(returns: Sequence[float], periods_per_year: float = 252.0) -> float:
    r = np.asarray(list(returns), dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 5:
        return 0.0
    mu, sd = r.mean(), r.std(ddof=1)
    if sd < 1e-12:
        return 0.0
    return float(mu / sd * np.sqrt(periods_per_year))


def _skew_kurt(r: np.ndarray) -> tuple:
    n = len(r)
    if n < 5:
        return 0.0, 0.0
    m = r.mean()
    s = r.std(ddof=1)
    if s < 1e-12:
        return 0.0, 0.0
    z = (r - m) / s
    skew = float(np.mean(z**3) * n / ((n - 1) * (n - 2)) * n) if n > 2 else 0.0
    # excess kurtosis
    kurt = float(np.mean(z**4) - 3.0)
    return skew, kurt


def probabilistic_sharpe_ratio(
    returns: Sequence[float],
    *,
    sr_benchmark: float = 0.0,
    periods_per_year: float = 252.0,
) -> float:
    r = np.asarray(list(returns), dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 10:
        return 0.0
    mu, sd = r.mean(), r.std(ddof=1)
    if sd < 1e-12:
        return 0.0
    sr_hat = mu / sd
    skew, kurt = _skew_kurt(r)
    sr_star = sr_benchmark / np.sqrt(periods_per_year)
    numer = (sr_hat - sr_star) * np.sqrt(n - 1)
    denom = np.sqrt(max(1e-12, 1 - skew * sr_hat + ((kurt + 3) / 4.0) * sr_hat**2))
    return _norm_cdf(numer / denom)


def deflated_sharpe_ratio(
    returns: Sequence[float],
    *,
    n_trials: int,
    var_sharpe_across_trials: Optional[float] = None,
    periods_per_year: float = 252.0,
) -> float:
    r = np.asarray(list(returns), dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 10 or n_trials < 1:
        return 0.0
    g = 0.5772156649
    if n_trials == 1:
        sr_0 = 0.0
    else:
        inv1 = _norm_ppf(1 - 1.0 / n_trials)
        inv2 = _norm_ppf(1 - 1.0 / (n_trials * np.e))
        e_max = (1 - g) * inv1 + g * inv2
        vs = var_sharpe_across_trials if var_sharpe_across_trials and var_sharpe_across_trials > 0 else 1.0 / n
        sr_0 = float(e_max * np.sqrt(vs))
    return probabilistic_sharpe_ratio(
        r,
        sr_benchmark=sr_0 * np.sqrt(periods_per_year),
        periods_per_year=periods_per_year,
    )


def probability_of_backtest_overfitting(
    is_sharpes: Sequence[float],
    oos_sharpes: Sequence[float],
) -> float:
    is_s = np.asarray(list(is_sharpes), dtype=float)
    oos_s = np.asarray(list(oos_sharpes), dtype=float)
    m = min(len(is_s), len(oos_s))
    if m < 4:
        return 1.0
    is_s, oos_s = is_s[:m], oos_s[:m]
    order = np.argsort(is_s)
    fails = 0
    trials = 0
    for i in range(m):
        for j in range(i + 1, m):
            a, b = order[i], order[j]
            trials += 1
            if oos_s[b] < oos_s[a]:
                fails += 1
    return float(fails / trials) if trials else 1.0
