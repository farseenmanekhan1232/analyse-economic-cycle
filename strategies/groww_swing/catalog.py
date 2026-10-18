"""Named swing approach registry — IDs used in params, scan, backtest, orders."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional

# Approach ID → human label (Groww Cloud / UI)
APPROACH_META: Dict[str, Dict[str, str]] = {
    "trend_pullback": {
        "label": "Trend pullback",
        "summary": "EMA20 pullback + RSI reclaim in uptrend",
    },
    "trend_breakout": {
        "label": "Trend breakout",
        "summary": "Close above prior N-day high with volume",
    },
    "rs_momentum": {
        "label": "RS momentum",
        "summary": "Top relative-strength ETFs vs Nifty in uptrend",
    },
    "defensive_mean_reversion": {
        "label": "Defensive mean reversion",
        "summary": "Oversold bounce in defensive sectors only",
    },
    "vol_compression_break": {
        "label": "Vol compression break",
        "summary": "BB/ATR squeeze then break in trend direction",
    },
}

ALL_APPROACH_IDS: List[str] = list(APPROACH_META.keys())

# Prefer breakout / pullback before softer approaches when multiple fire
APPROACH_PRIORITY: List[str] = [
    "trend_breakout",
    "trend_pullback",
    "rs_momentum",
    "vol_compression_break",
    "defensive_mean_reversion",
]

# Legacy setup names from older params / logs
LEGACY_SETUP_ALIASES: Dict[str, str] = {
    "pullback": "trend_pullback",
    "breakout": "trend_breakout",
}


def normalize_approach_id(raw: str) -> str:
    s = str(raw or "").strip()
    return LEGACY_SETUP_ALIASES.get(s, s)


def resolve_enabled(params: Mapping[str, Any]) -> List[str]:
    """Approaches enabled in params.json (intersection with known IDs)."""
    raw = params.get("enabled_approaches")
    if not raw:
        return list(ALL_APPROACH_IDS)
    out: List[str] = []
    for item in raw:
        aid = normalize_approach_id(str(item))
        if aid in APPROACH_META and aid not in out:
            out.append(aid)
    return out or list(ALL_APPROACH_IDS)


def prioritize(approach_ids: List[str]) -> List[str]:
    rank = {a: i for i, a in enumerate(APPROACH_PRIORITY)}
    return sorted(approach_ids, key=lambda a: rank.get(a, 99))


DetectorFn = Callable[..., Optional[Dict[str, Any]]]


def get_detectors() -> Dict[str, DetectorFn]:
    """Late import to avoid circular imports with setups."""
    from . import setups as S

    return {
        "trend_pullback": S.detect_trend_pullback,
        "trend_breakout": S.detect_trend_breakout,
        "rs_momentum": S.detect_rs_momentum,
        "defensive_mean_reversion": S.detect_defensive_mean_reversion,
        "vol_compression_break": S.detect_vol_compression_break,
    }
