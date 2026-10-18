"""Legacy JSON API for old Pulse OS (SIP / satellite / review).

Primary product is Decision OS under `/api/decide/*` + Next.js apps/web.
This router remains for one-off ledger tooling; do not build new UI on it.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.data.groww_client import GrowwClient
from backend.data.nav_client import fetch_latest_nav, nav_for_scheme, search_schemes
from backend.portfolio.ledger import InvestmentLedger

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/os", tags=["os"])
ledger = InvestmentLedger()


def _cycle_context() -> Dict[str, str]:
    """Pull phase from cached pipeline results if available."""
    try:
        from backend.data.cache_manager import CacheManager

        results = CacheManager().get("pipeline_results") or {}
        return {
            "current_phase": results.get("current_phase") or "",
            "current_sub_phase": results.get("sub_phase") or "",
        }
    except Exception:
        return {"current_phase": "", "current_sub_phase": ""}


def _alerts(summary: Dict[str, Any], attention: List[Dict], cycle: Dict[str, str]) -> List[str]:
    alerts: List[str] = []
    today = date.today()
    for p in attention:
        if p.get("status") == "exit_due" or (
            p.get("exit_by_date") and p["exit_by_date"][:10] < today.isoformat()
        ):
            alerts.append(f"Exit overdue: {p['instrument']}")
        elif p.get("exit_by_date"):
            try:
                ed = date.fromisoformat(p["exit_by_date"][:10])
                if today <= ed <= today + timedelta(days=7):
                    alerts.append(f"Exit within 7 days: {p['instrument']}")
            except ValueError:
                pass
        if p.get("pnl_pct", 0) <= -float(p.get("stop_loss_pct") or 12):
            alerts.append(f"Stop loss hit: {p['instrument']}")
        invalid = (p.get("thesis_invalid_if") or "").strip()
        sub = cycle.get("current_sub_phase") or ""
        if invalid and sub and invalid.lower() in sub.lower():
            alerts.append(f"Thesis conflict ({sub}): {p['instrument']}")
    if summary.get("satellite_pct", 0) > 30:
        alerts.append(
            f"Satellite weight {summary['satellite_pct']}% — above 30% band; consider trim"
        )
    last = ledger.last_review_date()
    if last:
        try:
            if (today - date.fromisoformat(last[:10])).days > 35:
                alerts.append(f"Monthly review overdue (last: {last})")
        except ValueError:
            pass
    elif summary.get("position_count", 0) > 0:
        alerts.append("No monthly review yet — run the wizard")
    return alerts


# ── Schemas ───────────────────────────────────────────────


class PositionCreate(BaseModel):
    instrument: str
    thesis: str
    asset_class: str = "mf"
    scheme_code: Optional[str] = None
    sector: str = ""
    sleeve: str = "satellite"
    units: float = 0
    invested_amount: float = 0
    avg_cost: Optional[float] = None
    entry_date: Optional[str] = None
    horizon_months_lo: int = 6
    horizon_months_hi: int = 9
    target_return_pct: Optional[float] = None
    stop_loss_pct: float = 12
    take_profit_pct: Optional[float] = None
    review_date: Optional[str] = None
    exit_by_date: Optional[str] = None
    thesis_invalid_if: str = ""
    notes: str = ""
    last_nav: Optional[float] = None


class PositionUpdate(BaseModel):
    instrument: Optional[str] = None
    thesis: Optional[str] = None
    asset_class: Optional[str] = None
    scheme_code: Optional[str] = None
    sector: Optional[str] = None
    sleeve: Optional[str] = None
    units: Optional[float] = None
    invested_amount: Optional[float] = None
    horizon_months_lo: Optional[int] = None
    horizon_months_hi: Optional[int] = None
    target_return_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    review_date: Optional[str] = None
    exit_by_date: Optional[str] = None
    thesis_invalid_if: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class CloseBody(BaseModel):
    exit_nav: float
    outcome_tags: str = "thesis_right"
    note: str = ""


class NavBody(BaseModel):
    nav: float
    nav_date: Optional[str] = None


class LumpsumBody(BaseModel):
    amount: float
    nav: float
    tx_date: Optional[str] = None


class SipCreate(BaseModel):
    position_id: str
    amount: float
    sip_day: int = Field(ge=1, le=28)
    start_date: str


class ReconcileBody(BaseModel):
    position_id: str
    units: float
    nav: float
    invested_amount: Optional[float] = None


class ReviewDecision(BaseModel):
    position_id: str
    decision: str
    reason: str = ""


class ReviewCreate(BaseModel):
    decisions: List[ReviewDecision]
    notes: str = ""


class GrowwCredentials(BaseModel):
    api_key: str
    api_secret: str = ""
    access_token: str = ""
    expires_at: Optional[str] = None


# ── Home / attention ─────────────────────────────────────


@router.get("/home")
def os_home():
    cycle = _cycle_context()
    summary = ledger.portfolio_summary()
    attention = ledger.attention_queue(cycle.get("current_sub_phase", ""))
    return {
        "summary": summary,
        "attention": attention,
        "alerts": _alerts(summary, attention, cycle),
        "calibration": ledger.closed_calibration_stats(),
        "cycle": cycle,
        "last_review": ledger.last_review_date(),
    }


# ── Positions ─────────────────────────────────────────────


@router.get("/positions")
def list_positions(include_closed: bool = False):
    open_pos = ledger.list_positions()
    closed = ledger.list_positions(status="closed") if include_closed else []
    return {"positions": open_pos, "closed": closed, "cycle": _cycle_context()}


@router.post("/positions")
def create_position(body: PositionCreate):
    data = body.model_dump()
    if not data.get("thesis", "").strip():
        raise HTTPException(400, "Thesis is required")
    if data.get("avg_cost") is None and data.get("units") and data.get("invested_amount"):
        data["avg_cost"] = data["invested_amount"] / data["units"]
    return ledger.create_position(data)


@router.get("/positions/{position_id}")
def get_position(position_id: str):
    pos = ledger.get_position(position_id)
    if not pos:
        raise HTTPException(404, "Position not found")
    return {
        "position": pos,
        "transactions": ledger.list_transactions(position_id),
        "cycle": _cycle_context(),
    }


@router.patch("/positions/{position_id}")
def update_position(position_id: str, body: PositionUpdate):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    pos = ledger.update_position(position_id, fields)
    if not pos:
        raise HTTPException(404, "Position not found")
    return pos


@router.post("/positions/{position_id}/close")
def close_position(position_id: str, body: CloseBody):
    pos = ledger.close_position(position_id, body.exit_nav, body.outcome_tags, body.note)
    if not pos:
        raise HTTPException(404, "Position not found")
    return pos


@router.post("/positions/{position_id}/reviewed")
def mark_reviewed(position_id: str):
    new_review = (date.today() + timedelta(days=30)).isoformat()
    pos = ledger.update_position(position_id, {"review_date": new_review, "status": "open"})
    if not pos:
        raise HTTPException(404, "Position not found")
    return pos


@router.post("/positions/{position_id}/extend")
def extend_horizon(position_id: str):
    pos = ledger.get_position(position_id)
    if not pos:
        raise HTTPException(404, "Position not found")
    fields: Dict[str, Any] = {"status": "open", "review_date": (date.today() + timedelta(days=30)).isoformat()}
    if pos.get("exit_by_date"):
        try:
            fields["exit_by_date"] = (
                date.fromisoformat(pos["exit_by_date"][:10]) + timedelta(days=90)
            ).isoformat()
        except ValueError:
            pass
    return ledger.update_position(position_id, fields)


@router.post("/positions/{position_id}/nav")
def set_nav(position_id: str, body: NavBody):
    pos = ledger.update_nav(position_id, body.nav, body.nav_date)
    if not pos:
        raise HTTPException(404, "Position not found")
    return pos


@router.post("/positions/{position_id}/refresh-nav")
def refresh_nav(position_id: str):
    pos = ledger.get_position(position_id)
    if not pos:
        raise HTTPException(404, "Position not found")
    if not pos.get("scheme_code"):
        raise HTTPException(400, "No scheme_code on position")
    info = fetch_latest_nav(pos["scheme_code"])
    if not info:
        raise HTTPException(502, "Could not fetch NAV")
    return ledger.update_nav(position_id, info["nav"], info.get("date"))


@router.post("/positions/{position_id}/lumpsum")
def add_lumpsum(position_id: str, body: LumpsumBody):
    pos = ledger.add_lumpsum(position_id, body.amount, body.nav, body.tx_date)
    if not pos:
        raise HTTPException(404, "Position not found")
    return pos


# ── SIPs ───────────────────────────────────────────────────


@router.get("/sips")
def list_sips():
    return {"sips": ledger.list_sips(), "positions": ledger.list_positions()}


@router.post("/sips")
def create_sip(body: SipCreate):
    pos = ledger.get_position(body.position_id)
    if not pos:
        raise HTTPException(404, "Position not found")
    return ledger.create_sip(body.position_id, body.amount, body.sip_day, body.start_date)


@router.post("/sips/{sip_id}/deactivate")
def deactivate_sip(sip_id: str):
    ledger.deactivate_sip(sip_id)
    return {"ok": True}


# ── Portfolio ──────────────────────────────────────────────


@router.get("/portfolio")
def portfolio():
    return {
        "summary": ledger.portfolio_summary(),
        "positions": ledger.list_positions(),
        "snapshots": ledger.list_snapshots(),
    }


@router.post("/portfolio/refresh-nav")
def refresh_all_navs():
    updated = []
    for pos in ledger.list_positions():
        if pos.get("asset_class") != "mf" or not pos.get("scheme_code"):
            continue
        info = fetch_latest_nav(pos["scheme_code"])
        if info:
            ledger.update_nav(pos["id"], info["nav"], info.get("date"))
            updated.append(pos["id"])
    return {"updated": updated, "summary": ledger.portfolio_summary()}


@router.post("/portfolio/process-sips")
def process_sips():
    credited = ledger.process_due_sips(nav_for_scheme)
    return {"credited": credited, "summary": ledger.portfolio_summary()}


@router.post("/portfolio/snapshot")
def take_snapshot():
    return ledger.take_snapshot()


@router.post("/portfolio/reconcile")
def reconcile(body: ReconcileBody):
    fields: Dict[str, Any] = {
        "units": body.units,
        "last_nav": body.nav,
        "last_nav_date": date.today().isoformat(),
        "market_value": body.units * body.nav,
    }
    if body.invested_amount is not None:
        fields["invested_amount"] = body.invested_amount
        fields["avg_cost"] = body.invested_amount / body.units if body.units else 0
    else:
        pos = ledger.get_position(body.position_id)
        if pos and body.units:
            fields["avg_cost"] = float(pos["invested_amount"]) / body.units
    pos = ledger.update_position(body.position_id, fields)
    if not pos:
        raise HTTPException(404, "Position not found")
    return pos


@router.get("/schemes/search")
def scheme_search(q: str = ""):
    return {"results": search_schemes(q)}


# ── Reviews ────────────────────────────────────────────────


@router.get("/reviews")
def list_reviews():
    return {
        "reviews": ledger.list_reviews(),
        "positions": ledger.list_positions(),
        "summary": ledger.portfolio_summary(),
        "last_review": ledger.last_review_date(),
        "cycle": _cycle_context(),
    }


@router.get("/reviews/{review_id}")
def get_review(review_id: str):
    rev = ledger.get_review(review_id)
    if not rev:
        raise HTTPException(404, "Review not found")
    # Enrich decisions with instrument names
    for d in rev.get("decisions", []):
        pos = ledger.get_position(d["position_id"])
        d["instrument"] = pos["instrument"] if pos else d["position_id"]
    return rev


@router.post("/reviews")
def create_review(body: ReviewCreate):
    cycle = _cycle_context()
    checklist = []
    decisions = [d.model_dump() for d in body.decisions]
    for d in decisions:
        pos = ledger.get_position(d["position_id"])
        name = pos["instrument"] if pos else d["position_id"]
        if d["decision"] == "exit":
            checklist.append({"action": "SELL", "instrument": name, "note": d.get("reason", "")})
        elif d["decision"] == "trim":
            checklist.append({"action": "TRIM", "instrument": name, "note": d.get("reason", "")})
    ledger.take_snapshot()
    review = ledger.create_review(
        decisions=decisions,
        cycle_phase=cycle.get("current_phase", ""),
        cycle_sub_phase=cycle.get("current_sub_phase", ""),
        notes=body.notes,
        action_checklist=checklist,
    )
    return review


# ── Groww ──────────────────────────────────────────────────


@router.get("/groww/status")
def groww_status():
    creds = ledger.get_groww_credentials() or {}
    client = GrowwClient(
        api_key=creds.get("api_key") or None,
        api_secret=None,
        access_token=creds.get("access_token") or None,
    )
    # Prefer env secret + key
    env_client = GrowwClient()
    status = env_client.status()
    status["last_sync_at"] = creds.get("last_sync_at")
    status["db_has_token"] = bool(creds.get("access_token"))
    return status


@router.post("/groww/credentials")
def save_groww_credentials(body: GrowwCredentials):
    ledger.save_groww_token(body.api_key, body.access_token or body.api_key, body.expires_at)
    return {"ok": True}


@router.post("/groww/sync")
def groww_sync():
    creds = ledger.get_groww_credentials() or {}
    client = GrowwClient(
        api_key=creds.get("api_key") or None,
        access_token=creds.get("access_token") or None,
    )
    # Env takes precedence for key/secret exchange
    if GrowwClient().configured:
        client = GrowwClient()
    try:
        holdings = client.fetch_holdings()
    except Exception as exc:
        raise HTTPException(502, f"Groww sync failed: {exc}") from exc

    synced = []
    existing = {p["instrument"].upper(): p for p in ledger.list_positions(include_closed=True)}
    for h in holdings:
        key = h["instrument"].upper()
        if key in existing and existing[key].get("status") != "closed":
            ledger.update_position(
                existing[key]["id"],
                {
                    "units": h["units"],
                    "avg_cost": h["avg_cost"],
                    "invested_amount": h["invested_amount"],
                    "last_nav": h["last_nav"],
                    "last_nav_date": date.today().isoformat(),
                    "market_value": h["units"] * h["last_nav"],
                    "scheme_code": h.get("scheme_code") or existing[key].get("scheme_code"),
                },
            )
            synced.append({**h, "id": existing[key]["id"], "action": "updated"})
        else:
            created = ledger.create_position(
                {
                    **h,
                    "thesis": "Synced from Groww equity holdings — add thesis",
                    "entry_date": date.today().isoformat(),
                    "horizon_months_lo": 6,
                    "horizon_months_hi": 9,
                }
            )
            synced.append({**h, "id": created["id"], "action": "created"})
    ledger.mark_groww_synced()
    if client.access_token:
        ledger.save_groww_token(
            client.api_key or "env",
            client.access_token,
            client._token_expiry,
        )
    return {"synced": synced, "count": len(synced)}
