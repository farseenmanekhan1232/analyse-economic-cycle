"""Accept decisions → update holdings + Groww checklist."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.decision.helpers import hold_until_from_months
from backend.decision.holdings import get_holding, update_holding_plan
from backend.decision.models import Decision


def accept_decisions(
    db: Session,
    run_id: str,
    items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    items: [{holding_id?, sector, instrument, action, hold_until?, note?}]
    """
    checklist = []
    saved = []
    for item in items:
        action = (item.get("action") or "keep").lower()
        holding_id = item.get("holding_id") or None
        if holding_id == "":
            holding_id = None
        instrument = item.get("instrument") or ""
        sector = item.get("sector") or ""
        note = item.get("note") or ""
        hold_until_raw = item.get("hold_until")
        hold_until: Optional[date] = None
        if hold_until_raw:
            hold_until = date.fromisoformat(str(hold_until_raw)[:10])

        d = Decision(
            id=str(uuid.uuid4())[:12],
            run_id=run_id,
            holding_id=holding_id,
            sector=sector,
            instrument=instrument,
            action=action,
            hold_until=hold_until,
            note=note,
            accepted=True,
        )
        db.add(d)
        saved.append(d.id)

        if holding_id:
            h = get_holding(db, holding_id)
            if h:
                instrument = instrument or h.instrument
                if action == "sell":
                    checklist.append({"action": "SELL", "instrument": instrument, "note": note})
                    # Don't auto-close until sync confirms — flag reason
                    update_holding_plan(
                        db,
                        holding_id,
                        reason=note or h.reason or "Marked sell on checklist",
                        run_id=run_id,
                    )
                elif action in ("keep", "extend", "review"):
                    until = hold_until or h.hold_until or hold_until_from_months(9)
                    update_holding_plan(
                        db,
                        holding_id,
                        hold_until=until if action != "review" else h.hold_until,
                        reason=note or h.reason,
                        run_id=run_id,
                        sector=item.get("sector") if action == "review" else None,
                    )
                    if action == "extend":
                        checklist.append(
                            {
                                "action": "NOTE",
                                "instrument": instrument,
                                "note": f"Change hold-until to {until.isoformat()}"
                                + (f" — {note}" if note else ""),
                            }
                        )
                    elif action == "review":
                        checklist.append(
                            {
                                "action": "NOTE",
                                "instrument": instrument,
                                "note": note or "Map sector in Holdings — unmapped on this run",
                            }
                        )
                elif action == "buy":
                    checklist.append({"action": "BUY", "instrument": instrument or sector, "note": note})
        else:
            # buy idea without holding
            if action == "buy":
                checklist.append(
                    {
                        "action": "BUY",
                        "instrument": instrument or sector,
                        "note": note or f"New {sector} — hold until {hold_until}",
                    }
                )

    db.commit()
    return {"decision_ids": saved, "checklist": checklist}
