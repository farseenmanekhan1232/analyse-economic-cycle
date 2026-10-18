"""Sticky recommend eligibility — shared by pipeline and Decision OS diff.

Enter/exit bands + consecutive-run confirmation so absolute score ranking
does not flip the book every run.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.decision.thresholds import (
    EXIT_SCORE,
    HYSTERESIS_POINTS,
    RECOMMEND_CONSECUTIVE,
    RECOMMEND_ENTER,
    RECOMMEND_SCORE,
    is_buy_like_rating,
)


def is_sticky_recommended(
    score: float,
    *,
    rating: str = "",
    prev_scores: Optional[Sequence[Optional[float]]] = None,
    was_recommended: Optional[bool] = None,
) -> bool:
    """Decide recommend with enter/exit hysteresis and consecutive confirmation.

    Rules (newest score first in prev_scores = [prev, prev2, ...]):
    - If already recommended last run: stay on until score < EXIT_SCORE
      (unless rating is explicitly sell-like — handled by callers for holdings).
    - If not previously recommended: enter when score >= RECOMMEND_ENTER, OR
      score >= RECOMMEND_SCORE for RECOMMEND_CONSECUTIVE consecutive runs
      (current + prior runs), OR buy-like rating with score >= EXIT_SCORE.
    - First run / no history: enter only at RECOMMEND_ENTER (or buy-like + near band).
    """
    rating_ok = is_buy_like_rating(rating)
    prev = list(prev_scores or [])
    prev_score = prev[0] if prev else None

    if was_recommended is None and prev_score is not None:
        # Infer prior recommend from score band (exit band = sticky floor)
        was_recommended = prev_score >= EXIT_SCORE and (
            prev_score >= RECOMMEND_SCORE - HYSTERESIS_POINTS or rating_ok
        )

    if was_recommended:
        return score >= EXIT_SCORE or rating_ok

    # New entry
    if score >= RECOMMEND_ENTER:
        return True
    if rating_ok and score >= EXIT_SCORE:
        return True

    # Consecutive confirmation at/above RECOMMEND_SCORE
    need = RECOMMEND_CONSECUTIVE
    if score < RECOMMEND_SCORE:
        return False
    streak = 1  # current
    for p in prev:
        if p is None or p < RECOMMEND_SCORE:
            break
        streak += 1
        if streak >= need:
            return True
    return streak >= need


def prev_scores_for_sector(
    history: Sequence[Dict[str, Any]],
    sector_key: str,
    *,
    limit: int = 3,
) -> Tuple[List[Optional[float]], Optional[bool]]:
    """Extract recent scores + last recommended flag from run history rows.

    history: newest-first list of {sector -> {score, recommended}} or
    list of summary-like dicts keyed by sector string.
    """
    scores: List[Optional[float]] = []
    was_rec: Optional[bool] = None
    for i, run_map in enumerate(history[:limit]):
        row = run_map.get(sector_key) if isinstance(run_map, dict) else None
        if row is None:
            # try normalized / upper
            for k, v in (run_map or {}).items():
                if str(k).upper() == str(sector_key).upper():
                    row = v
                    break
        if not isinstance(row, dict):
            scores.append(None)
            continue
        sc = row.get("score")
        scores.append(float(sc) if sc is not None else None)
        if i == 0 and "recommended" in row:
            was_rec = bool(row.get("recommended"))
    return scores, was_rec


def build_sector_history_maps(
    runs_payload: Iterable[Any],
) -> List[Dict[str, Dict[str, Any]]]:
    """Build newest-first sector→{score, recommended} maps from AnalysisRun-like objs."""
    import json

    maps: List[Dict[str, Dict[str, Any]]] = []
    for run in runs_payload:
        by_sector: Dict[str, Dict[str, Any]] = {}
        # Prefer ORM sectors
        sectors = getattr(run, "sectors", None) or []
        payload: Dict[str, Any] = {}
        raw = getattr(run, "payload_json", None) or "{}"
        try:
            payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (json.JSONDecodeError, TypeError):
            payload = {}
        summary_by = {
            str(r.get("sector") or ""): r
            for r in (payload.get("summary") or [])
            if isinstance(r, dict)
        }
        if sectors:
            for s in sectors:
                key = getattr(s, "sector_id", None) or getattr(s, "sector", None) or ""
                key = str(key)
                extra = summary_by.get(getattr(s, "sector", "") or "") or summary_by.get(key) or {}
                by_sector[key] = {
                    "score": float(getattr(s, "score", 0) or 0),
                    "recommended": bool(extra["recommended"])
                    if "recommended" in extra
                    else (
                        is_buy_like_rating(getattr(s, "rating", "") or "")
                        or float(getattr(s, "score", 0) or 0) >= RECOMMEND_SCORE
                    ),
                    "rating": getattr(s, "rating", "") or extra.get("rating") or "",
                }
                # also index by raw sector name
                raw_name = str(getattr(s, "sector", "") or "")
                if raw_name and raw_name != key:
                    by_sector[raw_name] = by_sector[key]
        else:
            for row in summary_by.values():
                key = str(row.get("sector") or "")
                if not key:
                    continue
                by_sector[key] = {
                    "score": float(row.get("score") or 0),
                    "recommended": bool(row.get("recommended", False)),
                    "rating": row.get("rating") or "",
                }
        maps.append(by_sector)
    return maps
