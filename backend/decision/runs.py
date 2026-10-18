"""Persist analysis runs and query them."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.decision.helpers import parse_hold_months
from backend.decision.models import AnalysisRun, SectorScore
from backend.decision.recommend import is_sticky_recommended
from backend.decision.sectors import normalize_sector
from backend.decision.thresholds import EXIT_SCORE, is_buy_like_rating

logger = logging.getLogger(__name__)


def persist_run_from_pipeline(db: Session, results: Dict[str, Any]) -> AnalysisRun:
    """Append an immutable analysis run from pipeline results dict."""
    run_id = str(uuid.uuid4())[:12]
    summary = results.get("summary") or []
    run = AnalysisRun(
        id=run_id,
        ran_at=datetime.now(),
        phase=results.get("current_phase") or "",
        sub_phase=results.get("sub_phase") or "",
        progress=float(results.get("phase_progress") or 0),
        market_story=results.get("market_story") or "",
        risk_label=results.get("risk_label") or "",
        payload_json=json.dumps(
            {
                "fund_picks": results.get("fund_picks") or {},
                "recommendations": results.get("recommendations") or [],
                "top_sectors": results.get("top_sectors") or [],
                "investments": results.get("investments") or [],
                "exit_watch": results.get("exit_watch") or [],
                "sub_phase_desc": results.get("sub_phase_desc") or "",
                "methodology_note": results.get("methodology_note") or "",
                "summary": summary,
                "last_run": results.get("_last_run"),
            }
        ),
    )
    db.add(run)

    for rank, row in enumerate(summary):
        hold_for = row.get("hold_for") or "6-9 months"
        lo, hi = parse_hold_months(str(hold_for))
        raw_sector = row.get("sector") or ""
        sid = normalize_sector(raw_sector) or raw_sector
        db.add(
            SectorScore(
                run_id=run_id,
                sector=sid or (row.get("sector") or ""),
                sector_id=sid or None,
                score=float(row.get("score") or 0),
                rating=row.get("rating") or "",
                hold_months_lo=lo,
                hold_months_hi=hi,
                stop_loss_pct=float(row.get("stop_loss_pct") or 12),
                exit_triggers=row.get("exit_trigger") or "",
                rank=rank,
            )
        )
    db.commit()
    db.refresh(run)
    logger.info("Persisted analysis run %s (%s sectors)", run_id, len(summary))
    return run


def get_latest_run(db: Session) -> Optional[AnalysisRun]:
    return db.scalars(select(AnalysisRun).order_by(AnalysisRun.ran_at.desc()).limit(1)).first()


def get_run(db: Session, run_id: str) -> Optional[AnalysisRun]:
    return db.get(AnalysisRun, run_id)


def list_runs(db: Session, limit: int = 20) -> List[AnalysisRun]:
    return list(
        db.scalars(select(AnalysisRun).order_by(AnalysisRun.ran_at.desc()).limit(limit)).all()
    )


def run_to_dict(run: AnalysisRun) -> Dict[str, Any]:
    sectors = sorted(run.sectors, key=lambda s: s.rank)
    try:
        payload = json.loads(run.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    summary_by_sector = {
        str(row.get("sector") or ""): row
        for row in (payload.get("summary") or [])
        if isinstance(row, dict)
    }
    sector_rows = []
    for s in sectors:
        extra = summary_by_sector.get(s.sector) or {}
        if "recommended" in extra:
            recommended = bool(extra.get("recommended"))
        else:
            recommended = is_sticky_recommended(
                float(s.score),
                rating=s.rating or "",
                prev_scores=None,
                was_recommended=False,
            ) or (
                is_buy_like_rating(s.rating or "")
                or float(s.score) >= EXIT_SCORE + 5
            )
        sector_rows.append(
            {
                "sector": s.sector,
                "sector_id": s.sector_id or normalize_sector(s.sector) or s.sector,
                "score": s.score,
                "rating": s.rating or extra.get("rating") or "",
                "hold_months_lo": s.hold_months_lo,
                "hold_months_hi": s.hold_months_hi,
                "hold_for": extra.get("hold_for")
                or f"{s.hold_months_lo:.0f}–{s.hold_months_hi:.0f} months",
                "stop_loss_pct": s.stop_loss_pct,
                "exit_triggers": s.exit_triggers,
                "rank": s.rank,
                "why": extra.get("why") or "",
                "recommended": recommended,
                "recent": extra.get("recent"),
                "sticky": extra.get("sticky"),
            }
        )
    return {
        "id": run.id,
        "ran_at": run.ran_at.isoformat() if run.ran_at else None,
        "phase": run.phase,
        "sub_phase": run.sub_phase,
        "sub_phase_desc": payload.get("sub_phase_desc") or "",
        "methodology_note": payload.get("methodology_note") or "",
        "progress": run.progress,
        "market_story": run.market_story,
        "risk_label": run.risk_label,
        "sectors": sector_rows,
        "fund_picks": payload.get("fund_picks") or {},
        "recommendations": payload.get("recommendations") or [],
        "top_sectors": payload.get("top_sectors") or [],
        "investments": payload.get("investments") or [],
        "exit_watch": payload.get("exit_watch") or [],
        "last_run": payload.get("last_run"),
    }
