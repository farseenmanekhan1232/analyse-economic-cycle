"""Tests for quant research lab modules."""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.groww_fno.vrp import paper_spread_plan, vrp_regime_action
from strategies.research.features.feature_store import (
    build_macro_feature_frame,
    information_coefficient_report,
    panel_from_synthetic,
)
from strategies.research.labels.triple_barrier import apply_triple_barrier
from strategies.research.models.regime_hmm import fit_regime_hmm, size_multiplier_from_posterior
from strategies.research.portfolio.construction import hierarchical_risk_parity, volatility_target_weights
from strategies.research.reports.run_lab_smoke import run_lab_smoke
from strategies.research.validation.metrics import (
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    sharpe_ratio,
)
from strategies.research.validation.purged_cv import combinatorial_purged_paths


def test_macro_and_hmm():
    panel = panel_from_synthetic(n_days=200, seed=1)
    closes = pd.DataFrame({k: v["close"] for k, v in panel.items()})
    macro = build_macro_feature_frame(closes).dropna()
    assert not macro.empty
    model, post = fit_regime_hmm(macro, n_states=2)
    assert "p_expansion" in post.columns
    assert 0 <= size_multiplier_from_posterior(0.1) <= 1
    assert model.n_states == 2


def test_triple_barrier_and_ic():
    panel = panel_from_synthetic(n_days=180, seed=2)
    sym = list(panel.keys())[0]
    labels = apply_triple_barrier(panel[sym])
    assert "ret" in labels.columns
    assert set(labels["touch"].unique()) <= {"pt", "sl", "vb", "flat"}


def test_validation_metrics():
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0005, 0.01, 200)
    assert sharpe_ratio(rets) != 0
    assert 0 <= probabilistic_sharpe_ratio(rets) <= 1
    assert 0 <= deflated_sharpe_ratio(rets, n_trials=20) <= 1
    paths = combinatorial_purged_paths(200, max_paths=10)
    assert len(paths) >= 1


def test_portfolio_and_fno():
    panel = panel_from_synthetic(n_days=150, seed=3)
    rets = pd.DataFrame({k: v["close"].pct_change() for k, v in panel.items()}).dropna()
    w = volatility_target_weights(rets)
    assert abs(sum(w.values()) - sum(w.values())) == 0
    assert abs(sum(hierarchical_risk_parity(rets).values()) - 1) < 1e-6
    act = vrp_regime_action(0.22, 0.15, 0.7)
    assert act.action in {"sell_premium", "buy_premium", "flat"}
    plan = paper_spread_plan(
        underlying="NIFTY", direction="long", spot=22000, iv_rank_value=0.2, p_expansion=0.7
    )
    assert "structure" in plan


def test_lab_smoke():
    report = run_lab_smoke(n_days=220, seed=5)
    assert "regime" in report
    assert "validation" in report
    assert report["validation"]["n_cpcv_paths"] >= 1
    assert "fno" in report
