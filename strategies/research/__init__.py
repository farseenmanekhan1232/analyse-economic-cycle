"""Quant research lab — no Groww/Kite broker imports."""

from strategies.research.features.feature_store import (
    build_cross_sectional_features,
    build_macro_feature_frame,
    information_coefficient_report,
    residualize_returns,
)
from strategies.research.labels.triple_barrier import apply_triple_barrier
from strategies.research.models.meta_labeling import fit_meta_labeler, primary_side_from_features
from strategies.research.models.regime_hmm import RegimeHMM, fit_regime_hmm
from strategies.research.portfolio.construction import (
    correlation_budget_ok,
    hierarchical_risk_parity,
    volatility_target_weights,
)
from strategies.research.validation.metrics import (
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_ratio,
)
from strategies.research.validation.purged_cv import combinatorial_purged_paths, purged_train_test_split

__all__ = [
    "build_macro_feature_frame",
    "build_cross_sectional_features",
    "information_coefficient_report",
    "residualize_returns",
    "apply_triple_barrier",
    "primary_side_from_features",
    "fit_meta_labeler",
    "RegimeHMM",
    "fit_regime_hmm",
    "volatility_target_weights",
    "hierarchical_risk_parity",
    "correlation_budget_ok",
    "sharpe_ratio",
    "probabilistic_sharpe_ratio",
    "deflated_sharpe_ratio",
    "probability_of_backtest_overfitting",
    "purged_train_test_split",
    "combinatorial_purged_paths",
]
