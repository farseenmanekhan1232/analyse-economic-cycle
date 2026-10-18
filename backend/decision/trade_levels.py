"""Per-holding stop / target / square-off call from entry vs current price.

Hold-month windows stay cycle context only. Day-to-day act-or-not uses levels.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from backend.decision.helpers import format_display_date
from backend.decision.models import Holding, SectorScore
from backend.decision.thresholds import MF_STALE_DAYS, STOCKS_STALE_DAYS, WEAK_SELL

logger = logging.getLogger(__name__)

STOP_PCT_FLOOR = 8.0
STOP_PCT_CAP = 20.0
TARGET_R_MULT = 1.5
NEAR_TARGET_FRAC = 0.15  # within 15% of the way from entry to target distance remaining
THIN_CUSHION_PCT = 5.0
THIN_R_LEFT = 0.5


def _entry_price(h: Holding) -> Optional[float]:
    if h.avg_cost and h.avg_cost > 0:
        return float(h.avg_cost)
    if h.units and h.units > 0 and h.invested_amount and h.invested_amount > 0:
        return float(h.invested_amount) / float(h.units)
    return None


def _stop_pct(sector_stop: Optional[float]) -> float:
    raw = float(sector_stop) if sector_stop and sector_stop > 0 else STOP_PCT_FLOOR
    return min(STOP_PCT_CAP, max(STOP_PCT_FLOOR, raw))


def _target_pct(stop_pct: float, score: Optional[float], rating: str) -> float:
    base = stop_pct * TARGET_R_MULT
    s = float(score) if score is not None else 55.0
    r = (rating or "").lower()
    if s >= 70 or r in ("top pick", "strong buy"):
        return base * 1.15
    if s >= 60 or r in ("buy", "overweight"):
        return base
    if s < WEAK_SELL or r in ("sell", "avoid", "underweight"):
        return base * 0.5
    if s < 55:
        return base * 0.75
    return base


def _time_used_pct(h: Holding) -> Optional[float]:
    if not h.hold_until:
        return None
    end = h.hold_until
    start = None
    if h.created_at:
        start = h.created_at.date() if isinstance(h.created_at, datetime) else h.created_at
    if start is None:
        # assume ~ hold window length ending at hold_until (9 mo default span)
        return None
    total = (end - start).days
    if total <= 0:
        return 100.0 if date.today() >= end else 0.0
    used = (date.today() - start).days
    return round(min(100.0, max(0.0, used / total * 100.0)), 1)


def levels_for_holding(
    h: Holding,
    score: Optional[SectorScore] = None,
    *,
    quote: Optional[float] = None,
    price_as_of: Optional[datetime] = None,
    price_stale: bool = False,
) -> Dict[str, Any]:
    """
    Build a trade card: entry / current / stop / target + Hold|Tighten|Exit|Review.
    """
    entry = _entry_price(h)
    current = float(quote) if quote and quote > 0 else None
    if current is None and h.last_price and h.last_price > 0:
        current = float(h.last_price)

    sector_stop = score.stop_loss_pct if score else None
    stop_pct = _stop_pct(sector_stop)
    target_pct = _target_pct(
        stop_pct,
        score.score if score else None,
        score.rating if score else "",
    )

    stop_price = round(entry * (1 - stop_pct / 100.0), 4) if entry else None
    target_price = round(entry * (1 + target_pct / 100.0), 4) if entry else None

    pnl_pct = None
    if entry and current and entry > 0:
        pnl_pct = round((current / entry - 1.0) * 100.0, 2)

    cushion_pct = None
    if current is not None and stop_price and stop_price > 0:
        cushion_pct = round((current / stop_price - 1.0) * 100.0, 2)

    r_remaining = None
    if current is not None and stop_price is not None and target_price is not None:
        risk = current - stop_price
        reward = target_price - current
        if risk > 1e-9:
            r_remaining = round(reward / risk, 2)
        elif reward <= 0:
            r_remaining = 0.0

    time_used = _time_used_pct(h)
    overdue = bool(h.hold_until and h.hold_until < date.today())
    rating = (score.rating or "").lower() if score else ""
    from backend.decision.thresholds import SELL_HYSTERESIS

    weak_thesis = bool(
        score
        and (
            score.score < WEAK_SELL - SELL_HYSTERESIS
            or rating in ("sell", "avoid", "underweight")
        )
    )

    # Missing inputs → review
    if entry is None or current is None:
        action = "review"
        label = "Need entry or current price"
        rationale = (
            "Cannot judge square-off without an entry (avg cost) and a current price. "
            "Sync from Groww, then refresh Analyse."
        )
    elif price_stale:
        action = "review"
        label = "Price may be stale — refresh Sync"
        rationale = (
            f"Last known price ₹{current:,.2f} may be outdated. "
            "Re-sync stocks/ETFs (or MF XLSX) before trusting Exit/Hold."
        )
    elif current <= (stop_price or 0) or (cushion_pct is not None and cushion_pct <= 0):
        action = "exit"
        label = "At or below stop — exit"
        rationale = (
            f"Current ₹{current:,.2f} is at/under stop ₹{stop_price:,.2f} "
            f"(-{stop_pct:.0f}% from entry ₹{entry:,.2f}). Thesis invalidated on price — sell on Groww."
        )
    elif weak_thesis:
        action = "exit"
        label = "Thesis weak — consider exit"
        rationale = (
            f"{(score.sector if score else 'Sector').replace('_', ' ')} score "
            f"{score.score:.0f} ({score.rating or 'weak'}). "
            f"Current ₹{current:,.2f} vs stop ₹{stop_price:,.2f} / target ₹{target_price:,.2f}."
        )
    else:
        # Near target?
        near_target = False
        if entry and target_price and current and target_price > entry:
            span = target_price - entry
            progress = (current - entry) / span
            near_target = progress >= (1.0 - NEAR_TARGET_FRAC)

        thin = (r_remaining is not None and r_remaining < THIN_R_LEFT) and (
            cushion_pct is not None and cushion_pct < THIN_CUSHION_PCT * 2
        )

        if near_target or thin:
            action = "tighten"
            label = "Near target — tighten or take profit"
            rationale = (
                f"Current ₹{current:,.2f} is close to target ₹{target_price:,.2f} "
                f"(entry ₹{entry:,.2f}, stop ₹{stop_price:,.2f})"
                + (f"; ~{r_remaining:.1f}R left" if r_remaining is not None else "")
                + ". Consider booking partial/full profits; do not let it fall through the stop."
            )
        elif overdue:
            # Calendar review only — do not force exit from levels
            action = "hold"
            label = "Hold — review date passed (levels OK)"
            bits = []
            if pnl_pct is not None:
                bits.append(f"PnL {pnl_pct:+.1f}%")
            if cushion_pct is not None:
                bits.append(f"{cushion_pct:.0f}% above stop")
            rationale = (
                f"Hold-until {format_display_date(h.hold_until)} has passed, but price levels "
                f"still work (entry ₹{entry:,.2f} · now ₹{current:,.2f} · stop ₹{stop_price:,.2f}). "
                + ("; ".join(bits) + ". " if bits else "")
                + "Update the review date in Analyse — do not sell solely because the calendar expired."
            )
        else:
            action = "hold"
            label = "Hold — levels still work"
            bits = []
            if cushion_pct is not None:
                bits.append(f"{cushion_pct:.0f}% above stop")
            if r_remaining is not None:
                bits.append(f"~{r_remaining:.1f}R left to target")
            if time_used is not None:
                bits.append(f"{time_used:.0f}% of review window used")
            rationale = (
                f"Entry ₹{entry:,.2f} · now ₹{current:,.2f} · stop ₹{stop_price:,.2f} · "
                f"target ₹{target_price:,.2f}. "
                + ("; ".join(bits) + ". " if bits else "")
                + "Month windows are only a review deadline — act on these levels."
            )

    return {
        "entry": round(entry, 4) if entry else None,
        "current": round(current, 4) if current else None,
        "stop_price": stop_price,
        "target_price": target_price,
        "stop_pct": round(stop_pct, 1),
        "target_pct": round(target_pct, 1),
        "pnl_pct": pnl_pct,
        "cushion_pct": cushion_pct,
        "r_remaining": r_remaining,
        "time_used_pct": time_used,
        "price_stale": price_stale,
        "price_as_of": price_as_of.isoformat() if price_as_of else None,
        "action": action,
        "label": label,
        "rationale": rationale,
        "hold_for_context": (
            f"{score.hold_months_lo:.0f}–{score.hold_months_hi:.0f} months typical dwell"
            if score
            else None
        ),
    }


def fetch_equity_quotes(holdings: List[Holding]) -> Dict[str, float]:
    """Map holding.id → LTP for etf/stock via Kite when connected. Empty on failure."""
    from sqlalchemy.orm import object_session

    from backend.decision.models import Instrument

    symbols: Dict[str, str] = {}  # holding_id -> NSE:SYMBOL
    for h in holdings:
        if h.asset_class not in ("etf", "stock"):
            continue
        sym = None
        sess = object_session(h)
        if h.instrument_id and sess is not None:
            inst = sess.get(Instrument, h.instrument_id)
            if inst and inst.nse_symbol:
                sym = inst.nse_symbol.upper()
        if not sym:
            raw = (h.scheme_code or h.external_key or "").strip().upper()
            if raw and not raw.startswith("INF") and raw.isalnum() and len(raw) <= 20:
                sym = raw
            else:
                name = (h.instrument or "").upper()
                for token in reversed(name.replace("-", " ").split()):
                    if token.isalnum() and 2 <= len(token) <= 15 and not token.startswith("INF"):
                        sym = token
                        break
        if not sym:
            continue
        symbols[h.id] = f"NSE:{sym}"

    if not symbols:
        return {}

    try:
        from backend.data.cache_manager import CacheManager
        from backend.data.kite_client import KiteClient

        token_data = CacheManager().get("kite_access_token") or {}
        token = token_data.get("access_token")
        if not token:
            return {}
        kite = KiteClient(access_token=token)
        keys = list(set(symbols.values()))
        quotes = kite.get_quote(keys) or {}
        out: Dict[str, float] = {}
        for hid, key in symbols.items():
            q = quotes.get(key) or {}
            ltp = q.get("last_price")
            if ltp and float(ltp) > 0:
                out[hid] = float(ltp)
        if out:
            logger.info("Refreshed LTP for %s equity holdings", len(out))
        return out
    except Exception as exc:
        logger.debug("ETF quote refresh skipped: %s", exc)
        return {}


def price_stale_for(h: Holding, last_sync: Optional[datetime]) -> bool:
    """True when we should not trust last_price for a firm Exit/Hold call."""
    if h.asset_class == "mf":
        limit = MF_STALE_DAYS
    else:
        limit = STOCKS_STALE_DAYS
    if last_sync is None:
        return True
    age = (datetime.now() - last_sync).total_seconds() / 86400.0
    return age > limit
