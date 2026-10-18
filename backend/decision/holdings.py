"""Holdings CRUD, sync upsert, migration from legacy ledger."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.decision.helpers import normalize_sector
from backend.decision.models import Holding, OrderLog, SyncMeta
from backend.decision.sectors import resolve_sector_id


def _set_sector_fields(obj, sector: str) -> str:
    sid, _ = resolve_sector_id(sector or "")
    canonical = sid or normalize_sector(sector) or (sector or "")
    if hasattr(obj, "sector"):
        obj.sector = canonical
    if hasattr(obj, "sector_id"):
        obj.sector_id = sid
    return canonical


def _attach_instrument(db: Session, h: Holding) -> None:
    from backend.decision.instruments import resolve_for_holding

    if h.instrument_id:
        return
    inst = resolve_for_holding(
        db,
        asset_class=h.asset_class,
        instrument_name=h.instrument,
        external_key=h.external_key or "",
        scheme_code=h.scheme_code,
        sector=h.sector or "",
    )
    h.instrument_id = inst.id
    if inst.sector and not h.sector:
        _set_sector_fields(h, inst.sector_id or inst.sector)
    elif not h.sector_id and (h.sector or inst.sector):
        sid, _ = resolve_sector_id(h.sector or inst.sector or "")
        h.sector_id = sid
        if sid and not h.sector:
            h.sector = sid

logger = logging.getLogger(__name__)


def _refresh_status(h: Holding) -> None:
    if h.status == "closed":
        return
    if not h.hold_until:
        h.status = "holding"
        return
    from datetime import timedelta

    today = date.today()
    if h.hold_until < today:
        h.status = "overdue"
    elif h.hold_until <= today + timedelta(days=14):
        h.status = "due"
    else:
        h.status = "holding"


def holding_to_dict(h: Holding) -> Dict[str, Any]:
    _refresh_status(h)
    pnl = h.market_value - h.invested_amount
    pnl_pct = (pnl / h.invested_amount * 100) if h.invested_amount else 0.0
    needs_id_review = False
    symbol: Optional[str] = None
    if h.instrument_id:
        from backend.decision.models import Instrument

        # Prefer loaded relationship; else one lookup
        inst = h.instrument_row
        if inst is None:
            from sqlalchemy.orm import object_session

            sess = object_session(h)
            if sess is not None:
                inst = sess.get(Instrument, h.instrument_id)
        if inst is not None:
            needs_id_review = bool(inst.needs_id_review)
            symbol = (inst.nse_symbol or inst.amfi_code or "").strip() or None
    if not symbol:
        # ETF/stock sync often stores ticker as instrument / external_key
        for cand in (h.scheme_code, h.external_key, h.instrument):
            raw = (cand or "").strip()
            if not raw:
                continue
            # Short alphanumeric ticker (MOREALTY), not long fund names / ISINs
            if len(raw) <= 16 and raw.replace("-", "").isalnum() and not raw.startswith("INF"):
                symbol = raw.upper() if raw.isascii() else raw
                break
    return {
        "id": h.id,
        "instrument": h.instrument,
        "symbol": symbol,
        "asset_class": h.asset_class,
        "external_key": h.external_key,
        "scheme_code": h.scheme_code,
        "sector": h.sector,
        "sector_id": h.sector_id,
        "units": h.units,
        "avg_cost": h.avg_cost,
        "invested_amount": h.invested_amount,
        "last_price": h.last_price,
        "market_value": h.market_value,
        "hold_until": h.hold_until.isoformat() if h.hold_until else None,
        "reason": h.reason,
        "status": h.status,
        "opened_by_run_id": h.opened_by_run_id,
        "last_reviewed_run_id": h.last_reviewed_run_id,
        "missing_from_sync": h.missing_from_sync,
        "needs_plan": h.needs_plan,
        "needs_id_review": needs_id_review,
        "instrument_id": h.instrument_id,
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
    }


def list_holdings(db: Session, include_closed: bool = False) -> List[Holding]:
    q = select(Holding)
    if not include_closed:
        q = q.where(Holding.status != "closed")
    rows = list(db.scalars(q.order_by(Holding.instrument)).all())
    for h in rows:
        _refresh_status(h)
    return rows


def get_holding(db: Session, holding_id: str) -> Optional[Holding]:
    return db.get(Holding, holding_id)


def upsert_holding(
    db: Session,
    *,
    instrument: str,
    asset_class: str,
    external_key: str,
    units: float,
    invested_amount: float,
    last_price: float,
    market_value: float,
    sector: str = "",
    scheme_code: Optional[str] = None,
    avg_cost: float = 0,
    preserve_plan: bool = True,
) -> Holding:
    existing = db.scalars(
        select(Holding).where(
            Holding.asset_class == asset_class,
            Holding.external_key == external_key,
        )
    ).first()
    # Same ISIN under stock vs etf → reuse the existing open row (avoid duplicates)
    if not existing and external_key:
        key = external_key.strip().upper()
        if len(key) >= 10 and (key.startswith("INF") or (len(key) == 12 and key[:3].isalpha())):
            candidates = list(
                db.scalars(
                    select(Holding).where(
                        Holding.status != "closed",
                        (Holding.external_key == external_key)
                        | (Holding.external_key == key)
                        | (Holding.scheme_code == external_key)
                        | (Holding.scheme_code == key),
                    )
                ).all()
            )
            if candidates:
                # Prefer matching asset_class, else etf over stock
                pref = sorted(
                    candidates,
                    key=lambda h: (
                        0 if h.asset_class == asset_class else 1,
                        0 if h.asset_class == "etf" else 1,
                        h.id,
                    ),
                )
                existing = pref[0]
                # Normalize class toward etf when either side is etf
                if asset_class == "etf" or existing.asset_class == "etf":
                    existing.asset_class = "etf"
                    asset_class = "etf"
    if existing:
        existing.instrument = instrument
        existing.units = units
        existing.invested_amount = invested_amount
        existing.last_price = last_price
        existing.market_value = market_value
        existing.avg_cost = avg_cost or existing.avg_cost
        existing.scheme_code = scheme_code or existing.scheme_code
        if sector and not existing.sector:
            _set_sector_fields(existing, sector)
        existing.missing_from_sync = False
        if existing.status == "closed" and units > 0:
            existing.status = "holding"
            existing.closed_at = None
        if not preserve_plan and not existing.hold_until:
            existing.needs_plan = True
        _attach_instrument(db, existing)
        if existing.instrument_id and not existing.sector_id:
            from backend.decision.models import Instrument

            inst = db.get(Instrument, existing.instrument_id)
            if inst and (inst.sector_id or inst.sector):
                _set_sector_fields(existing, inst.sector_id or inst.sector)
        _refresh_status(existing)
        return existing

    h = Holding(
        id=str(uuid.uuid4())[:12],
        instrument=instrument,
        asset_class=asset_class,
        external_key=external_key,
        scheme_code=scheme_code,
        units=units,
        avg_cost=avg_cost,
        invested_amount=invested_amount,
        last_price=last_price,
        market_value=market_value,
        needs_plan=True,
        status="holding",
    )
    _set_sector_fields(h, sector)
    db.add(h)
    _attach_instrument(db, h)
    return h


def update_holding_plan(
    db: Session,
    holding_id: str,
    *,
    hold_until: Optional[date] = None,
    reason: Optional[str] = None,
    sector: Optional[str] = None,
    run_id: Optional[str] = None,
    status: Optional[str] = None,
) -> Optional[Holding]:
    h = db.get(Holding, holding_id)
    if not h:
        return None
    if hold_until is not None:
        h.hold_until = hold_until
        h.needs_plan = False
    if reason is not None:
        h.reason = reason
    if sector is not None:
        _set_sector_fields(h, sector)
    if run_id:
        h.last_reviewed_run_id = run_id
        if not h.opened_by_run_id:
            h.opened_by_run_id = run_id
    if status:
        h.status = status
        if status == "closed":
            h.closed_at = date.today()
    _refresh_status(h)
    return h


def mark_missing_not_in_keys(db: Session, asset_class: str, present_keys: set) -> int:
    n = 0
    for h in list_holdings(db):
        if h.asset_class != asset_class or h.status == "closed":
            continue
        if h.external_key not in present_keys:
            h.missing_from_sync = True
            n += 1
    return n


def set_sync_meta(db: Session, *, stocks: bool = False, mf: bool = False) -> None:
    meta = db.get(SyncMeta, 1)
    if not meta:
        meta = SyncMeta(id=1)
        db.add(meta)
    now = datetime.now()
    if stocks:
        meta.last_stocks_sync_at = now
    if mf:
        meta.last_mf_sync_at = now


def get_sync_meta(db: Session) -> Dict[str, Any]:
    meta = db.get(SyncMeta, 1)
    if not meta:
        return {"last_stocks_sync_at": None, "last_mf_sync_at": None}
    return {
        "last_stocks_sync_at": meta.last_stocks_sync_at.isoformat() if meta.last_stocks_sync_at else None,
        "last_mf_sync_at": meta.last_mf_sync_at.isoformat() if meta.last_mf_sync_at else None,
    }


def append_order(db: Session, order: Dict[str, Any]) -> None:
    oid = str(order.get("groww_order_id") or "")
    if not oid:
        return
    existing = db.scalars(select(OrderLog).where(OrderLog.groww_order_id == oid)).first()
    if existing:
        return
    import json

    db.add(
        OrderLog(
            groww_order_id=oid,
            trading_symbol=str(order.get("trading_symbol") or ""),
            transaction_type=str(order.get("transaction_type") or ""),
            quantity=float(order.get("quantity") or order.get("filled_quantity") or 0),
            price=float(order.get("average_fill_price") or order.get("price") or 0),
            order_status=str(order.get("order_status") or ""),
            trade_date=str(order.get("trade_date") or order.get("created_at") or ""),
            raw_json=json.dumps(order),
        )
    )


def migrate_from_legacy_ledger(db: Session) -> Dict[str, Any]:
    """Copy open positions from InvestmentLedger into Decision OS holdings."""
    from backend.portfolio.ledger import InvestmentLedger

    legacy = InvestmentLedger()
    created = 0
    skipped = 0
    for p in legacy.list_positions(include_closed=False):
        asset = p.get("asset_class") or "mf"
        key = (p.get("scheme_code") or p.get("instrument") or "").strip()
        if not key:
            skipped += 1
            continue
        hold_until = None
        if p.get("exit_by_date"):
            try:
                hold_until = date.fromisoformat(str(p["exit_by_date"])[:10])
            except ValueError:
                hold_until = None
        h = upsert_holding(
            db,
            instrument=p["instrument"],
            asset_class=asset,
            external_key=key,
            units=float(p.get("units") or 0),
            invested_amount=float(p.get("invested_amount") or 0),
            last_price=float(p.get("last_nav") or p.get("avg_cost") or 0),
            market_value=float(p.get("market_value") or 0),
            sector=p.get("sector") or "",
            scheme_code=p.get("scheme_code"),
            avg_cost=float(p.get("avg_cost") or 0),
            preserve_plan=True,
        )
        if hold_until and not h.hold_until:
            h.hold_until = hold_until
            h.needs_plan = False
        if p.get("thesis") and not h.reason:
            h.reason = (p.get("thesis") or "")[:500]
            h.needs_plan = False if h.hold_until else h.needs_plan
        created += 1
    db.commit()
    return {"migrated": created, "skipped": skipped}
