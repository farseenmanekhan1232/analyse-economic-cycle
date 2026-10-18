"""Sync stocks from Groww API + MFs from XLSX; accumulate day orders."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.decision.helpers import normalize_sector
from backend.decision.holdings import (
    append_order,
    get_sync_meta,
    list_holdings,
    mark_missing_not_in_keys,
    set_sync_meta,
    upsert_holding,
)
from backend.portfolio.import_groww import parse_mf_holdings, resolve_amfi_code

logger = logging.getLogger(__name__)


def sync_stocks(db: Session) -> Dict[str, Any]:
    from backend.data.groww_client import GrowwClient

    client = GrowwClient()
    if not client.configured:
        raise RuntimeError("Groww not configured (GROWW_API_KEY / SECRET)")

    holdings = client.fetch_holdings()
    keys = set()
    updated = []
    for h in holdings:
        symbol = h["instrument"]
        isin = h.get("scheme_code") or symbol
        key = isin or symbol
        keys.add(key)
        asset = h.get("asset_class") or "stock"
        row = upsert_holding(
            db,
            instrument=symbol,
            asset_class=asset,
            external_key=key,
            units=float(h["units"]),
            invested_amount=float(h["invested_amount"]),
            last_price=float(h.get("last_nav") or h.get("avg_cost") or 0),
            market_value=float(h["units"]) * float(h.get("last_nav") or h.get("avg_cost") or 0),
            sector=normalize_sector(h.get("sector") or symbol),
            scheme_code=isin,
            avg_cost=float(h.get("avg_cost") or 0),
            preserve_plan=True,
        )
        updated.append(row.id)

    missing = mark_missing_not_in_keys(db, "stock", keys)
    missing += mark_missing_not_in_keys(db, "etf", keys)

    # Day orders
    orders_synced = 0
    try:
        import httpx
        from backend.data.groww_client import GROWW_API_BASE

        token = client.ensure_access_token()
        with httpx.Client(timeout=30.0, base_url=GROWW_API_BASE) as http:
            r = http.get(
                "/v1/order/list",
                params={"segment": "CASH", "page": 0, "page_size": 100},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "X-API-VERSION": "1.0",
                },
            )
            if r.status_code < 400:
                data = r.json()
                payload = data.get("payload") or data
                for o in payload.get("order_list") or []:
                    append_order(db, o)
                    orders_synced += 1
    except Exception as exc:
        logger.warning("Order list sync skipped: %s", exc)

    set_sync_meta(db, stocks=True)
    db.commit()
    return {
        "updated": len(updated),
        "missing_flagged": missing,
        "orders_logged": orders_synced,
        "sync": get_sync_meta(db),
    }


def sync_mf_xlsx(db: Session, path: Path) -> Dict[str, Any]:
    rows, _as_of = parse_mf_holdings(path)
    keys = set()
    updated = []
    for row in rows:
        code = resolve_amfi_code(row["instrument"]) or row["instrument"]
        # WhiteOak fallback
        if "whiteoak" in row["instrument"].lower() and "pharma" in row["instrument"].lower():
            code = "INF03VN01886"
        keys.add(str(code))
        nav = float(row.get("last_nav") or 0)
        h = upsert_holding(
            db,
            instrument=row["instrument"],
            asset_class="mf",
            external_key=str(code),
            units=float(row["units"]),
            invested_amount=float(row["invested_amount"]),
            last_price=nav,
            market_value=float(row.get("market_value") or 0),
            sector=row.get("sector") or "",
            scheme_code=str(code) if str(code).isdigit() or str(code).startswith("INF") else None,
            avg_cost=float(row.get("avg_cost") or 0),
            preserve_plan=True,
        )
        updated.append(h.id)
    missing = mark_missing_not_in_keys(db, "mf", keys)
    set_sync_meta(db, mf=True)
    db.commit()
    return {
        "updated": len(updated),
        "missing_flagged": missing,
        "sync": get_sync_meta(db),
        "holding_ids": updated,
    }


def portfolio_summary(db: Session) -> Dict[str, Any]:
    holdings = list_holdings(db)
    invested = sum(h.invested_amount for h in holdings)
    value = sum(h.market_value for h in holdings)
    return {
        "position_count": len(holdings),
        "total_invested": round(invested, 2),
        "total_value": round(value, 2),
        "pnl": round(value - invested, 2),
        "pnl_pct": round((value - invested) / invested * 100, 2) if invested else 0,
        "due_count": sum(1 for h in holdings if h.status in ("due", "overdue")),
        "needs_plan_count": sum(1 for h in holdings if h.needs_plan),
        "sync": get_sync_meta(db),
    }
