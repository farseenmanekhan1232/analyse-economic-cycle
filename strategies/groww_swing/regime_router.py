"""Map cycle bias → which named approaches may scan today."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .catalog import ALL_APPROACH_IDS, prioritize, resolve_enabled
from .cycle_filter import DEFENSIVE_SECTORS


# Default eligibility by macro phase (intersected with enabled_approaches)
PHASE_APPROACHES: Dict[str, List[str]] = {
    "expansion": [
        "trend_pullback",
        "trend_breakout",
        "rs_momentum",
        "vol_compression_break",
    ],
    "contraction": [
        "defensive_mean_reversion",
        "vol_compression_break",
    ],
    "unknown": [
        "vol_compression_break",
    ],
}


def eligible_approaches(
    bias: Mapping[str, Any],
    params: Mapping[str, Any],
) -> List[str]:
    """
    Approaches allowed given cycle bias + params.

    Hard stops:
    - risk_off → empty (no new risk)
    - VIX fear is already folded into risk_off by cycle_filter
    """
    enabled = set(resolve_enabled(params))
    if bias.get("risk_off"):
        return []

    phase = str(bias.get("phase") or "unknown")
    sub = str(bias.get("sub_phase") or "")
    base = list(PHASE_APPROACHES.get(phase, PHASE_APPROACHES["unknown"]))

    # Late expansion still trend; early expansion same set
    if sub in {"early_expansion", "late_expansion"} and phase != "contraction":
        base = list(PHASE_APPROACHES["expansion"])

    if phase == "contraction":
        if not bool(params.get("allow_contraction_defensives", True)):
            return []
        # Only defensive MR + squeeze when contraction sleeve is on
        base = list(PHASE_APPROACHES["contraction"])

    chosen = [a for a in prioritize(base) if a in enabled]
    return chosen


def filter_sectors_for_approach(
    approach_id: str,
    allowed_sectors: List[str],
) -> List[str]:
    """Narrow sector list for approaches that only trade a sleeve."""
    if approach_id == "defensive_mean_reversion":
        defensive = set(DEFENSIVE_SECTORS)
        return [s for s in allowed_sectors if s in defensive]
    return list(allowed_sectors)


def router_snapshot(
    bias: Mapping[str, Any],
    params: Mapping[str, Any],
) -> Dict[str, Any]:
    """JSON-friendly summary for scan/UI."""
    eligible = eligible_approaches(bias, params)
    return {
        "enabled": resolve_enabled(params),
        "eligible_today": eligible,
        "phase": bias.get("phase"),
        "sub_phase": bias.get("sub_phase"),
        "risk_off": bool(bias.get("risk_off")),
        "all_approach_ids": list(ALL_APPROACH_IDS),
    }
