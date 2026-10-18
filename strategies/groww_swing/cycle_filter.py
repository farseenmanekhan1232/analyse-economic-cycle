"""Portable cycle / sector filter operating on OHLCV DataFrames only.

Distilled from Pulse market_signals + regime SUB_PHASE_SECTORS.
No Kite, SQL, or FastAPI imports — safe for Groww Cloud.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

import numpy as np
import pandas as pd

CYCLICAL_SECTORS = [
    "BANK",
    "AUTO",
    "REALTY",
    "INFRA",
    "METAL",
    "ENERGY",
    "PSU_BANK",
    "PVT_BANK",
    "OIL_GAS",
    "CONSUMER_DURABLES",
]
DEFENSIVE_SECTORS = [
    "PHARMA",
    "FMCG",
    "HEALTHCARE",
    "IT",
    "MEDIA",
]
COMMODITY_SECTORS = ["METAL", "OIL_GAS", "ENERGY"]
CONSUMER_SECTORS = ["FMCG", "CONSUMER_DURABLES", "AUTO"]
GROWTH_SECTORS = ["IT", "PHARMA", "HEALTHCARE"]
VALUE_SECTORS = ["BANK", "PSU_BANK", "PVT_BANK", "ENERGY", "METAL"]

SUB_PHASE_SECTORS = {
    "early_expansion": ["BANK", "PVT_BANK", "AUTO", "REALTY", "CONSUMER_DURABLES", "INFRA"],
    "late_expansion": ["ENERGY", "METAL", "OIL_GAS", "IT"],
    "contraction": ["PHARMA", "FMCG", "HEALTHCARE", "IT", "MEDIA"],
}


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure DatetimeIndex and lowercase ohlcv columns."""
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        if "timestamp" in out.columns:
            out["timestamp"] = pd.to_datetime(out["timestamp"])
            out = out.set_index("timestamp")
        elif "date" in out.columns:
            out["date"] = pd.to_datetime(out["date"])
            out = out.set_index("date")
        else:
            out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    rename = {c: c.lower() for c in out.columns}
    out = out.rename(columns=rename)
    return out


def closes_frame(sector_data: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Build a wide close DataFrame keyed by sector id."""
    closes: Dict[str, pd.Series] = {}
    for key, df in sector_data.items():
        if df is None or df.empty:
            continue
        norm = _normalize_ohlcv(df)
        if "close" not in norm.columns:
            continue
        series = norm["close"].dropna().astype(float)
        if series.empty:
            continue
        closes[key] = series
    if not closes:
        return pd.DataFrame()
    return pd.DataFrame(closes).dropna(how="all")


def _trend_signal(series: pd.Series, lookback: int = 63) -> Dict[str, Any]:
    if len(series) < lookback:
        return {"signal": "unknown", "trend_pct": 0.0, "confidence": 0.3}
    ma_short = series.rolling(21).mean()
    ma_long = series.rolling(lookback).mean()
    trend = float((series.iloc[-1] / series.iloc[-lookback] - 1) * 100)
    if ma_short.iloc[-1] > ma_long.iloc[-1] and trend > 2:
        return {
            "signal": "rising",
            "trend_pct": round(trend, 2),
            "confidence": min(0.9, 0.5 + abs(trend) / 20),
        }
    if ma_short.iloc[-1] < ma_long.iloc[-1] and trend < -2:
        return {
            "signal": "falling",
            "trend_pct": round(trend, 2),
            "confidence": min(0.9, 0.5 + abs(trend) / 20),
        }
    return {"signal": "flat", "trend_pct": round(trend, 2), "confidence": 0.4}


def cyclical_defensive_ratio(closes: pd.DataFrame) -> Dict[str, Any]:
    cyc = [s for s in CYCLICAL_SECTORS if s in closes.columns]
    dfn = [s for s in DEFENSIVE_SECTORS if s in closes.columns]
    if not cyc or not dfn:
        return {"signal": "unknown", "ratio": None}
    ratio = (closes[cyc].mean(axis=1) / closes[dfn].mean(axis=1)).dropna()
    if ratio.empty:
        return {"signal": "unknown", "ratio": None}
    ratio_norm = ratio / ratio.iloc[0] if ratio.iloc[0] != 0 else ratio
    trend = _trend_signal(ratio_norm)
    signal = (
        "expansion"
        if trend["signal"] == "rising"
        else "contraction"
        if trend["signal"] == "falling"
        else "transition"
    )
    return {
        "signal": signal,
        "ratio": round(float(ratio_norm.iloc[-1]), 4),
        "trend_3m_pct": trend["trend_pct"],
        "confidence": trend["confidence"],
    }


def credit_cycle(closes: pd.DataFrame) -> Dict[str, Any]:
    bank_s = [s for s in ["BANK", "PVT_BANK", "PSU_BANK"] if s in closes.columns]
    if not bank_s:
        return {"signal": "neutral", "ratio": None}
    ratio = (closes[bank_s].mean(axis=1) / closes.mean(axis=1)).dropna()
    if ratio.empty:
        return {"signal": "neutral", "ratio": None}
    ratio_norm = ratio / ratio.iloc[0] if ratio.iloc[0] != 0 else ratio
    trend = _trend_signal(ratio_norm)
    phase = (
        "credit_expansion"
        if trend["signal"] == "rising"
        else "credit_contraction"
        if trend["signal"] == "falling"
        else "neutral"
    )
    return {
        "signal": phase,
        "ratio": round(float(ratio_norm.iloc[-1]), 4),
        "trend_3m_pct": trend["trend_pct"],
    }


def inflation_expectations(closes: pd.DataFrame) -> Dict[str, Any]:
    comm = [s for s in COMMODITY_SECTORS if s in closes.columns]
    cons = [s for s in CONSUMER_SECTORS if s in closes.columns]
    if not comm or not cons:
        return {"signal": "neutral", "ratio": None}
    ratio = (closes[comm].mean(axis=1) / closes[cons].mean(axis=1)).dropna()
    if ratio.empty:
        return {"signal": "neutral", "ratio": None}
    ratio_norm = ratio / ratio.iloc[0] if ratio.iloc[0] != 0 else ratio
    trend = _trend_signal(ratio_norm)
    if trend["trend_pct"] > 5:
        sig = "rising_inflation"
    elif trend["trend_pct"] < -5:
        sig = "falling_inflation"
    else:
        sig = "stable"
    return {
        "signal": sig,
        "ratio": round(float(ratio_norm.iloc[-1]), 4),
        "trend_3m_pct": trend["trend_pct"],
    }


def growth_value_rotation(closes: pd.DataFrame) -> Dict[str, Any]:
    gs = [s for s in GROWTH_SECTORS if s in closes.columns]
    vs = [s for s in VALUE_SECTORS if s in closes.columns]
    if not gs or not vs:
        return {"signal": "neutral", "ratio": None}
    ratio = (closes[gs].mean(axis=1) / closes[vs].mean(axis=1)).dropna()
    if ratio.empty:
        return {"signal": "neutral", "ratio": None}
    ratio_norm = ratio / ratio.iloc[0] if ratio.iloc[0] != 0 else ratio
    trend = _trend_signal(ratio_norm)
    rot = (
        "growth_leading"
        if trend["trend_pct"] > 3
        else "value_leading"
        if trend["trend_pct"] < -3
        else "neutral"
    )
    return {
        "signal": rot,
        "ratio": round(float(ratio_norm.iloc[-1]), 4),
        "trend_3m_pct": trend["trend_pct"],
    }


def market_breadth(closes: pd.DataFrame, ma_period: int = 200) -> Dict[str, Any]:
    above, total = 0, 0
    details: Dict[str, bool] = {}
    for col in closes.columns:
        series = closes[col].dropna()
        if len(series) < ma_period:
            continue
        ma = series.rolling(ma_period).mean()
        if pd.notna(ma.iloc[-1]) and ma.iloc[-1] > 0:
            details[col] = bool(series.iloc[-1] > ma.iloc[-1])
            if details[col]:
                above += 1
            total += 1
    if total == 0:
        # Short history fallback: use shorter MA once
        short = min(50, max(20, closes.shape[0] // 3 or 20))
        if short < ma_period:
            return market_breadth(closes, ma_period=short)
        return {"breadth_pct": 0, "signal": "unknown"}
    pct = (above / total) * 100
    signal = "healthy" if pct >= 70 else "moderate" if pct >= 40 else "narrow"
    return {
        "breadth_pct": round(pct, 1),
        "signal": signal,
        "sectors_above": above,
        "total_sectors": total,
        "details": details,
    }


def sector_momentum(closes: pd.DataFrame, lookback: int = 63) -> Dict[str, Any]:
    momentum: Dict[str, float] = {}
    for col in closes.columns:
        series = closes[col].dropna()
        if len(series) < lookback:
            continue
        momentum[col] = round((series.iloc[-1] / series.iloc[-lookback] - 1) * 100, 2)
    if not momentum:
        return {"leaders": [], "laggards": [], "rotation_type": "unknown", "ranks": {}}
    sorted_mom = sorted(momentum.items(), key=lambda x: x[1], reverse=True)
    leaders = sorted_mom[:5]
    laggards = sorted_mom[-5:]
    top3 = [s[0] for s in sorted_mom[:3]]
    cyc_count = sum(1 for s in top3 if s in CYCLICAL_SECTORS)
    def_count = sum(1 for s in top3 if s in DEFENSIVE_SECTORS)
    rot = "cyclical_led" if cyc_count >= 2 else "defensive_led" if def_count >= 2 else "mixed"
    return {
        "leaders": [{"sector": s, "momentum_pct": m} for s, m in leaders],
        "laggards": [{"sector": s, "momentum_pct": m} for s, m in laggards],
        "rotation_type": rot,
        "ranks": momentum,
    }


def classify_vix(
    vix_value: Optional[float],
    *,
    fear: float = 25.0,
    elevated: float = 20.0,
) -> Dict[str, Any]:
    if vix_value is None or not np.isfinite(vix_value):
        return {"value": None, "signal": "unknown"}
    current = float(vix_value)
    if current > fear:
        sig = "fear"
    elif current > elevated:
        sig = "elevated"
    elif current < 12:
        sig = "complacent"
    else:
        sig = "normal"
    return {"value": round(current, 1), "signal": sig}


def synthesize_phase(
    signals: Mapping[str, Any],
    prev_sub_phase: Optional[str] = None,
) -> Dict[str, Any]:
    cd = signals.get("cyclical_defensive", {}) or {}
    cc = signals.get("credit_cycle", {}) or {}
    mb = signals.get("market_breadth", {}) or {}
    rm = signals.get("sector_momentum", {}) or {}

    score = 0.0
    if cd.get("signal") == "expansion":
        score += 1.0
    elif cd.get("signal") == "contraction":
        score -= 1.0
    if cc.get("signal") == "credit_expansion":
        score += 0.5
    elif cc.get("signal") == "credit_contraction":
        score -= 0.5
    if mb.get("signal") == "healthy":
        score += 0.5
    elif mb.get("signal") == "narrow":
        score -= 0.5
    if rm.get("rotation_type") == "cyclical_led":
        score += 0.5
    elif rm.get("rotation_type") == "defensive_led":
        score -= 0.5

    # Enter/exit deadbands (aligned with Pulse MarketSignals)
    phase_early_enter, phase_early_exit = 1.15, 0.85
    phase_exp_floor = 0.15
    phase_contr_enter, phase_contr_exit = -0.85, -0.15
    prev = (prev_sub_phase or "").strip() or "late_expansion"

    if prev == "contraction":
        if score <= phase_contr_exit:
            phase, sub = "contraction", "contraction"
        elif score >= phase_early_enter:
            phase, sub = "expansion", "early_expansion"
        elif score >= phase_exp_floor:
            phase, sub = "expansion", "late_expansion"
        else:
            phase, sub = "contraction", "contraction"
    elif prev == "early_expansion":
        if score >= phase_early_exit:
            phase, sub = "expansion", "early_expansion"
        elif score <= phase_contr_enter:
            phase, sub = "contraction", "contraction"
        else:
            phase, sub = "expansion", "late_expansion"
    else:
        if score >= phase_early_enter:
            phase, sub = "expansion", "early_expansion"
        elif score <= phase_contr_enter:
            phase, sub = "contraction", "contraction"
        elif score <= phase_contr_exit and score < phase_exp_floor:
            phase, sub = "contraction", "contraction"
        else:
            phase, sub = "expansion", "late_expansion"

    breadth_pct = float(mb.get("breadth_pct") or 50.0)
    trend_3m = float(cd.get("trend_3m_pct") or 0.0)
    if sub == "early_expansion":
        progress = 0.20
        if breadth_pct < 60:
            progress += 0.15
        if trend_3m < 3:
            progress += 0.10
        progress += max(0.0, (2.0 - score) * 0.08)
        progress = min(max(progress, 0.10), 0.45)
    elif sub == "late_expansion":
        progress = 0.55
        if breadth_pct < 50:
            progress += 0.15
        elif breadth_pct > 70:
            progress -= 0.10
        if trend_3m < 0:
            progress += 0.12
        progress += max(0.0, (1.0 - score) * 0.15)
        progress = min(max(progress, 0.45), 0.90)
    else:
        progress = 0.35
        if breadth_pct < 40:
            progress += 0.20
        progress += min(0.35, abs(score) * 0.15)
        if trend_3m > 0:
            progress += 0.10
        progress = min(max(progress, 0.15), 0.95)

    return {
        "phase": phase,
        "sub_phase": sub,
        "score": round(score, 2),
        "progress": round(progress, 2),
        "cyclical_defensive": cd.get("signal"),
        "credit_cycle": cc.get("signal"),
        "breadth": mb.get("signal"),
        "rotation": rm.get("rotation_type"),
        "prev_sub_phase": prev_sub_phase,
    }


def sector_scores(
    closes: pd.DataFrame,
    *,
    sub_phase: str,
    momentum_lookback: int = 63,
) -> Dict[str, float]:
    """0–100 conviction per sector from momentum + sub-phase fit."""
    mom = sector_momentum(closes, lookback=momentum_lookback).get("ranks", {})
    favored = set(SUB_PHASE_SECTORS.get(sub_phase, []))
    scores: Dict[str, float] = {}
    mom_vals = list(mom.values()) if mom else [0.0]
    lo, hi = min(mom_vals), max(mom_vals)
    span = hi - lo if hi != lo else 1.0
    for sector in closes.columns:
        m = float(mom.get(sector, 0.0))
        mom_pts = 25.0 * (m - lo) / span  # 0–25
        fit_pts = 20.0 if sector in favored else 0.0
        # Base 40 so mid-pack sectors aren't zeroed
        scores[sector] = round(min(100.0, 40.0 + mom_pts + fit_pts), 1)
    return scores


def compute_cycle_bias(
    sector_data: Mapping[str, pd.DataFrame],
    *,
    vix_value: Optional[float] = None,
    params: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Full cycle filter output for swing strategy."""
    p = dict(params or {})
    closes = closes_frame(sector_data)
    if closes.empty:
        return {
            "phase": "unknown",
            "sub_phase": "unknown",
            "allowed_sectors": [],
            "sector_scores": {},
            "risk_off": True,
            "signals": {},
            "reason": "no_sector_data",
        }

    signals: Dict[str, Any] = {
        "cyclical_defensive": cyclical_defensive_ratio(closes),
        "credit_cycle": credit_cycle(closes),
        "inflation_expectations": inflation_expectations(closes),
        "growth_value": growth_value_rotation(closes),
        "market_breadth": market_breadth(closes, ma_period=int(p.get("breadth_ma", 200))),
        "sector_momentum": sector_momentum(
            closes, lookback=int(p.get("momentum_lookback", 63))
        ),
        "india_vix": classify_vix(
            vix_value,
            fear=float(p.get("vix_fear_threshold", 25)),
            elevated=float(p.get("vix_elevated_threshold", 20)),
        ),
    }
    phase_info = synthesize_phase(signals)
    scores = sector_scores(
        closes,
        sub_phase=phase_info["sub_phase"],
        momentum_lookback=int(p.get("momentum_lookback", 63)),
    )

    vix_sig = signals["india_vix"].get("signal")
    breadth_pct = float(signals["market_breadth"].get("breadth_pct") or 0)
    min_breadth = float(p.get("min_breadth_for_new_risk", 35))
    risk_off = vix_sig == "fear" or (
        phase_info["phase"] == "contraction" and breadth_pct < min_breadth
    )

    recommend = float(p.get("recommend_score", 55))
    allow_def = bool(p.get("allow_contraction_defensives", True))
    favored = list(SUB_PHASE_SECTORS.get(phase_info["sub_phase"], []))

    allowed: List[str] = []
    if not risk_off:
        for sector, score in sorted(scores.items(), key=lambda x: -x[1]):
            if score < recommend:
                continue
            if phase_info["phase"] == "contraction" and allow_def:
                if sector not in DEFENSIVE_SECTORS and sector not in favored:
                    continue
            elif favored and sector not in favored and score < recommend + 10:
                # Require extra conviction outside favored list
                continue
            allowed.append(sector)

    return {
        **phase_info,
        "allowed_sectors": allowed,
        "sector_scores": scores,
        "favored_sectors": favored,
        "risk_off": risk_off,
        "signals": signals,
        "reason": "fear_vix" if vix_sig == "fear" else ("ok" if allowed else "no_setups"),
    }
