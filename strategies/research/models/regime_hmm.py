"""Probabilistic regime model — Gaussian HMM on macro feature emissions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd


def _standardize(X: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    mu = np.nanmean(X, axis=0)
    sd = np.nanstd(X, axis=0)
    sd = np.where(sd < 1e-12, 1.0, sd)
    Z = (X - mu) / sd
    Z = np.nan_to_num(Z, nan=0.0, posinf=0.0, neginf=0.0)
    return Z, mu, sd


def _logsumexp(a: np.ndarray, axis: int = -1) -> np.ndarray:
    m = np.max(a, axis=axis, keepdims=True)
    return np.squeeze(m, axis=axis) + np.log(np.sum(np.exp(a - m), axis=axis))


@dataclass
class RegimeHMM:
    """2–3 state Gaussian HMM with diagonal covariance (pure numpy)."""

    n_states: int = 2
    n_iter: int = 50
    random_state: int = 0
    means_: Optional[np.ndarray] = None
    covars_: Optional[np.ndarray] = None
    startprob_: Optional[np.ndarray] = None
    transmat_: Optional[np.ndarray] = None
    feature_names_: Optional[list] = None
    mu_: Optional[np.ndarray] = None
    sd_: Optional[np.ndarray] = None
    # State index interpreted as "expansion-like" after fit
    expansion_state_: int = 0

    def fit(self, features: pd.DataFrame) -> "RegimeHMM":
        df = features.dropna().copy()
        if df.empty or len(df) < 40:
            raise ValueError("Need ≥40 observations to fit RegimeHMM")
        self.feature_names_ = list(df.columns)
        X, self.mu_, self.sd_ = _standardize(df.values.astype(float))
        T, D = X.shape
        K = self.n_states
        rng = np.random.default_rng(self.random_state)

        # K-means-ish init
        centers = X[rng.choice(T, size=K, replace=False)]
        for _ in range(10):
            dist = ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
            assign = dist.argmin(axis=1)
            for k in range(K):
                if np.any(assign == k):
                    centers[k] = X[assign == k].mean(axis=0)
        self.means_ = centers
        self.covars_ = np.ones((K, D))
        for k in range(K):
            if np.any(assign == k):
                var = X[assign == k].var(axis=0)
                self.covars_[k] = np.maximum(var, 1e-3)
        self.startprob_ = np.full(K, 1.0 / K)
        self.transmat_ = np.full((K, K), 1.0 / K)
        # Prefer persistence
        self.transmat_ = 0.85 * np.eye(K) + 0.15 * self.transmat_
        self.transmat_ /= self.transmat_.sum(axis=1, keepdims=True)

        for _ in range(self.n_iter):
            # E-step
            log_em = self._log_emission(X)
            log_alpha = np.zeros((T, K))
            log_alpha[0] = np.log(self.startprob_ + 1e-16) + log_em[0]
            for t in range(1, T):
                for k in range(K):
                    log_alpha[t, k] = log_em[t, k] + _logsumexp(
                        log_alpha[t - 1] + np.log(self.transmat_[:, k] + 1e-16)
                    )
            log_beta = np.zeros((T, K))
            for t in range(T - 2, -1, -1):
                for k in range(K):
                    log_beta[t, k] = _logsumexp(
                        np.log(self.transmat_[k] + 1e-16) + log_em[t + 1] + log_beta[t + 1]
                    )
            log_gamma = log_alpha + log_beta
            log_gamma -= _logsumexp(log_gamma, axis=1)[:, None]
            gamma = np.exp(log_gamma)

            # xi
            xi = np.zeros((T - 1, K, K))
            for t in range(T - 1):
                for i in range(K):
                    for j in range(K):
                        xi[t, i, j] = (
                            log_alpha[t, i]
                            + np.log(self.transmat_[i, j] + 1e-16)
                            + log_em[t + 1, j]
                            + log_beta[t + 1, j]
                        )
                xi[t] = np.exp(xi[t] - _logsumexp(xi[t].ravel()))

            # M-step
            self.startprob_ = gamma[0] / gamma[0].sum()
            for i in range(K):
                denom = gamma[:-1, i].sum()
                for j in range(K):
                    self.transmat_[i, j] = xi[:, i, j].sum() / (denom + 1e-16)
            self.transmat_ /= self.transmat_.sum(axis=1, keepdims=True)
            for k in range(K):
                w = gamma[:, k][:, None]
                self.means_[k] = (w * X).sum(axis=0) / (w.sum() + 1e-16)
                diff = X - self.means_[k]
                self.covars_[k] = (w * diff**2).sum(axis=0) / (w.sum() + 1e-16)
                self.covars_[k] = np.maximum(self.covars_[k], 1e-3)

        # Label expansion state = higher mean breadth / lower vol if present
        names = self.feature_names_ or []
        scores = []
        for k in range(K):
            s = 0.0
            if "breadth" in names:
                s += self.means_[k, names.index("breadth")]
            if "cyc_def_mom" in names:
                s += self.means_[k, names.index("cyc_def_mom")]
            if "realized_vol" in names:
                s -= self.means_[k, names.index("realized_vol")]
            if "vix_z" in names:
                s -= self.means_[k, names.index("vix_z")]
            scores.append(s)
        self.expansion_state_ = int(np.argmax(scores))
        return self

    def _log_emission(self, X: np.ndarray) -> np.ndarray:
        T, D = X.shape
        K = self.n_states
        out = np.zeros((T, K))
        for k in range(K):
            var = self.covars_[k]
            coef = -0.5 * (np.sum(np.log(2 * np.pi * var)) + np.sum((X - self.means_[k]) ** 2 / var, axis=1))
            out[:, k] = coef
        return out

    def predict_proba(self, features: pd.DataFrame) -> pd.DataFrame:
        if self.means_ is None or self.feature_names_ is None:
            raise RuntimeError("RegimeHMM not fitted")
        df = features[self.feature_names_].copy()
        X = (df.values.astype(float) - self.mu_) / self.sd_
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        T, K = X.shape[0], self.n_states
        log_em = self._log_emission(X)
        log_alpha = np.zeros((T, K))
        log_alpha[0] = np.log(self.startprob_ + 1e-16) + log_em[0]
        for t in range(1, T):
            for k in range(K):
                log_alpha[t, k] = log_em[t, k] + _logsumexp(
                    log_alpha[t - 1] + np.log(self.transmat_[:, k] + 1e-16)
                )
        log_beta = np.zeros((T, K))
        for t in range(T - 2, -1, -1):
            for k in range(K):
                log_beta[t, k] = _logsumexp(
                    np.log(self.transmat_[k] + 1e-16) + log_em[t + 1] + log_beta[t + 1]
                )
        log_gamma = log_alpha + log_beta
        log_gamma -= _logsumexp(log_gamma, axis=1)[:, None]
        gamma = np.exp(log_gamma)
        cols = {f"p_state_{k}": gamma[:, k] for k in range(K)}
        cols["p_expansion"] = gamma[:, self.expansion_state_]
        cols["p_contraction"] = 1.0 - cols["p_expansion"]
        return pd.DataFrame(cols, index=df.index)


def fit_regime_hmm(features: pd.DataFrame, n_states: int = 2) -> Tuple[RegimeHMM, pd.DataFrame]:
    model = RegimeHMM(n_states=n_states)
    model.fit(features)
    return model, model.predict_proba(features)


def size_multiplier_from_posterior(
    p_expansion: float,
    *,
    fear_cut: float = 0.25,
    full_size_above: float = 0.65,
) -> float:
    """Map regime posterior to risk multiplier in [0, 1]."""
    p = float(p_expansion)
    if p <= fear_cut:
        return 0.0
    if p >= full_size_above:
        return 1.0
    return (p - fear_cut) / (full_size_above - fear_cut)
