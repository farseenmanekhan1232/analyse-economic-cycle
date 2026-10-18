"""Portfolio construction: vol targeting, HRP, correlation budget, CVaR hint."""

from __future__ import annotations

from typing import Dict, Mapping, Optional, Sequence

import numpy as np
import pandas as pd


def _cov_from_returns(returns: pd.DataFrame) -> pd.DataFrame:
    return returns.cov()


def volatility_target_weights(
    returns: pd.DataFrame,
    *,
    target_vol: float = 0.12,
    max_weight: float = 0.35,
    prior: Optional[Mapping[str, float]] = None,
) -> Dict[str, float]:
    """
    Inverse-vol weights scaled so projected ann. vol ≈ target_vol.
    `prior` optional tilts (e.g. meta-size × regime).
    """
    r = returns.dropna(how="all").fillna(0.0)
    if r.empty or r.shape[1] == 0:
        return {}
    vol = r.std() * np.sqrt(252)
    vol = vol.replace(0, np.nan).dropna()
    if vol.empty:
        n = r.shape[1]
        return {c: 1.0 / n for c in r.columns}
    inv = 1.0 / vol
    if prior:
        for k, v in prior.items():
            if k in inv.index:
                inv[k] *= max(0.0, float(v))
    w = inv / inv.sum()
    w = w.clip(upper=max_weight)
    w = w / w.sum()
    # Scale to target vol
    cov = r[w.index].cov() * 252
    port_var = float(np.asarray(w).T @ cov.values @ np.asarray(w))
    port_vol = np.sqrt(max(port_var, 0.0))
    scale = (target_vol / port_vol) if port_vol > 1e-12 else 1.0
    scale = float(np.clip(scale, 0.0, 2.0))
    return {k: float(w[k] * scale) for k in w.index}


def _cluster_var(cov: np.ndarray, items: Sequence[int]) -> float:
    sub = cov[np.ix_(items, items)]
    w = np.ones(len(items)) / len(items)
    return float(w @ sub @ w)


def hierarchical_risk_parity(returns: pd.DataFrame) -> Dict[str, float]:
    """
    Simplified HRP: recursive bisection on correlation distance.
    """
    r = returns.dropna(how="all").fillna(0.0)
    cols = list(r.columns)
    n = len(cols)
    if n == 0:
        return {}
    if n == 1:
        return {cols[0]: 1.0}
    cov = r.cov().values * 252
    corr = r.corr().fillna(0).values
    dist = np.sqrt(0.5 * (1 - corr))
    # Seriation via nearest-neighbor
    order = [0]
    remaining = set(range(1, n))
    while remaining:
        last = order[-1]
        nxt = min(remaining, key=lambda j: dist[last, j])
        order.append(nxt)
        remaining.remove(nxt)

    def _allocate(idxs: list) -> np.ndarray:
        if len(idxs) == 1:
            return np.array([1.0])
        mid = len(idxs) // 2
        left, right = idxs[:mid], idxs[mid:]
        wl = _allocate(left)
        wr = _allocate(right)
        var_l = _cluster_var(cov, left)
        var_r = _cluster_var(cov, right)
        a = 1.0 - var_l / (var_l + var_r + 1e-16)
        return np.concatenate([wl * a, wr * (1 - a)])

    w = _allocate(order)
    # Map back
    out = {cols[order[i]]: float(w[i]) for i in range(n)}
    s = sum(out.values())
    return {k: v / s for k, v in out.items()}


def correlation_budget_ok(
    candidate: str,
    returns: pd.DataFrame,
    current_holdings: Sequence[str],
    *,
    max_avg_corr: float = 0.75,
    lookback: int = 60,
) -> bool:
    if candidate not in returns.columns:
        return False
    if not current_holdings:
        return True
    cols = [c for c in current_holdings if c in returns.columns] + [candidate]
    sub = returns[cols].tail(lookback).dropna()
    if sub.shape[0] < 20:
        return True
    corr = sub.corr()[candidate].drop(labels=[candidate], errors="ignore")
    if corr.empty:
        return True
    return float(corr.mean()) <= max_avg_corr


def cvar_budget_scale(
    returns: pd.Series,
    *,
    confidence: float = 0.95,
    max_abs_cvar: float = 0.03,
) -> float:
    """Scale ∈ (0,1] so historical CVaR of sized returns respects budget."""
    r = returns.dropna()
    if len(r) < 30:
        return 1.0
    q = r.quantile(1 - confidence)
    tail = r[r <= q]
    cvar = float(tail.mean()) if len(tail) else float(q)
    if cvar >= 0:
        return 1.0
    # cvar is negative; want |cvar| * scale <= max_abs_cvar
    scale = max_abs_cvar / abs(cvar)
    return float(np.clip(scale, 0.0, 1.0))
