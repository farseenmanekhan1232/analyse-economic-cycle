"""Named Decision OS / pipeline thresholds — single place for score bands."""

from __future__ import annotations

# Decision OS buy-gap / recommend eligibility
RECOMMEND_SCORE = 60.0

# Enter requires clear clearance above the band (or consecutive confirmation)
RECOMMEND_ENTER = 63.0

# Stay recommended until score falls below this exit floor
EXIT_SCORE = 55.0

# Consecutive runs at/above RECOMMEND_SCORE to enter without RECOMMEND_ENTER
RECOMMEND_CONSECUTIVE = 2

# Pipeline may still scrape a slightly softer list for fund LTP enrichment only
SCRAPE_MIN = 55.0

# propose_action bands
WEAK_SELL = 50.0
# Sell only when score clears below WEAK_SELL by this margin (or was already weak)
SELL_HYSTERESIS = 3.0
EXITISH = 55.0
EXTEND_IF_BELOW = 65.0
KEEP_STRONG = 60.0

# Rating labels (pipeline)
RATING_TOP_PICK = 70.0
RATING_BUY = 60.0
RATING_HOLD = 50.0

# Hysteresis points around recommend band (legacy alias for enter gap)
HYSTERESIS_POINTS = 3.0

# Cycle phase vote deadband — avoid early↔late flip on tiny vote noise
PHASE_EARLY_ENTER = 1.15
PHASE_EARLY_EXIT = 0.85
PHASE_EXPANSION_FLOOR = 0.15
PHASE_CONTRACTION_ENTER = -0.85
PHASE_CONTRACTION_EXIT = -0.15

# Plan staleness: implied hold_until differs from stored by more than this
PLAN_STALE_DAYS = 45

# Concentration: flag buy ideas when sector already heavy
CONCENTRATION_MAX_WEIGHT = 0.25
CONCENTRATION_MAX_NAMES = 2

# Sync freshness (days)
MF_STALE_DAYS = 7
STOCKS_STALE_DAYS = 3

# Calibration lookback
CALIBRATION_MIN_AGE_DAYS = 30
CALIBRATION_WINDOWS = (30, 90)


def rating_for_score(score: float) -> str:
    if score >= RATING_TOP_PICK:
        return "Top Pick"
    if score >= RATING_BUY:
        return "Buy"
    if score >= RATING_HOLD:
        return "Hold"
    return "Wait"


def is_buy_like_rating(rating: str) -> bool:
    return (rating or "").lower() in ("buy", "strong buy", "overweight", "top pick")


def is_sell_like_rating(rating: str) -> bool:
    return (rating or "").lower() in ("sell", "avoid", "underweight")
