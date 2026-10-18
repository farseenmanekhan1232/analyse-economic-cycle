"""One-shot / idempotent data repairs for Decision OS SQLite."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.decision.instruments import SECTOR_CATALOG, find_instrument, upsert_instrument
from backend.decision.models import Holding, Instrument, SectorScore
from backend.decision.sectors import normalize_sector, resolve_sector_id

logger = logging.getLogger(__name__)


def repair_sector_ids(db: Session) -> int:
    """Backfill / correct sector_id on holdings, instruments, scores."""
    n = 0
    for row in list(db.scalars(select(Holding)).all()) + list(
        db.scalars(select(Instrument)).all()
    ) + list(db.scalars(select(SectorScore)).all()):
        sid, _ = resolve_sector_id(getattr(row, "sector_id", None) or getattr(row, "sector", "") or "")
        if not sid:
            # try sector label alone
            sid, _ = resolve_sector_id(getattr(row, "sector", "") or "")
        if sid and getattr(row, "sector_id", None) != sid:
            row.sector_id = sid
            n += 1
        if sid and hasattr(row, "sector") and (not row.sector or normalize_sector(row.sector) == sid):
            if row.sector != sid:
                row.sector = sid
                n += 1
    return n


def repair_catalog_sectors(db: Session) -> int:
    """Force instrument sector/sector_id from SECTOR_CATALOG (fixes HEALTHCARE→PHARMA drift)."""
    n = 0
    for sector, rows in SECTOR_CATALOG.items():
        sid = normalize_sector(sector) or sector
        for spec in rows:
            inst = find_instrument(
                db,
                asset_class=spec.get("asset_class"),
                isin=spec.get("isin"),
                amfi_code=spec.get("amfi_code"),
                nse_symbol=spec.get("nse_symbol"),
            )
            if not inst:
                upsert_instrument(
                    db,
                    asset_class=spec["asset_class"],
                    display_name=spec.get("display_name") or "",
                    sector=sid,
                    isin=spec.get("isin"),
                    amfi_code=spec.get("amfi_code"),
                    nse_symbol=spec.get("nse_symbol"),
                )
                n += 1
                continue
            if inst.sector != sid or inst.sector_id != sid:
                inst.sector = sid
                inst.sector_id = sid
                n += 1
            if spec.get("display_name") and (
                not inst.display_name or len(spec["display_name"]) > len(inst.display_name or "")
            ):
                inst.display_name = spec["display_name"]
    return n


def merge_duplicate_open_holdings(db: Session) -> List[Dict[str, Any]]:
    """
    Close duplicate open holdings that share instrument_id or the same ISIN-like external_key.

    Prefer etf > mf > stock. Do NOT sum market values (Groww often lists the same
    position twice under stock+etf). Keep the preferred row's quantities; close others.
    """
    closed: List[Dict[str, Any]] = []
    opens = [h for h in db.scalars(select(Holding).where(Holding.status != "closed")).all()]

    def _pref(h: Holding) -> tuple:
        order = {"etf": 0, "mf": 1, "stock": 2}.get(h.asset_class, 9)
        return (order, -(h.market_value or 0), h.id)

    # Group by instrument_id
    by_iid: Dict[str, List[Holding]] = {}
    for h in opens:
        if h.instrument_id:
            by_iid.setdefault(h.instrument_id, []).append(h)

    for iid, rows in by_iid.items():
        if len(rows) < 2:
            continue
        rows_sorted = sorted(rows, key=_pref)
        keep = rows_sorted[0]
        for dup in rows_sorted[1:]:
            dup.status = "closed"
            dup.closed_at = date.today()
            dup.missing_from_sync = False
            dup.reason = (
                (dup.reason + " | " if dup.reason else "")
                + f"Closed as duplicate of {keep.id} ({keep.asset_class}:{keep.instrument})"
            ).strip(" |")
            closed.append(
                {
                    "closed_id": dup.id,
                    "kept_id": keep.id,
                    "instrument": dup.instrument,
                    "reason": "same_instrument_id",
                }
            )

    # Group by ISIN-like external_key across asset classes (still-open only)
    opens = [h for h in db.scalars(select(Holding).where(Holding.status != "closed")).all()]
    by_key: Dict[str, List[Holding]] = {}
    for h in opens:
        key = (h.external_key or h.scheme_code or "").strip().upper()
        if len(key) >= 10 and (key.startswith("INF") or (len(key) == 12 and key[:3].isalpha())):
            by_key.setdefault(key, []).append(h)

    for key, rows in by_key.items():
        if len(rows) < 2:
            continue
        rows_sorted = sorted(rows, key=_pref)
        keep = rows_sorted[0]
        # Align instrument_id
        if keep.instrument_id:
            for r in rows_sorted:
                if r.instrument_id != keep.instrument_id:
                    r.instrument_id = keep.instrument_id
        for dup in rows_sorted[1:]:
            if dup.status == "closed":
                continue
            dup.status = "closed"
            dup.closed_at = date.today()
            dup.missing_from_sync = False
            dup.reason = (
                (dup.reason + " | " if dup.reason else "")
                + f"Closed as duplicate ISIN {key} of {keep.id} ({keep.asset_class})"
            ).strip(" |")
            closed.append(
                {
                    "closed_id": dup.id,
                    "kept_id": keep.id,
                    "instrument": dup.instrument,
                    "reason": "same_isin",
                }
            )

    return closed


def align_holding_sectors_from_instruments(db: Session) -> int:
    """If holding has instrument with sector_id, prefer that when holding sector empty/wrong."""
    n = 0
    for h in db.scalars(select(Holding)).all():
        if not h.instrument_id:
            continue
        inst = db.get(Instrument, h.instrument_id)
        if not inst or not (inst.sector_id or inst.sector):
            continue
        want = inst.sector_id or normalize_sector(inst.sector)
        if not want:
            continue
        if h.sector_id != want or normalize_sector(h.sector or "") != want:
            # Only overwrite if holding sector empty or equivalent mismatch noise
            from backend.decision.sectors import equivalent_ids

            cur = h.sector_id or normalize_sector(h.sector or "")
            if not cur or want in equivalent_ids(cur) or cur in equivalent_ids(want) or not h.sector:
                h.sector = want
                h.sector_id = want
                n += 1
    return n


def run_data_migrations(db: Session) -> Dict[str, Any]:
    """Idempotent repairs. Safe to run on every init_db."""
    catalog_n = repair_catalog_sectors(db)
    sid_n = repair_sector_ids(db)
    align_n = align_holding_sectors_from_instruments(db)
    closed = merge_duplicate_open_holdings(db)
    db.commit()
    summary = {
        "catalog_sector_fixes": catalog_n,
        "sector_id_fixes": sid_n,
        "holding_sector_align": align_n,
        "duplicates_closed": closed,
    }
    logger.info("Decision OS data migration: %s", summary)
    return summary
