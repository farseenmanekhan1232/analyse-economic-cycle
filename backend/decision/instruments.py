"""Canonical instruments + sector suggestion allowlist.

Identity rule: holdings and suggestions share instrument_id.
Match on isin / amfi_code / nse_symbol — never on display name at runtime.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.decision.helpers import normalize_sector
from backend.decision.models import Holding, Instrument

logger = logging.getLogger(__name__)

# Curated universe: sector → list of identity specs for suggestions.
# Prefer isin / amfi_code; nse_symbol for ETFs/stocks.
SECTOR_CATALOG: Dict[str, List[Dict[str, str]]] = {
    "AUTO": [
        {"asset_class": "etf", "nse_symbol": "AUTOIETF", "display_name": "Nippon India ETF Auto"},
        {"asset_class": "etf", "nse_symbol": "AUTOBEES", "display_name": "Nippon India ETF Nifty Auto"},
    ],
    "PHARMA": [
        {"asset_class": "etf", "nse_symbol": "PHARMABEES", "display_name": "Nippon India ETF Pharma"},
        {"asset_class": "mf", "amfi_code": "149268", "display_name": "ITI Pharma and Healthcare Fund Direct Growth"},
        {
            "asset_class": "mf",
            "isin": "INF03VN01886",
            "display_name": "WhiteOak Capital Pharma and Healthcare Fund Direct Growth",
        },
    ],
    "HEALTHCARE": [
        {"asset_class": "etf", "nse_symbol": "HEALTHIETF", "display_name": "ICICI Pru Nifty Healthcare ETF"},
        {"asset_class": "etf", "nse_symbol": "MOHEALTH", "display_name": "Motilal Oswal Nifty Healthcare ETF"},
    ],
    "ENERGY": [
        {"asset_class": "etf", "nse_symbol": "MOENERGY", "display_name": "Motilal Oswal Nifty Energy ETF"},
        {"asset_class": "etf", "nse_symbol": "ENERGY", "display_name": "Nippon India ETF Energy"},
        {
            "asset_class": "mf",
            "amfi_code": "152728",
            "display_name": "ICICI Prudential Energy Opportunities Fund Direct Growth",
        },
        {
            "asset_class": "mf",
            "amfi_code": "119028",
            "display_name": "DSP Natural Resources and New Energy Fund Direct Plan Growth",
        },
    ],
    "REALTY": [
        {
            "asset_class": "etf",
            "nse_symbol": "MOREALTY",
            "isin": "INF247L01CI4",
            "display_name": "Motilal Oswal Nifty Realty ETF",
        },
    ],
    "METAL": [
        {"asset_class": "etf", "nse_symbol": "METALIETF", "display_name": "ICICI Pru Nifty Metal ETF"},
        {"asset_class": "etf", "nse_symbol": "GROWWMETAL", "display_name": "Groww Nifty Metal ETF"},
        {
            "asset_class": "mf",
            "amfi_code": "147662",
            "display_name": "ICICI Prudential Commodities Fund Direct Growth",
        },
    ],
    "FMCG": [
        {"asset_class": "etf", "nse_symbol": "FMCGIETF", "display_name": "ICICI Pru Nifty FMCG ETF"},
    ],
    "BANK": [
        {"asset_class": "etf", "nse_symbol": "BANKBEES", "display_name": "Nippon India ETF Bank BeES"},
        {"asset_class": "etf", "nse_symbol": "BANKIETF", "display_name": "ICICI Pru Nifty Bank ETF"},
    ],
    "IT": [
        {"asset_class": "etf", "nse_symbol": "ITBEES", "display_name": "Nippon India ETF Nifty IT"},
        {"asset_class": "etf", "nse_symbol": "SBIETFIT", "display_name": "SBI Nifty IT ETF"},
    ],
    "INFRA": [
        {"asset_class": "etf", "nse_symbol": "INFRABEES", "display_name": "Nippon India ETF Infra BeES"},
        {"asset_class": "etf", "nse_symbol": "MOINFRA", "display_name": "Motilal Oswal Nifty Infra ETF"},
    ],
    "OIL_GAS": [
        {"asset_class": "etf", "nse_symbol": "OILIETF", "display_name": "ICICI Pru Nifty Oil & Gas ETF"},
    ],
    "PSU_BANK": [
        {"asset_class": "etf", "nse_symbol": "PSUBNKBEES", "display_name": "Nippon India ETF PSU Bank BeES"},
    ],
    "CONSUMER_DURABLES": [
        {"asset_class": "etf", "nse_symbol": "CONSUMBEES", "display_name": "Nippon India ETF Consumption"},
    ],
}

# Placeholder codes that are not real — strip before seed
_PLACEHOLDER_AMFI = {"152XXX_SBI_AUTO"}


def _clean_id(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in _PLACEHOLDER_AMFI:
        return None
    return s


def instrument_to_dict(inst: Instrument) -> Dict[str, Any]:
    return {
        "id": inst.id,
        "asset_class": inst.asset_class,
        "display_name": inst.display_name,
        "sector": inst.sector,
        "sector_id": inst.sector_id,
        "isin": inst.isin,
        "amfi_code": inst.amfi_code,
        "nse_symbol": inst.nse_symbol,
        "needs_id_review": inst.needs_id_review,
    }


def find_instrument(
    db: Session,
    *,
    asset_class: Optional[str] = None,
    isin: Optional[str] = None,
    amfi_code: Optional[str] = None,
    nse_symbol: Optional[str] = None,
) -> Optional[Instrument]:
    isin = _clean_id(isin)
    amfi_code = _clean_id(amfi_code)
    nse_symbol = _clean_id(nse_symbol)
    if nse_symbol:
        nse_symbol = nse_symbol.upper()

    # ISIN / AMFI are globally unique — ignore asset_class for those lookups
    if isin:
        hit = db.scalars(select(Instrument).where(Instrument.isin == isin)).first()
        if hit:
            return hit
    if amfi_code:
        hit = db.scalars(select(Instrument).where(Instrument.amfi_code == amfi_code)).first()
        if hit:
            return hit
    if nse_symbol:
        q = select(Instrument).where(Instrument.nse_symbol == nse_symbol)
        if asset_class:
            q = q.where(Instrument.asset_class == asset_class)
        hit = db.scalars(q).first()
        if hit:
            return hit
        # symbol without class (ETF vs stock mis-tag)
        return db.scalars(select(Instrument).where(Instrument.nse_symbol == nse_symbol)).first()
    return None


def upsert_instrument(
    db: Session,
    *,
    asset_class: str,
    display_name: str,
    sector: str = "",
    isin: Optional[str] = None,
    amfi_code: Optional[str] = None,
    nse_symbol: Optional[str] = None,
    kite_tradingsymbol: Optional[str] = None,
    needs_id_review: bool = False,
) -> Instrument:
    isin = _clean_id(isin)
    amfi_code = _clean_id(amfi_code)
    nse_symbol = _clean_id(nse_symbol)
    if nse_symbol:
        nse_symbol = nse_symbol.upper()

    # Prefer strongest id first; if ISIN is new but ticker already in catalog, reuse catalog row.
    existing = find_instrument(
        db,
        asset_class=asset_class,
        isin=isin,
        amfi_code=amfi_code,
        nse_symbol=None,
    )
    if existing is None and nse_symbol:
        existing = find_instrument(
            db,
            asset_class=asset_class,
            nse_symbol=nse_symbol,
        )
    sector_n = normalize_sector(sector) or sector
    if existing:
        if display_name and (
            not existing.display_name or len(display_name) > len(existing.display_name or "")
        ):
            existing.display_name = display_name
        if sector_n:
            # Catalog / explicit sector wins over stale labels
            existing.sector = sector_n
            existing.sector_id = normalize_sector(sector_n) or existing.sector_id
        if isin and not existing.isin:
            existing.isin = isin
        if amfi_code and not existing.amfi_code:
            existing.amfi_code = amfi_code
        if nse_symbol and not existing.nse_symbol:
            existing.nse_symbol = nse_symbol
        if kite_tradingsymbol and not existing.kite_tradingsymbol:
            existing.kite_tradingsymbol = kite_tradingsymbol
        if isin or amfi_code or nse_symbol:
            existing.needs_id_review = False
        return existing

    has_id = bool(isin or amfi_code or nse_symbol)
    if not has_id:
        logger.warning(
            "Instrument resolve low-confidence: name=%s key class=%s — needs_id_review",
            display_name,
            asset_class,
        )
    inst = Instrument(
        id=str(uuid.uuid4())[:12],
        asset_class=asset_class,
        display_name=display_name or nse_symbol or amfi_code or isin or "Unknown",
        sector=sector_n,
        sector_id=normalize_sector(sector_n) or None,
        isin=isin,
        amfi_code=amfi_code,
        nse_symbol=nse_symbol,
        kite_tradingsymbol=kite_tradingsymbol,
        needs_id_review=needs_id_review or not has_id,
    )
    db.add(inst)
    db.flush()
    return inst


def seed_catalog(db: Session) -> int:
    """Upsert curated sector allowlist into instruments. Returns count touched."""
    n = 0
    for sector, rows in SECTOR_CATALOG.items():
        for spec in rows:
            amfi = _clean_id(spec.get("amfi_code"))
            if spec.get("amfi_code") in _PLACEHOLDER_AMFI:
                continue
            upsert_instrument(
                db,
                asset_class=spec["asset_class"],
                display_name=spec.get("display_name") or "",
                sector=sector,
                isin=spec.get("isin"),
                amfi_code=amfi,
                nse_symbol=spec.get("nse_symbol"),
            )
            n += 1
    db.commit()
    return n


def resolve_for_holding(
    db: Session,
    *,
    asset_class: str,
    instrument_name: str,
    external_key: str = "",
    scheme_code: Optional[str] = None,
    sector: str = "",
) -> Instrument:
    """Attach/create instrument from sync fields (ISIN / AMFI / NSE symbol)."""
    key = (scheme_code or external_key or "").strip()
    isin = None
    amfi = None
    nse = None
    ac = (asset_class or "mf").lower()

    if key.upper().startswith("INF") or (len(key) == 12 and key[:3].isalpha()):
        isin = key.upper()
    elif key.isdigit():
        amfi = key
    elif re.match(r"^[A-Z0-9]{1,20}$", key.upper()) and ac in ("etf", "stock"):
        nse = key.upper()

    # Always try ticker from short ETF/stock names (e.g. MOHEALTH) even when ISIN is present —
    # otherwise sync creates a second instrument that never matches the catalog row.
    if ac in ("etf", "stock") and not nse and instrument_name:
        token = instrument_name.strip().split()[-1]
        if re.match(r"^[A-Za-z0-9]{2,20}$", token):
            nse = token.upper()
        elif re.match(r"^[A-Za-z0-9]{2,20}$", instrument_name.strip()):
            nse = instrument_name.strip().upper()

    return upsert_instrument(
        db,
        asset_class=ac,
        display_name=instrument_name,
        sector=sector,
        isin=isin,
        amfi_code=amfi,
        nse_symbol=nse,
        needs_id_review=not bool(isin or amfi or nse),
    )


def merge_duplicate_instruments(db: Session) -> int:
    """Collapse instruments that share ISIN, AMFI, or NSE symbol; re-point holdings."""
    merged = 0
    by_isin: Dict[str, List[Instrument]] = {}
    by_amfi: Dict[str, List[Instrument]] = {}
    by_nse: Dict[str, List[Instrument]] = {}
    for inst in db.scalars(select(Instrument)).all():
        if inst.isin:
            by_isin.setdefault(inst.isin.upper(), []).append(inst)
        if inst.amfi_code:
            by_amfi.setdefault(inst.amfi_code, []).append(inst)
        nse = (inst.nse_symbol or "").strip().upper()
        if not nse and inst.asset_class in ("etf", "stock"):
            name = (inst.display_name or "").strip()
            if re.match(r"^[A-Za-z0-9]{2,20}$", name):
                nse = name.upper()
        if nse:
            by_nse.setdefault(nse, []).append(inst)

    def _collapse(groups: Dict[str, List[Instrument]]) -> None:
        nonlocal merged
        for _key, rows in groups.items():
            # Unique by id in case same row appears twice
            uniq: Dict[str, Instrument] = {r.id: r for r in rows}
            rows = list(uniq.values())
            if len(rows) < 2:
                continue
            # Prefer etf over stock, then row with nse_symbol / richer name
            rows_sorted = sorted(
                rows,
                key=lambda r: (
                    0 if r.asset_class == "etf" else 1 if r.asset_class == "mf" else 2,
                    0 if r.nse_symbol else 1,
                    0 if r.isin else 1,
                    -len(r.display_name or ""),
                ),
            )
            keep = rows_sorted[0]
            for dup in rows_sorted[1:]:
                for h in db.scalars(select(Holding).where(Holding.instrument_id == dup.id)).all():
                    h.instrument_id = keep.id
                if dup.isin and not keep.isin:
                    keep.isin = dup.isin
                if dup.amfi_code and not keep.amfi_code:
                    keep.amfi_code = dup.amfi_code
                if dup.nse_symbol and not keep.nse_symbol:
                    keep.nse_symbol = dup.nse_symbol
                db.delete(dup)
                merged += 1

    _collapse(by_isin)
    _collapse(by_amfi)
    _collapse(by_nse)
    db.commit()
    return merged


def backfill_holding_instruments(db: Session) -> int:
    """Link holdings to instruments; re-link when ISIN/AMFI already on another row."""
    n = 0
    for h in db.scalars(select(Holding)).all():
        inst = resolve_for_holding(
            db,
            asset_class=h.asset_class,
            instrument_name=h.instrument,
            external_key=h.external_key or "",
            scheme_code=h.scheme_code,
            sector=h.sector or "",
        )
        if h.instrument_id != inst.id:
            h.instrument_id = inst.id
            n += 1
        if inst.sector and not h.sector:
            h.sector = inst.sector
    db.commit()
    merge_duplicate_instruments(db)
    return n


def catalog_for_sectors(db: Session, sectors: List[str]) -> List[Instrument]:
    """Instruments from allowlist sectors (normalized sector_id)."""
    wanted = {normalize_sector(s) or s for s in sectors}
    # Expand PHARMA↔HEALTHCARE
    from backend.decision.sectors import equivalent_ids

    expanded: set = set()
    for w in wanted:
        expanded |= equivalent_ids(w) if w else set()
        if w:
            expanded.add(w)
    rows = list(
        db.scalars(
            select(Instrument).where(
                (Instrument.sector_id.in_(expanded)) | (Instrument.sector.in_(expanded))
            )
        ).all()
    )
    return rows


def etf_symbols_by_sector() -> Dict[str, List[str]]:
    """Derive ETF symbol map from SECTOR_CATALOG (single source with fund recommender)."""
    out: Dict[str, List[str]] = {}
    for sector, rows in SECTOR_CATALOG.items():
        syms = []
        for spec in rows:
            if spec.get("asset_class") == "etf" and spec.get("nse_symbol"):
                syms.append(spec["nse_symbol"].upper())
        out[sector] = syms
    return out
