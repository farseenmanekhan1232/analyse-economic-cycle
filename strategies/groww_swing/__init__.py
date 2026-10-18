"""Groww Cloud CNC swing strategy — portable package (no Pulse/backend imports)."""

from .backtest import compare_cycle_vs_baseline, load_params, run_swing_backtest
from .catalog import ALL_APPROACH_IDS, APPROACH_META, resolve_enabled
from .cycle_filter import compute_cycle_bias
from .eval import run_full_eval
from .regime_router import eligible_approaches, router_snapshot
from .risk import filter_and_size, shares_for_risk
from .setups import detect_setup, scan_universe

__all__ = [
    "ALL_APPROACH_IDS",
    "APPROACH_META",
    "compute_cycle_bias",
    "detect_setup",
    "scan_universe",
    "shares_for_risk",
    "filter_and_size",
    "run_swing_backtest",
    "compare_cycle_vs_baseline",
    "load_params",
    "resolve_enabled",
    "eligible_approaches",
    "router_snapshot",
    "run_full_eval",
]
