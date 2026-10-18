"""Diff open holdings against latest analysis run → actions + instrument set-diff buys."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from backend.decision.helpers import format_display_date, hold_until_from_months, normalize_sector
from backend.decision.holdings import holding_to_dict, list_holdings
from backend.decision.instruments import catalog_for_sectors
from backend.decision.models import AnalysisRun, Holding, SectorScore
from backend.decision.runs import get_latest_run, list_runs, run_to_dict
from backend.decision.sectors import equivalent_ids, resolve_sector_id
from backend.decision.thresholds import (
    CONCENTRATION_MAX_NAMES,
    CONCENTRATION_MAX_WEIGHT,
    EXIT_SCORE,
    EXITISH,
    EXTEND_IF_BELOW,
    KEEP_STRONG,
    MF_STALE_DAYS,
    PLAN_STALE_DAYS,
    SELL_HYSTERESIS,
    STOCKS_STALE_DAYS,
    WEAK_SELL,
    is_sell_like_rating,
)
from backend.decision.recommend import is_sticky_recommended, prev_scores_for_sector, build_sector_history_maps


def _holding_sector_id(h: Holding) -> Tuple[Optional[str], str]:
    if h.sector_id:
        return h.sector_id, "exact"
    return resolve_sector_id(h.sector or "")


def _score_sector_id(s: SectorScore) -> Optional[str]:
    if s.sector_id:
        return s.sector_id
    sid, _ = resolve_sector_id(s.sector or "")
    return sid


def _score_for_holding(
    run: AnalysisRun, holding: Holding
) -> Tuple[Optional[SectorScore], Dict[str, Any]]:
    """Exact sector_id join (with PHARMA↔HEALTHCARE equivalents)."""
    holding_sid, conf = _holding_sector_id(holding)
    debug = {
        "holding_sector_id": holding_sid,
        "matched_score_sector_id": None,
        "matched_score": None,
        "match_confidence": "none" if not holding_sid else conf,
    }
    if not holding_sid:
        return None, debug

    wanted = equivalent_ids(holding_sid)
    best = None
    for s in run.sectors:
        sid = _score_sector_id(s)
        if sid and sid in wanted:
            if best is None or s.score > best.score:
                best = s
    if best:
        matched_id = _score_sector_id(best)
        debug["matched_score_sector_id"] = matched_id
        debug["matched_score"] = best.score
        debug["match_confidence"] = "exact" if matched_id == holding_sid else "alias"
        return best, debug
    return None, debug


def _prev_run_scores(db: Session, sector_id: Optional[str]) -> tuple:
    """Return (prev_scores newest-first, was_recommended)."""
    if not sector_id:
        return [], None
    runs = list_runs(db, limit=4)
    if not runs:
        return [], None
    maps = build_sector_history_maps(runs)
    wanted = equivalent_ids(sector_id)
    # Merge equivalent keys into each map
    merged = []
    for m in maps:
        row = None
        for w in wanted:
            if w in m:
                row = m[w]
                break
        merged.append({sector_id: row} if row else {})
    return prev_scores_for_sector(merged, sector_id, limit=3)


def _prev_run_score(db: Session, sector_id: Optional[str]) -> Optional[float]:
    scores, _ = _prev_run_scores(db, sector_id)
    return scores[0] if scores else None


def _is_recommended(
    score: SectorScore,
    prev_score: Optional[float] = None,
    *,
    prev_scores: Optional[List[Optional[float]]] = None,
    was_recommended: Optional[bool] = None,
    force_sticky: bool = False,
) -> bool:
    """Recommend with enter/exit hysteresis + consecutive confirmation.

    force_sticky: held sector still above EXIT_SCORE stays recommendable
    so the book is preferred over a fresh absolute top-N.
    """
    scores = list(prev_scores or [])
    if not scores and prev_score is not None:
        scores = [prev_score]
    if force_sticky and score.score >= EXIT_SCORE:
        return True
    return is_sticky_recommended(
        float(score.score),
        rating=score.rating or "",
        prev_scores=scores,
        was_recommended=was_recommended,
    )


def _plan_stale(
    holding: Holding, score: Optional[SectorScore], match: Dict[str, Any]
) -> bool:
    if score is None:
        return False
    implied = hold_until_from_months(score.hold_months_hi)
    if holding.hold_until:
        delta = abs((implied - holding.hold_until).days)
        if delta > PLAN_STALE_DAYS:
            return True
    # Remapped sector vs what was last reviewed (string sector drifted)
    holding_sid = match.get("holding_sector_id")
    if holding_sid and holding.sector and normalize_sector(holding.sector) != holding_sid:
        return True
    return False


def propose_action(
    holding_sector: str,
    score: Optional[SectorScore],
    hold_until: Optional[date],
    *,
    match_confidence: str = "exact",
    plan_stale: bool = False,
    trade_levels: Optional[Dict[str, Any]] = None,
    prev_score: Optional[float] = None,
) -> Dict[str, Any]:
    today = date.today()
    overdue = bool(hold_until and hold_until < today)
    levels = trade_levels or {}
    levels_action = levels.get("action")

    if score is None or match_confidence == "none":
        return {
            "suggested": "review",
            "label": "Sector not linked to this analysis",
            "rationale": (
                "Pulse could not match this holding to a scored sector, so Keep/Sell "
                "advice is unreliable. Open Holdings, set the correct sector (e.g. REALTY, PHARMA), "
                "then refresh Analyse."
            ),
            "proposed_hold_until": hold_until.isoformat() if hold_until else None,
        }

    # Price levels drive square-off (primary over month windows)
    if levels_action == "exit":
        return {
            "suggested": "sell",
            "label": levels.get("label") or "Exit on levels",
            "rationale": levels.get("rationale")
            or "Current price hit stop or thesis broke — sell on Groww.",
            "proposed_hold_until": None,
        }

    # Overdue hold-until is a *review* deadline, not an automatic sell.
    # Only escalate to sell when levels already say exit (handled above)
    # or thesis is clearly broken (weak score with hysteresis).
    if overdue:
        new_until = hold_until_from_months(score.hold_months_hi)
        weak_now = _thesis_broken(score, prev_score)
        if weak_now:
            return {
                "suggested": "sell",
                "label": "Review date passed and thesis weakened",
                "rationale": (
                    f"You planned to review by {format_display_date(hold_until)}. "
                    f"{score.sector.replace('_', ' ')} now scores {score.score:.0f} "
                    f"({score.rating or 'weak'}) — below the exit band. "
                    "Confirm Sell on Groww, or Keep if you disagree."
                ),
                "proposed_hold_until": None,
            }
        return {
            "suggested": "extend",
            "label": "Hold date passed — set a new review date",
            "rationale": (
                f"You planned to review by {format_display_date(hold_until)}. "
                f"Thesis is still intact (score {score.score:.0f}). "
                f"Hold-until is a review deadline, not an automatic sell. "
                f"This run suggests ~{score.hold_months_lo:.0f}–{score.hold_months_hi:.0f} months "
                f"(until {format_display_date(new_until)})."
                + (f" Levels: {levels.get('label')}." if levels.get("label") else "")
            ),
            "proposed_hold_until": new_until.isoformat() if new_until else None,
        }

    if levels_action == "tighten":
        new_until = hold_until_from_months(score.hold_months_hi) if score else hold_until
        return {
            "suggested": "extend",
            "label": levels.get("label") or "Near target — take profit",
            "rationale": (
                (levels.get("rationale") or "")
                + (
                    f" Optional: tighten review date to {format_display_date(new_until)}."
                    if new_until
                    else ""
                )
            ).strip(),
            "proposed_hold_until": new_until.isoformat()
            if isinstance(new_until, date)
            else (new_until if new_until else None),
        }

    if plan_stale and levels_action != "exit":
        new_until = hold_until_from_months(score.hold_months_hi)
        return {
            "suggested": "extend",
            "label": "Saved hold date is out of date",
            "rationale": (
                f"Your book still says hold until {format_display_date(hold_until)}. "
                f"Levels say: {levels.get('label') or 'hold'}. "
                f"This analysis rates {score.sector.replace('_', ' ')} at {score.score:.0f} "
                f"and uses ~{score.hold_months_lo:.0f}–{score.hold_months_hi:.0f} months only as a "
                f"review deadline (until {format_display_date(new_until)}). "
                "Confirm the new date, keep your old one, or sell."
            ),
            "proposed_hold_until": new_until.isoformat(),
        }

    if _thesis_broken(score, prev_score):
        exit_bit = f" Exit watch: {score.exit_triggers}." if score.exit_triggers else ""
        return {
            "suggested": "sell",
            "label": "Score looks weak — consider selling",
            "rationale": (
                f"{score.sector.replace('_', ' ')} scored {score.score:.0f} "
                f"({score.rating or 'weak'}).{exit_bit} "
                + (f" Levels: {levels.get('label')}. " if levels.get("label") else "")
                + "Confirm Sell to add it to your Groww checklist, or Keep if you disagree."
            ),
            "proposed_hold_until": None,
        }

    new_until = hold_until_from_months(score.hold_months_hi)
    if hold_until and new_until < hold_until and score.score < EXTEND_IF_BELOW and levels_action == "hold":
        pass

    until = hold_until or new_until
    rating = (score.rating or "").lower()
    if levels_action == "hold" and levels.get("label"):
        return {
            "suggested": "keep",
            "label": levels.get("label") or "Still fine to hold",
            "rationale": levels.get("rationale")
            or (
                f"{score.sector.replace('_', ' ')} scored {score.score:.0f}. "
                f"Review again by {format_display_date(until)}."
            ),
            "proposed_hold_until": until.isoformat() if until else None,
        }

    if levels_action == "review":
        return {
            "suggested": "keep",
            "label": levels.get("label") or "Check price freshness",
            "rationale": levels.get("rationale") or "Refresh Sync, then re-check levels.",
            "proposed_hold_until": hold_until.isoformat() if hold_until else None,
        }

    if score.score >= KEEP_STRONG or rating in ("buy", "strong buy", "overweight", "hold", "top pick"):
        return {
            "suggested": "keep",
            "label": "Still fine to hold",
            "rationale": (
                f"{score.sector.replace('_', ' ')} scored {score.score:.0f} "
                f"({score.rating or 'ok'}). No change needed"
                + (f" — review again by {format_display_date(until)}." if until else ".")
            ),
            "proposed_hold_until": until.isoformat() if until else None,
        }

    return {
        "suggested": "keep",
        "label": "Hold, but watch closely",
        "rationale": (
            f"{score.sector.replace('_', ' ')} scored {score.score:.0f} — not a clear buy or sell. "
            f"Keep for now"
            + (f"; next review by {format_display_date(until)}." if until else ".")
        ),
        "proposed_hold_until": until.isoformat() if until else None,
    }


def _thesis_broken(score: SectorScore, prev_score: Optional[float] = None) -> bool:
    """Sell-side hysteresis: require clear weakness, not a one-tick cross of 50."""
    rating = score.rating or ""
    if is_sell_like_rating(rating):
        return True
    exitish = "stop" in (score.exit_triggers or "").lower() and score.score < EXITISH
    if exitish:
        return True
    # Clear break below weak band
    if score.score < WEAK_SELL - SELL_HYSTERESIS:
        return True
    # Already weak last run and still below WEAK_SELL
    if (
        prev_score is not None
        and prev_score < WEAK_SELL
        and score.score < WEAK_SELL
    ):
        return True
    return False


def _price_index(fund_picks: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for _sector, picks in (fund_picks or {}).items():
        if not isinstance(picks, dict):
            continue
        for e in picks.get("etfs") or []:
            if not isinstance(e, dict):
                continue
            sym = (e.get("symbol") or "").upper()
            if sym:
                out[sym] = e
        for m in picks.get("mfs") or []:
            if not isinstance(m, dict):
                continue
            sym = (m.get("symbol") or "").strip()
            if sym:
                out[sym] = m
    return out


def _sector_exposure(open_holdings: List[Holding]) -> Dict[str, Dict[str, float]]:
    """sector_id → {weight, count, value}."""
    total = sum(max(0.0, h.market_value or 0) for h in open_holdings) or 1.0
    by: Dict[str, Dict[str, float]] = {}
    for h in open_holdings:
        sid, _ = _holding_sector_id(h)
        if not sid:
            continue
        bucket = by.setdefault(sid, {"value": 0.0, "count": 0.0, "weight": 0.0})
        bucket["value"] += max(0.0, h.market_value or 0)
        bucket["count"] += 1
    for sid in list(by.keys()):
        bucket = by[sid]
        bucket["weight"] = bucket["value"] / total
        for eq in equivalent_ids(sid):
            if eq not in by:
                by[eq] = bucket
    return by


def build_instrument_suggestions(
    db: Session,
    run: AnalysisRun,
    open_holdings: List[Holding],
    closed_holdings: List[Holding],
    fund_picks: Optional[Dict[str, Any]] = None,
    limit: int = 20,
) -> tuple:
    exposure = _sector_exposure(open_holdings)
    held_sector_ids: Set[str] = set()
    for h in open_holdings:
        sid, _ = _holding_sector_id(h)
        if sid:
            held_sector_ids |= equivalent_ids(sid)

    recommended: List[Tuple[SectorScore, Optional[float]]] = []
    for s in sorted(run.sectors, key=lambda x: x.rank):
        sid = _score_sector_id(s)
        prev_scores, was_rec = _prev_run_scores(db, sid)
        prev = prev_scores[0] if prev_scores else None
        force = bool(sid and sid in held_sector_ids and s.score >= EXIT_SCORE)
        if _is_recommended(
            s, prev, prev_scores=prev_scores, was_recommended=was_rec, force_sticky=force
        ):
            recommended.append((s, prev))

    # Prefer held sectors first in ranking for catalog fills
    def _rec_sort_key(item: Tuple[SectorScore, Optional[float]]):
        s, _ = item
        sid = _score_sector_id(s)
        held = 0 if (sid and sid in held_sector_ids) else 1
        return (held, -float(s.score or 0), s.rank)

    recommended.sort(key=_rec_sort_key)

    rec_sectors = [s.sector for s, _ in recommended]
    score_by_id: Dict[str, SectorScore] = {}
    for s, _ in recommended:
        sid = _score_sector_id(s)
        if sid:
            score_by_id[sid] = s
            for eq in equivalent_ids(sid):
                score_by_id.setdefault(eq, s)

    open_ids: Set[str] = {h.instrument_id for h in open_holdings if h.instrument_id}
    open_keys: Set[str] = set()
    for h in open_holdings:
        for raw in (
            h.instrument_id,
            h.scheme_code,
            h.external_key,
            h.instrument,
            getattr(h.instrument_row, "nse_symbol", None) if h.instrument_row else None,
            getattr(h.instrument_row, "isin", None) if h.instrument_row else None,
            getattr(h.instrument_row, "amfi_code", None) if h.instrument_row else None,
        ):
            k = str(raw or "").strip().upper()
            if k:
                open_keys.add(k)

    def _already_held(inst) -> bool:
        if inst.id in open_ids:
            return True
        for raw in (inst.id, inst.nse_symbol, inst.isin, inst.amfi_code, inst.display_name):
            k = str(raw or "").strip().upper()
            if k and k in open_keys:
                return True
        return False

    prices = _price_index(fund_picks or {})

    ideas: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    def _overweight_meta(sector_id: Optional[str]) -> Dict[str, Any]:
        if not sector_id:
            return {"overweight_warning": False}
        exp = exposure.get(sector_id) or {}
        weight = float(exp.get("weight") or 0)
        count = int(exp.get("count") or 0)
        warn = weight >= CONCENTRATION_MAX_WEIGHT or count >= CONCENTRATION_MAX_NAMES
        return {
            "overweight_warning": warn,
            "sector_weight": round(weight, 4),
            "sector_open_count": count,
        }

    for h in closed_holdings:
        if not h.instrument_id or h.instrument_id in open_ids:
            continue
        # Also skip closed ideas that match an open holding by ticker/ISIN
        hd = holding_to_dict(h)
        sym = str(hd.get("symbol") or h.scheme_code or h.external_key or "").strip().upper()
        if sym and sym in open_keys:
            continue
        score, match = _score_for_holding(run, h)
        prev_scores, was_rec = _prev_run_scores(db, match.get("holding_sector_id"))
        prev = prev_scores[0] if prev_scores else None
        if not score or not _is_recommended(
            score, prev, prev_scores=prev_scores, was_recommended=was_rec
        ):
            continue
        if h.instrument_id in seen_ids:
            continue
        until = hold_until_from_months(score.hold_months_hi)
        sid = match.get("matched_score_sector_id") or match.get("holding_sector_id")
        meta = _overweight_meta(sid)
        ideas.append(
            {
                "instrument_id": h.instrument_id,
                "instrument": h.instrument,
                "asset_class": h.asset_class,
                "sector": score.sector,
                "sector_id": sid,
                "symbol": hd.get("symbol") or h.scheme_code or h.external_key,
                "kind": "previously_sold",
                "score": score.score,
                "prev_score": prev,
                "rating": score.rating,
                "hold_months_lo": score.hold_months_lo,
                "hold_months_hi": score.hold_months_hi,
                "proposed_hold_until": until.isoformat(),
                "suggested": "buy",
                "label": f"You sold this before — {hd.get('symbol') or h.instrument}",
                "rationale": (
                    f"{score.sector.replace('_', ' ')} is still a buy idea (score {score.score:.0f}). "
                    f"Suggested hold until {format_display_date(until)}"
                    + (f". You closed it on {format_display_date(h.closed_at)}" if h.closed_at else "")
                    + "."
                ),
                "closed_at": h.closed_at.isoformat() if h.closed_at else None,
                "holding_id": h.id,
                **meta,
            }
        )
        seen_ids.add(h.instrument_id)

    catalog = catalog_for_sectors(db, rec_sectors)
    filtered: Dict[str, Dict[str, List]] = {}

    for inst in catalog:
        sid = inst.sector_id or normalize_sector(inst.sector) or None
        score = score_by_id.get(sid) if sid else None
        if not score:
            continue

        held = _already_held(inst)
        bucket = filtered.setdefault(score.sector, {"etfs": [], "mfs": []})
        price = {}
        if inst.nse_symbol and inst.nse_symbol.upper() in prices:
            price = prices[inst.nse_symbol.upper()]
        elif inst.amfi_code and inst.amfi_code in prices:
            price = prices[inst.amfi_code]

        pick_row = {
            "instrument_id": inst.id,
            "symbol": inst.nse_symbol or inst.amfi_code,
            "name": inst.display_name,
            "ltp": price.get("ltp"),
            "nav": price.get("nav"),
            "kind": "previously_sold" if inst.id in seen_ids else "new",
        }
        if not held:
            if inst.asset_class == "etf":
                bucket["etfs"].append(pick_row)
            elif inst.asset_class == "mf":
                bucket["mfs"].append(pick_row)
            elif inst.asset_class == "stock":
                bucket.setdefault("stocks", []).append(pick_row)

        if held or inst.id in seen_ids:
            continue

        until = hold_until_from_months(score.hold_months_hi)
        prev = _prev_run_score(db, sid)
        meta = _overweight_meta(sid)
        # Prefer sticky book: do not push new names into already-heavy sectors
        if meta.get("overweight_warning"):
            continue
        ideas.append(
            {
                "instrument_id": inst.id,
                "instrument": inst.display_name,
                "asset_class": inst.asset_class,
                "sector": score.sector,
                "sector_id": sid,
                "symbol": inst.nse_symbol or inst.amfi_code,
                "kind": "new",
                "score": score.score,
                "prev_score": prev,
                "rating": score.rating,
                "hold_months_lo": score.hold_months_lo,
                "hold_months_hi": score.hold_months_hi,
                "proposed_hold_until": until.isoformat(),
                "suggested": "buy",
                "label": f"Not in your book — {inst.display_name}",
                "rationale": (
                    f"Catalog {inst.asset_class.upper()} for {score.sector.replace('_', ' ')} "
                    f"(score {score.score:.0f}). Suggested hold until {format_display_date(until)}."
                ),
                "ltp": price.get("ltp"),
                "nav": price.get("nav"),
                **meta,
            }
        )
        seen_ids.add(inst.id)

    filtered = {
        k: v
        for k, v in filtered.items()
        if (v.get("etfs") or v.get("mfs") or v.get("stocks"))
    }

    ideas.sort(
        key=lambda x: (
            0 if x.get("kind") == "previously_sold" else 1,
            0 if (x.get("sector_id") in held_sector_ids) else 1,
            1 if x.get("overweight_warning") else 0,
            -float(x.get("score") or 0),
            x.get("instrument") or "",
        )
    )
    return ideas[:limit], filtered


def _sync_freshness(db: Session) -> Dict[str, Any]:
    from datetime import datetime

    from backend.decision.models import SyncMeta

    meta = db.get(SyncMeta, 1)
    now = datetime.now()

    def _age_days(ts) -> Optional[float]:
        if not ts:
            return None
        return (now - ts).total_seconds() / 86400.0

    stocks_at = meta.last_stocks_sync_at if meta else None
    mf_at = meta.last_mf_sync_at if meta else None
    stocks_age = _age_days(stocks_at)
    mf_age = _age_days(mf_at)
    return {
        "last_stocks_sync_at": stocks_at.isoformat() if stocks_at else None,
        "last_mf_sync_at": mf_at.isoformat() if mf_at else None,
        "stocks_stale": stocks_age is None or stocks_age > STOCKS_STALE_DAYS,
        "mf_stale": mf_age is None or mf_age > MF_STALE_DAYS,
        "stocks_age_days": round(stocks_age, 1) if stocks_age is not None else None,
        "mf_age_days": round(mf_age, 1) if mf_age is not None else None,
    }


def build_diff(db: Session, run: Optional[AnalysisRun] = None) -> Dict[str, Any]:
    from datetime import datetime

    from backend.decision.calibration import build_calibration
    from backend.decision.models import SyncMeta
    from backend.decision.sectors import sector_registry_export
    from backend.decision.trade_levels import (
        fetch_equity_quotes,
        levels_for_holding,
        price_stale_for,
    )

    run = run or get_latest_run(db)
    all_holdings = list_holdings(db, include_closed=True)
    open_holdings = [h for h in all_holdings if h.status != "closed"]
    closed_holdings = [h for h in all_holdings if h.status == "closed"]
    rows: List[Dict[str, Any]] = []
    join_debug: List[Dict[str, Any]] = []

    quotes = fetch_equity_quotes(open_holdings)
    meta = db.get(SyncMeta, 1)
    stocks_sync = meta.last_stocks_sync_at if meta else None
    mf_sync = meta.last_mf_sync_at if meta else None

    if run:
        for h in open_holdings:
            score, match = _score_for_holding(run, h)
            stale = _plan_stale(h, score, match)
            quote = quotes.get(h.id)
            sync_ts = mf_sync if h.asset_class == "mf" else stocks_sync
            # Fresh Kite LTP means not stale for equities
            stale_price = False if quote else price_stale_for(h, sync_ts)
            levels = levels_for_holding(
                h,
                score,
                quote=quote,
                price_as_of=datetime.now() if quote else sync_ts,
                price_stale=stale_price,
            )
            prev_scores, _was = _prev_run_scores(db, match.get("holding_sector_id"))
            prev = prev_scores[0] if prev_scores else None
            proposal = propose_action(
                h.sector,
                score,
                h.hold_until,
                match_confidence=match["match_confidence"],
                plan_stale=stale,
                trade_levels=levels,
                prev_score=prev,
            )
            row = {
                "holding": holding_to_dict(h),
                "sector_score": {
                    "sector": score.sector,
                    "sector_id": match.get("matched_score_sector_id"),
                    "score": score.score,
                    "rating": score.rating,
                    "hold_months_lo": score.hold_months_lo,
                    "hold_months_hi": score.hold_months_hi,
                    "stop_loss_pct": score.stop_loss_pct,
                    "exit_triggers": score.exit_triggers,
                    "prev_score": prev,
                }
                if score
                else None,
                "match": match,
                "plan_stale": stale,
                "trade_levels": levels,
                "proposal": proposal,
            }
            rows.append(row)
            join_debug.append(
                {
                    "holding_id": h.id,
                    "instrument": h.instrument,
                    "holding_sector": h.sector,
                    **match,
                    "proposal": proposal["suggested"],
                    "levels_action": levels.get("action"),
                }
            )

        run_dict = run_to_dict(run)
        fund_picks = run_dict.get("fund_picks") or {}
        buy_ideas, fund_picks_filtered = build_instrument_suggestions(
            db, run, open_holdings, closed_holdings, fund_picks
        )
        run_dict["fund_picks"] = fund_picks_filtered
        run_dict["fund_picks_raw"] = fund_picks
        calibration = build_calibration(db)
    else:
        for h in open_holdings:
            sid, conf = _holding_sector_id(h)
            match = {
                "holding_sector_id": sid,
                "matched_score_sector_id": None,
                "matched_score": None,
                "match_confidence": conf if sid else "none",
            }
            quote = quotes.get(h.id)
            sync_ts = mf_sync if h.asset_class == "mf" else stocks_sync
            stale_price = False if quote else price_stale_for(h, sync_ts)
            levels = levels_for_holding(
                h,
                None,
                quote=quote,
                price_as_of=datetime.now() if quote else sync_ts,
                price_stale=stale_price,
            )
            rows.append(
                {
                    "holding": holding_to_dict(h),
                    "sector_score": None,
                    "match": match,
                    "plan_stale": False,
                    "trade_levels": levels,
                    "proposal": {
                        "suggested": "keep",
                        "label": "No analysis yet",
                        "rationale": "Run analysis first so Pulse can compare this holding to sector scores.",
                        "proposed_hold_until": h.hold_until.isoformat() if h.hold_until else None,
                    },
                }
            )
            join_debug.append(
                {
                    "holding_id": h.id,
                    "instrument": h.instrument,
                    "holding_sector": h.sector,
                    **match,
                    "proposal": "keep",
                    "levels_action": levels.get("action"),
                }
            )
        buy_ideas = []
        fund_picks_filtered = {}
        run_dict = None
        calibration = None

    return {
        "run": run_dict,
        "rows": rows,
        "buy_ideas": buy_ideas,
        "fund_picks_filtered": fund_picks_filtered if run else {},
        "due_count": sum(1 for r in rows if r["holding"]["status"] in ("due", "overdue")),
        "unmapped_count": sum(
            1 for r in rows if (r.get("match") or {}).get("match_confidence") == "none"
        ),
        "sync_freshness": _sync_freshness(db),
        "calibration": calibration,
        "join_debug": join_debug,
        "sector_registry": sector_registry_export(),
    }
