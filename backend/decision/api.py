"""FastAPI router for Pulse Decision OS."""

from __future__ import annotations

import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.decision.db import get_db, init_db
from backend.decision.decisions import accept_decisions
from backend.decision.diff import build_diff
from backend.decision.holdings import (
    get_holding,
    holding_to_dict,
    list_holdings,
    migrate_from_legacy_ledger,
    update_holding_plan,
)
from backend.decision.runs import get_latest_run, get_run, list_runs, persist_run_from_pipeline, run_to_dict
from backend.decision.sync import portfolio_summary, sync_mf_xlsx, sync_stocks

router = APIRouter(prefix="/api/decide", tags=["decide"])


class PlanUpdate(BaseModel):
    hold_until: Optional[str] = None
    reason: Optional[str] = None
    sector: Optional[str] = None
    status: Optional[str] = None


class DecisionItem(BaseModel):
    holding_id: Optional[str] = None
    sector: str = ""
    instrument: str = ""
    action: str = Field(description="keep|sell|buy|extend")
    hold_until: Optional[str] = None
    note: str = ""


class AcceptBody(BaseModel):
    run_id: str
    decisions: List[DecisionItem]


@router.get("/health")
def decide_health():
    return {"ok": True, "service": "decision-os"}


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    return portfolio_summary(db)


@router.get("/runs")
def runs(db: Session = Depends(get_db), limit: int = 20):
    return {"runs": [run_to_dict(r) for r in list_runs(db, limit)]}


@router.get("/runs/latest")
def latest_run(db: Session = Depends(get_db)):
    run = get_latest_run(db)
    if not run:
        return {"run": None}
    return {"run": run_to_dict(run)}


@router.get("/runs/{run_id}")
def one_run(run_id: str, db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return {"run": run_to_dict(run)}


@router.post("/runs/from-cache")
def persist_cached_run(db: Session = Depends(get_db)):
    """Save current pipeline cache as an immutable analysis run."""
    from backend.data.cache_manager import CacheManager

    results = CacheManager().get("pipeline_results")
    if not results or not results.get("summary"):
        raise HTTPException(404, "No pipeline results in cache — run analysis first")
    run = persist_run_from_pipeline(db, results)
    return {"run": run_to_dict(run)}


@router.get("/latest")
def decide_latest(db: Session = Depends(get_db)):
    """Holdings × latest run → proposals (the main Analyse payload)."""
    return build_diff(db)


@router.get("/sectors")
def sectors_registry():
    """Inspectable canonical sector id → aliases map."""
    from backend.decision.sectors import sector_registry_export

    return {"sectors": sector_registry_export()}


@router.get("/calibration")
def calibration(db: Session = Depends(get_db)):
    from backend.decision.calibration import build_calibration

    return build_calibration(db)


@router.get("/holdings")
def holdings(db: Session = Depends(get_db), include_closed: bool = False):
    rows = list_holdings(db, include_closed=include_closed)
    return {
        "holdings": [holding_to_dict(h) for h in rows],
        "summary": portfolio_summary(db),
    }


@router.get("/holdings/{holding_id}")
def holding_detail(holding_id: str, db: Session = Depends(get_db)):
    h = get_holding(db, holding_id)
    if not h:
        raise HTTPException(404, "Holding not found")
    return holding_to_dict(h)


@router.patch("/holdings/{holding_id}")
def patch_holding(holding_id: str, body: PlanUpdate, db: Session = Depends(get_db)):
    until = date.fromisoformat(body.hold_until[:10]) if body.hold_until else None
    h = update_holding_plan(
        db,
        holding_id,
        hold_until=until,
        reason=body.reason,
        sector=body.sector,
        status=body.status,
    )
    if not h:
        raise HTTPException(404, "Holding not found")
    db.commit()
    return holding_to_dict(h)


@router.post("/accept")
def accept(body: AcceptBody, db: Session = Depends(get_db)):
    if not get_run(db, body.run_id):
        raise HTTPException(404, "Run not found")
    result = accept_decisions(db, body.run_id, [d.model_dump() for d in body.decisions])
    return result


@router.post("/sync/stocks")
def sync_stocks_ep(db: Session = Depends(get_db)):
    try:
        return sync_stocks(db)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/sync/mf")
async def sync_mf_ep(file: UploadFile = File(...), db: Session = Depends(get_db)):
    suffix = Path(file.filename or "holdings.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        path = Path(tmp.name)
    try:
        return sync_mf_xlsx(db, path)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        path.unlink(missing_ok=True)


@router.post("/migrate-legacy")
def migrate_legacy(db: Session = Depends(get_db)):
    return migrate_from_legacy_ledger(db)
