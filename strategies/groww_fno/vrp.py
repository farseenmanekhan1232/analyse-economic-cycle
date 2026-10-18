"""F&O research stubs — VRP, IV rank, futures basis (no live orders)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import numpy as np
import pandas as pd


def realized_vol(close: pd.Series, window: int = 20) -> pd.Series:
    return close.pct_change().rolling(window).std() * np.sqrt(252)


def iv_rank(iv: pd.Series, lookback: int = 252) -> pd.Series:
    lo = iv.rolling(lookback).min()
    hi = iv.rolling(lookback).max()
    return (iv - lo) / (hi - lo).replace(0, np.nan)


def variance_risk_premium(iv: pd.Series, rv: pd.Series) -> pd.Series:
    return iv - rv.reindex(iv.index)


@dataclass
class VRPSignal:
    iv_rank: float
    vrp: float
    action: str
    rationale: str


def vrp_regime_action(
    iv: float,
    rv: float,
    iv_rank_value: float,
    *,
    sell_above: float = 0.55,
    buy_below: float = 0.20,
) -> VRPSignal:
    vrp = float(iv - rv)
    if iv_rank_value >= sell_above and vrp > 0:
        return VRPSignal(
            iv_rank=iv_rank_value,
            vrp=vrp,
            action="sell_premium",
            rationale="Elevated IV rank with positive VRP — defined-risk credit only",
        )
    if iv_rank_value <= buy_below:
        return VRPSignal(
            iv_rank=iv_rank_value,
            vrp=vrp,
            action="buy_premium",
            rationale="Cheap IV rank — debit / long vol with primary signal",
        )
    return VRPSignal(
        iv_rank=iv_rank_value,
        vrp=vrp,
        action="flat",
        rationale="IV regime neutral",
    )


def futures_basis(
    spot: float,
    near_fut: float,
    *,
    days_to_expiry: int,
) -> Dict[str, float]:
    if spot <= 0 or days_to_expiry <= 0:
        return {"basis_pts": 0.0, "basis_ann": 0.0}
    basis_pts = near_fut - spot
    basis_ann = (near_fut / spot - 1.0) * (365.0 / days_to_expiry)
    return {"basis_pts": round(basis_pts, 4), "basis_ann": round(basis_ann, 6)}


def greek_budget_ok(
    *,
    net_delta: float,
    net_vega: float,
    max_abs_delta: float = 50.0,
    max_abs_vega: float = 5000.0,
) -> bool:
    return abs(net_delta) <= max_abs_delta and abs(net_vega) <= max_abs_vega


def paper_spread_plan(
    *,
    underlying: str,
    direction: str,
    spot: float,
    iv_rank_value: float,
    p_expansion: float,
) -> Dict[str, Any]:
    if p_expansion < 0.35 and direction == "long":
        return {
            "underlying": underlying,
            "structure": "bear_call_credit_or_flat",
            "note": "Contraction posterior — prefer flat or defined-risk short call vertical",
            "iv_rank": iv_rank_value,
        }
    if direction == "long" and iv_rank_value < 0.25:
        width = round(spot * 0.02, 2)
        return {
            "underlying": underlying,
            "structure": "bull_call_debit",
            "approx_strikes": {"long": round(spot, 0), "short": round(spot + width, 0)},
            "iv_rank": iv_rank_value,
            "note": "Cheap IV — debit vertical; size by ROM",
        }
    if direction == "long" and iv_rank_value > 0.55:
        width = round(spot * 0.025, 2)
        return {
            "underlying": underlying,
            "structure": "bull_put_credit",
            "approx_strikes": {
                "short": round(spot - width * 0.5, 0),
                "long": round(spot - width, 0),
            },
            "iv_rank": iv_rank_value,
            "note": "Rich IV — put credit under support; Greek + margin caps required",
        }
    return {
        "underlying": underlying,
        "structure": "futures_or_cnc",
        "note": "Neutral IV — futures TSMOM or CNC vol-target",
        "iv_rank": iv_rank_value,
    }
