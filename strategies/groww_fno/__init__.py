"""F&O variance risk premium & basis research helpers (dry-run / paper only)."""

from strategies.groww_fno.vrp import (
    futures_basis,
    greek_budget_ok,
    iv_rank,
    paper_spread_plan,
    realized_vol,
    variance_risk_premium,
    vrp_regime_action,
)

__all__ = [
    "realized_vol",
    "iv_rank",
    "variance_risk_premium",
    "vrp_regime_action",
    "futures_basis",
    "greek_budget_ok",
    "paper_spread_plan",
]
