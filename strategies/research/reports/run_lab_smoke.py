"""End-to-end research lab smoke on synthetic panel (CI only — not promotion)."""

from __future__ import annotations

import json
from typing import Any, Dict

import numpy as np
import pandas as pd

from strategies.research.features.feature_store import (
    build_cross_sectional_features,
    build_macro_feature_frame,
    forward_returns_panel,
    information_coefficient_report,
    panel_from_synthetic,
)
from strategies.groww_fno.vrp import paper_spread_plan, vrp_regime_action
from strategies.research.labels.triple_barrier import apply_triple_barrier
from strategies.research.models.meta_labeling import fit_meta_labeler, primary_side_from_features
from strategies.research.models.regime_hmm import fit_regime_hmm, size_multiplier_from_posterior
from strategies.research.portfolio.construction import (
    hierarchical_risk_parity,
    volatility_target_weights,
)
from strategies.research.validation.metrics import (
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_ratio,
)
from strategies.research.validation.purged_cv import combinatorial_purged_paths


def run_lab_smoke(n_days: int = 320, seed: int = 11) -> Dict[str, Any]:
    panel = panel_from_synthetic(n_days=n_days, n_assets=8, seed=seed)
    closes = pd.DataFrame({k: v["close"] for k, v in panel.items()})
    macro = build_macro_feature_frame(closes)
    hmm, post = fit_regime_hmm(macro.dropna(), n_states=2)
    p_exp = float(post["p_expansion"].iloc[-1])

    xs = build_cross_sectional_features(panel)
    fwd = forward_returns_panel(panel, horizon=10)
    ic = information_coefficient_report(xs, fwd)

    # Labels on first asset
    sym0 = list(panel.keys())[0]
    sides = []
    for dt, row in xs.xs(sym0, level="symbol").iterrows():
        pe = float(post["p_expansion"].reindex([dt]).ffill().iloc[0]) if dt in post.index else p_exp
        sides.append(primary_side_from_features(row, p_expansion=pe))
    side_s = pd.Series(sides, index=xs.xs(sym0, level="symbol").index)
    labels = apply_triple_barrier(panel[sym0], side=side_s)

    feat_sym = xs.xs(sym0, level="symbol").join(post[["p_expansion"]], how="left")
    feat_sym["p_expansion"] = feat_sym["p_expansion"].ffill().fillna(0.5)
    feat_sym["side"] = side_s.reindex(feat_sym.index).fillna(0)
    meta = fit_meta_labeler(feat_sym, labels, p_expansion=feat_sym["p_expansion"])

    # Synthetic strategy returns for validation demos
    rng = np.random.default_rng(seed)
    rets = pd.Series(rng.normal(0.0004, 0.01, n_days))
    paths = combinatorial_purged_paths(len(rets), n_groups=6, n_test_groups=2, max_paths=15)
    is_s, oos_s = [], []
    for sp in paths:
        tr, te = rets.iloc[sp.train_idx], rets.iloc[sp.test_idx]
        if len(tr) > 10 and len(te) > 5:
            is_s.append(sharpe_ratio(tr))
            oos_s.append(sharpe_ratio(te))
    psr = probabilistic_sharpe_ratio(rets)
    dsr = deflated_sharpe_ratio(rets, n_trials=max(len(paths), 1))
    pbo = probability_of_backtest_overfitting(is_s, oos_s)

    rets_panel = closes.pct_change().dropna()
    w_vol = volatility_target_weights(rets_panel, target_vol=0.12)
    w_hrp = hierarchical_risk_parity(rets_panel)

    # Fake IV path for VRP stub
    iv = 0.18 + post["p_contraction"].reindex(closes.index).ffill().fillna(0.5) * 0.08
    rv = closes.mean(axis=1).pct_change().rolling(20).std() * np.sqrt(252)
    iv_r = ((iv - iv.rolling(60).min()) / (iv.rolling(60).max() - iv.rolling(60).min())).iloc[-1]
    vrp_act = vrp_regime_action(
        float(iv.iloc[-1]),
        float(rv.dropna().iloc[-1]) if rv.dropna().size else 0.15,
        float(iv_r) if np.isfinite(iv_r) else 0.5,
    )
    spread = paper_spread_plan(
        underlying="NIFTY",
        direction="long",
        spot=float(closes.iloc[-1].mean()),
        iv_rank_value=float(vrp_act.iv_rank),
        p_expansion=p_exp,
    )

    report = {
        "quality_note": "Synthetic smoke only — not a promotion artifact",
        "regime": {
            "p_expansion": round(p_exp, 4),
            "p_contraction": round(1 - p_exp, 4),
            "expansion_state": hmm.expansion_state_,
            "size_multiplier": round(size_multiplier_from_posterior(p_exp), 4),
        },
        "ic_top": ic.head(5).to_dict(orient="records") if not ic.empty else [],
        "labels": {
            "n": int(len(labels)),
            "success_rate": round(float(labels["bin_success"].mean()), 3)
            if "bin_success" in labels.columns
            else None,
        },
        "meta_fitted": meta.fitted_,
        "validation": {
            "n_cpcv_paths": len(paths),
            "sharpe": round(sharpe_ratio(rets), 4),
            "psr": round(psr, 4),
            "dsr": round(dsr, 4),
            "pbo": round(pbo, 4),
            "n_trials_for_dsr": len(paths),
        },
        "portfolio": {"vol_target": w_vol, "hrp": w_hrp},
        "fno": {"vrp_action": vrp_act.action, "spread_plan": spread},
    }
    return report


def main() -> None:
    print(json.dumps(run_lab_smoke(), indent=2, default=str))


if __name__ == "__main__":
    main()
