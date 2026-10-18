"""Thin calibration: past Buy/Top Pick sector calls vs realized index returns.

Uses cached pipeline sector history when available; otherwise returns empty calls
with an honest caveat. Does not claim portfolio alpha.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.decision.runs import list_runs
from backend.decision.sectors import kite_index_for, resolve_sector_id
from backend.decision.thresholds import (
    CALIBRATION_MIN_AGE_DAYS,
    CALIBRATION_WINDOWS,
    RECOMMEND_SCORE,
    is_buy_like_rating,
)

logger = logging.getLogger(__name__)

CAVEAT = (
    "Track record uses sector indices (not your PnL). India business-cycle samples "
    "are small — treat hit-rates as orientation, not precision."
)


def _close_series_from_cache() -> Dict[str, Any]:
    """sector_id → DataFrame-like close series from pipeline cache if present."""
    try:
        from backend.data.cache_manager import CacheManager

        results = CacheManager().get("pipeline_results") or {}
        # Prefer embedded history if pipeline stored it
        hist = results.get("sector_history") or results.get("_sector_closes") or {}
        if hist:
            return hist
    except Exception as exc:
        logger.debug("No sector history in cache: %s", exc)
    return {}


def _return_from_series(
    closes: List[float], dates: List[str], from_day: date, to_day: Optional[date] = None
) -> Optional[float]:
    if not closes or not dates or len(closes) != len(dates):
        return None
    to_day = to_day or date.today()
    start_idx = None
    end_idx = None
    for i, d in enumerate(dates):
        try:
            dd = date.fromisoformat(str(d)[:10])
        except ValueError:
            continue
        if start_idx is None and dd >= from_day:
            start_idx = i
        if dd <= to_day:
            end_idx = i
    if start_idx is None or end_idx is None or end_idx <= start_idx:
        return None
    a, b = float(closes[start_idx]), float(closes[end_idx])
    if a <= 0:
        return None
    return (b / a - 1.0) * 100.0


def _try_kite_return(sector_id: str, from_day: date, to_day: date) -> Optional[float]:
    """Best-effort live fetch; skip if Kite unavailable."""
    try:
        from backend.data.kite_client import KiteClient

        kite_name = kite_index_for(sector_id)
        if not kite_name:
            return None
        kite = KiteClient()
        if not getattr(kite, "kite", None):
            return None
        token = kite.get_instrument_token("NSE", kite_name)
        if not token:
            return None
        df = kite.fetch_historical(token, from_day.isoformat(), to_day.isoformat(), interval="day")
        if df is None or getattr(df, "empty", True):
            return None
        col = "close" if "close" in df.columns else df.columns[-1]
        a = float(df[col].iloc[0])
        b = float(df[col].iloc[-1])
        if a <= 0:
            return None
        return (b / a - 1.0) * 100.0
    except Exception as exc:
        logger.debug("Kite calibration fetch failed for %s: %s", sector_id, exc)
        return None


def build_calibration(db: Session) -> Dict[str, Any]:
    runs = list_runs(db, limit=40)
    today = date.today()
    cache = _close_series_from_cache()
    calls: List[Dict[str, Any]] = []

    for run in runs:
        if not run.ran_at:
            continue
        ran = run.ran_at.date() if isinstance(run.ran_at, datetime) else run.ran_at
        age = (today - ran).days
        if age < CALIBRATION_MIN_AGE_DAYS:
            continue
        for s in run.sectors:
            rating = s.rating or ""
            if s.score < RECOMMEND_SCORE and not is_buy_like_rating(rating):
                continue
            sid, _ = resolve_sector_id(s.sector_id or s.sector or "")
            if not sid:
                continue
            # Prefer hold window end, else 90d
            hi_days = int(round((s.hold_months_hi or 3) * 30))
            window_end = min(today, ran + timedelta(days=hi_days))
            ret = None
            series = cache.get(sid) or cache.get(s.sector)
            if isinstance(series, dict):
                ret = _return_from_series(
                    series.get("closes") or series.get("close") or [],
                    series.get("dates") or [],
                    ran,
                    window_end,
                )
            if ret is None:
                ret = _try_kite_return(sid, ran, window_end)
            if ret is None:
                continue
            calls.append(
                {
                    "run_id": run.id,
                    "ran_at": ran.isoformat(),
                    "sector": sid,
                    "score": s.score,
                    "rating": rating,
                    "return_pct": round(ret, 2),
                    "window_days": (window_end - ran).days,
                    "hit": ret > 0,
                }
            )

    # Deduplicate: keep one call per (run, sector)
    seen = set()
    uniq = []
    for c in calls:
        key = (c["run_id"], c["sector"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)

    hits = sum(1 for c in uniq if c["hit"])
    n = len(uniq)
    by_band: Dict[str, Dict[str, Any]] = {}
    for c in uniq:
        band = "top_pick" if c["score"] >= 70 else "buy"
        b = by_band.setdefault(band, {"n": 0, "hits": 0, "avg_return": 0.0, "_sum": 0.0})
        b["n"] += 1
        b["hits"] += 1 if c["hit"] else 0
        b["_sum"] += c["return_pct"]
    for b in by_band.values():
        b["avg_return"] = round(b["_sum"] / b["n"], 2) if b["n"] else 0.0
        b["hit_rate"] = round(b["hits"] / b["n"], 2) if b["n"] else None
        del b["_sum"]

    # Window aggregates for UI
    window_stats = {}
    for w in CALIBRATION_WINDOWS:
        subset = [c for c in uniq if c["window_days"] >= min(w, CALIBRATION_MIN_AGE_DAYS)]
        # Also include calls whose age since run >= w
        aged = []
        for c in uniq:
            try:
                ran = date.fromisoformat(c["ran_at"])
            except ValueError:
                continue
            if (today - ran).days >= w:
                aged.append(c)
        subset = aged
        wn = len(subset)
        window_stats[str(w)] = {
            "n": wn,
            "hit_rate": round(sum(1 for c in subset if c["hit"]) / wn, 2) if wn else None,
            "avg_return": round(sum(c["return_pct"] for c in subset) / wn, 2) if wn else None,
        }

    recent = sorted(uniq, key=lambda c: c["ran_at"], reverse=True)[:8]

    return {
        "caveat": CAVEAT,
        "n_calls": n,
        "hit_rate": round(hits / n, 2) if n else None,
        "avg_return": round(sum(c["return_pct"] for c in uniq) / n, 2) if n else None,
        "by_band": by_band,
        "windows": window_stats,
        "recent_calls": recent,
        "data_available": n > 0,
    }
