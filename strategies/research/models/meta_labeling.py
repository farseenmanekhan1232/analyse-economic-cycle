"""Primary side + meta-labeler (AFML ch.3 style)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

MappingLike = Any


def primary_side_from_features(
    feat_row: MappingLike,
    *,
    mom_col: str = "mom_63",
    rs_col: str = "rs_63",
    resid_z_col: str = "resid_z_20",
    p_expansion: float = 0.5,
) -> int:
    """
    Sparse primary rule: long if TS/CS momentum aligns and regime not hostile.
    Returns +1 long, 0 flat (no short CNC book by default).
    """
    mom = _get(feat_row, mom_col)
    rs = _get(feat_row, rs_col, default=0.0)
    z = _get(feat_row, resid_z_col, default=0.0)
    if p_expansion < 0.35:
        # Range / contraction: only residual MR bounce candidates
        if z is not None and z < -1.0:
            return 1
        return 0
    if mom is not None and mom > 0 and (rs is None or rs > -0.02):
        return 1
    return 0


def _get(row: Any, key: str, default: Optional[float] = None) -> Optional[float]:
    if isinstance(row, pd.Series):
        if key not in row.index:
            return default
        v = row[key]
    elif isinstance(row, dict):
        v = row.get(key, default)
    else:
        return default
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return default
    return float(v)


@dataclass
class MetaLabeler:
    """Logistic meta-labeler on [features, side, p_expansion] → P(success)."""

    feature_cols: List[str] = field(default_factory=list)
    weights_: Optional[np.ndarray] = None  # includes bias
    fitted_: bool = False

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        *,
        feature_cols: Optional[Sequence[str]] = None,
        max_iter: int = 200,
        lr: float = 0.05,
    ) -> "MetaLabeler":
        cols = list(feature_cols) if feature_cols else list(X.columns)
        self.feature_cols = cols
        mat = X[cols].astype(float).replace([np.inf, -np.inf], np.nan)
        mask = mat.notna().all(axis=1) & y.notna()
        mat = mat.loc[mask]
        yy = y.loc[mask].astype(float).clip(0, 1).values
        if len(mat) < 30:
            # Fallback: constant prior
            self.weights_ = np.zeros(len(cols) + 1)
            self.weights_[0] = np.log((yy.mean() + 1e-3) / (1 - yy.mean() + 1e-3)) if len(yy) else 0.0
            self.fitted_ = True
            return self

        # Standardize
        mu = mat.mean()
        sd = mat.std().replace(0, 1.0)
        Z = ((mat - mu) / sd).values
        self._mu = mu.values
        self._sd = sd.values
        n, d = Z.shape
        w = np.zeros(d + 1)
        Xb = np.column_stack([np.ones(n), Z])
        for _ in range(max_iter):
            z = Xb @ w
            p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
            grad = Xb.T @ (p - yy) / n
            w -= lr * grad
        self.weights_ = w
        self.fitted_ = True
        return self

    def predict_proba(self, X: pd.DataFrame) -> pd.Series:
        if not self.fitted_ or self.weights_ is None:
            raise RuntimeError("MetaLabeler not fitted")
        mat = X[self.feature_cols].astype(float)
        Z = (mat.values - self._mu) / self._sd
        Z = np.nan_to_num(Z, nan=0.0)
        Xb = np.column_stack([np.ones(len(Z)), Z])
        logits = Xb @ self.weights_
        p = 1.0 / (1.0 + np.exp(-np.clip(logits, -30, 30)))
        return pd.Series(p, index=X.index, name="p_meta")

    def size_from_proba(self, p: float, *, min_p: float = 0.55, regime_m: float = 1.0) -> float:
        if p < min_p:
            return 0.0
        return float(np.clip((p - min_p) / (1 - min_p), 0, 1) * regime_m)


def fit_meta_labeler(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    feature_cols: Optional[Sequence[str]] = None,
    p_expansion: Optional[pd.Series] = None,
) -> MetaLabeler:
    """Align features with triple-barrier bin_success; optional regime posterior column."""
    y = labels["bin_success"] if "bin_success" in labels.columns else (labels["ret"] > 0).astype(int)
    X = features.copy()
    if p_expansion is not None and "p_expansion" not in X.columns:
        X = X.join(p_expansion.rename("p_expansion"), how="left")
        X["p_expansion"] = X["p_expansion"].fillna(0.5)
    elif "p_expansion" in X.columns:
        X["p_expansion"] = X["p_expansion"].fillna(0.5)
    if "side" in labels.columns and "side" not in X.columns:
        X = X.join(labels["side"], how="left")
    # Only rows where primary proposed a side
    if "side" in X.columns:
        mask = X["side"].fillna(0) != 0
        X = X.loc[mask]
        y = y.reindex(X.index)
    cols = feature_cols
    if cols is None:
        cols = [c for c in X.columns if X[c].dtype != object]
    model = MetaLabeler()
    return model.fit(X, y, feature_cols=cols)
