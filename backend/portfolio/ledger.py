"""Investment ledger: positions, SIPs, transactions, reviews, snapshots."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import DB_PATH

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("open", "watch", "exit_due", "thesis_broken")


class InvestmentLedger:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DB_PATH
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    id TEXT PRIMARY KEY,
                    instrument TEXT NOT NULL,
                    asset_class TEXT NOT NULL DEFAULT 'mf',
                    scheme_code TEXT,
                    sector TEXT DEFAULT '',
                    sleeve TEXT NOT NULL DEFAULT 'satellite',
                    units REAL NOT NULL DEFAULT 0,
                    avg_cost REAL NOT NULL DEFAULT 0,
                    invested_amount REAL NOT NULL DEFAULT 0,
                    entry_date TEXT,
                    thesis TEXT DEFAULT '',
                    analysis_run_id TEXT,
                    horizon_months_lo INTEGER DEFAULT 6,
                    horizon_months_hi INTEGER DEFAULT 9,
                    target_return_pct REAL,
                    benchmark TEXT DEFAULT 'Nifty 50',
                    review_date TEXT,
                    exit_by_date TEXT,
                    stop_loss_pct REAL DEFAULT 12,
                    take_profit_pct REAL,
                    thesis_invalid_if TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    last_nav REAL,
                    last_nav_date TEXT,
                    market_value REAL,
                    notes TEXT DEFAULT '',
                    outcome_tags TEXT DEFAULT '',
                    closed_at TEXT,
                    closed_nav REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sips (
                    id TEXT PRIMARY KEY,
                    position_id TEXT NOT NULL,
                    amount REAL NOT NULL,
                    sip_day INTEGER NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    last_credited_date TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (position_id) REFERENCES positions(id)
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id TEXT PRIMARY KEY,
                    position_id TEXT NOT NULL,
                    tx_type TEXT NOT NULL,
                    tx_date TEXT NOT NULL,
                    amount REAL,
                    units REAL,
                    nav REAL,
                    note TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (position_id) REFERENCES positions(id)
                );

                CREATE TABLE IF NOT EXISTS review_sessions (
                    id TEXT PRIMARY KEY,
                    review_date TEXT NOT NULL,
                    cycle_phase TEXT DEFAULT '',
                    cycle_sub_phase TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    action_checklist TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS review_decisions (
                    id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL,
                    position_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT DEFAULT '',
                    FOREIGN KEY (review_id) REFERENCES review_sessions(id),
                    FOREIGN KEY (position_id) REFERENCES positions(id)
                );

                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id TEXT PRIMARY KEY,
                    snapshot_date TEXT NOT NULL,
                    total_invested REAL NOT NULL,
                    total_value REAL NOT NULL,
                    core_value REAL NOT NULL,
                    satellite_value REAL NOT NULL,
                    details_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS groww_credentials (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    api_key TEXT,
                    access_token TEXT,
                    token_expires_at TEXT,
                    last_sync_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
                CREATE INDEX IF NOT EXISTS idx_sips_position ON sips(position_id);
                CREATE INDEX IF NOT EXISTS idx_tx_position ON transactions(position_id);
                """
            )
            conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def _row(r: sqlite3.Row) -> Dict[str, Any]:
        return dict(r) if r else {}

    # ── Positions ──────────────────────────────────────────

    def create_position(self, data: Dict[str, Any]) -> Dict[str, Any]:
        pid = data.get("id") or str(uuid.uuid4())[:10]
        now = self._now()
        units = float(data.get("units") or 0)
        invested = float(data.get("invested_amount") or 0)
        avg_cost = float(data.get("avg_cost") or (invested / units if units else 0))
        entry_date = data.get("entry_date") or date.today().isoformat()

        horizon_hi = int(data.get("horizon_months_hi") or 9)
        exit_by = data.get("exit_by_date")
        if not exit_by:
            exit_by = (date.fromisoformat(entry_date) + timedelta(days=horizon_hi * 30)).isoformat()
        review_date = data.get("review_date") or (date.today() + timedelta(days=30)).isoformat()

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO positions (
                    id, instrument, asset_class, scheme_code, sector, sleeve,
                    units, avg_cost, invested_amount, entry_date, thesis, analysis_run_id,
                    horizon_months_lo, horizon_months_hi, target_return_pct, benchmark,
                    review_date, exit_by_date, stop_loss_pct, take_profit_pct, thesis_invalid_if,
                    status, last_nav, last_nav_date, market_value, notes,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid,
                    data["instrument"],
                    data.get("asset_class", "mf"),
                    data.get("scheme_code"),
                    data.get("sector", ""),
                    data.get("sleeve", "satellite"),
                    units,
                    avg_cost,
                    invested,
                    entry_date,
                    data.get("thesis", ""),
                    data.get("analysis_run_id"),
                    int(data.get("horizon_months_lo") or 6),
                    horizon_hi,
                    data.get("target_return_pct"),
                    data.get("benchmark", "Nifty 50"),
                    review_date,
                    exit_by,
                    float(data.get("stop_loss_pct") or 12),
                    data.get("take_profit_pct"),
                    data.get("thesis_invalid_if", ""),
                    data.get("status", "open"),
                    data.get("last_nav") or avg_cost or None,
                    data.get("last_nav_date") or entry_date,
                    units * float(data.get("last_nav") or avg_cost or 0),
                    data.get("notes", ""),
                    now,
                    now,
                ),
            )
            if invested or units:
                conn.execute(
                    """
                    INSERT INTO transactions (id, position_id, tx_type, tx_date, amount, units, nav, note, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        str(uuid.uuid4())[:10],
                        pid,
                        "buy",
                        entry_date,
                        invested,
                        units,
                        avg_cost or None,
                        "Initial entry",
                        now,
                    ),
                )
            conn.commit()
        return self.get_position(pid)

    def update_position(self, position_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        allowed = {
            "instrument", "sector", "sleeve", "thesis", "horizon_months_lo", "horizon_months_hi",
            "target_return_pct", "benchmark", "review_date", "exit_by_date", "stop_loss_pct",
            "take_profit_pct", "thesis_invalid_if", "status", "notes", "scheme_code",
            "outcome_tags", "units", "avg_cost", "invested_amount", "last_nav", "last_nav_date",
            "market_value",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_position(position_id)
        updates["updated_at"] = self._now()
        cols = ", ".join(f"{k}=?" for k in updates)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE positions SET {cols} WHERE id=?",
                (*updates.values(), position_id),
            )
            conn.commit()
        return self.get_position(position_id)

    def get_position(self, position_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
        if not row:
            return None
        pos = self._row(row)
        return self._enrich(pos)

    def list_positions(self, status: Optional[str] = None, include_closed: bool = False) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            if status:
                rows = conn.execute("SELECT * FROM positions WHERE status=? ORDER BY updated_at DESC", (status,)).fetchall()
            elif include_closed:
                rows = conn.execute("SELECT * FROM positions ORDER BY updated_at DESC").fetchall()
            else:
                placeholders = ",".join("?" * len(OPEN_STATUSES))
                rows = conn.execute(
                    f"SELECT * FROM positions WHERE status IN ({placeholders}) ORDER BY exit_by_date ASC",
                    OPEN_STATUSES,
                ).fetchall()
        return [self._enrich(self._row(r)) for r in rows]

    def close_position(
        self,
        position_id: str,
        exit_nav: float,
        outcome_tags: str = "",
        note: str = "",
    ) -> Optional[Dict[str, Any]]:
        pos = self.get_position(position_id)
        if not pos:
            return None
        now = self._now()
        today = date.today().isoformat()
        proceeds = float(pos["units"]) * exit_nav
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE positions SET status='closed', closed_at=?, closed_nav=?, last_nav=?,
                last_nav_date=?, market_value=?, outcome_tags=?, updated_at=?, notes=COALESCE(notes,'') || ?
                WHERE id=?
                """,
                (
                    today,
                    exit_nav,
                    exit_nav,
                    today,
                    proceeds,
                    outcome_tags,
                    now,
                    f"\nClosed: {note}" if note else "",
                    position_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO transactions (id, position_id, tx_type, tx_date, amount, units, nav, note, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(uuid.uuid4())[:10],
                    position_id,
                    "sell",
                    today,
                    proceeds,
                    pos["units"],
                    exit_nav,
                    note or "Closed",
                    now,
                ),
            )
            # deactivate SIPs
            conn.execute("UPDATE sips SET active=0, end_date=? WHERE position_id=?", (today, position_id))
            conn.commit()
        return self.get_position(position_id)

    def _enrich(self, pos: Dict[str, Any]) -> Dict[str, Any]:
        units = float(pos.get("units") or 0)
        invested = float(pos.get("invested_amount") or 0)
        nav = float(pos.get("last_nav") or pos.get("avg_cost") or 0)
        value = float(pos.get("market_value") or (units * nav))
        pnl = value - invested
        pnl_pct = (pnl / invested * 100) if invested else 0.0

        entry = pos.get("entry_date")
        days_held = 0
        if entry:
            try:
                days_held = (date.today() - date.fromisoformat(entry[:10])).days
            except ValueError:
                days_held = 0

        horizon_hi = int(pos.get("horizon_months_hi") or 9)
        horizon_days = max(horizon_hi * 30, 1)
        horizon_progress = min(days_held / horizon_days, 1.0)

        today = date.today()
        exit_by = pos.get("exit_by_date")
        review = pos.get("review_date")
        status = pos.get("status", "open")

        traffic = "green"
        next_action = "Hold"
        if status == "closed":
            traffic = "neutral"
            next_action = "Closed"
        else:
            overdue_exit = False
            due_review = False
            if exit_by:
                try:
                    ed = date.fromisoformat(exit_by[:10])
                    if ed < today:
                        overdue_exit = True
                    elif ed <= today + timedelta(days=7):
                        traffic = "amber"
                        next_action = "Exit soon"
                except ValueError:
                    pass
            if review:
                try:
                    rd = date.fromisoformat(review[:10])
                    if rd <= today:
                        due_review = True
                except ValueError:
                    pass
            if overdue_exit or status == "exit_due":
                traffic = "red"
                next_action = "Square off / decide"
                if status != "closed":
                    pos["status"] = "exit_due"
            elif status == "thesis_broken":
                traffic = "red"
                next_action = "Thesis broken — review"
            elif due_review:
                traffic = "amber" if traffic == "green" else traffic
                next_action = "Monthly review due"
            elif pnl_pct <= -float(pos.get("stop_loss_pct") or 12):
                traffic = "red"
                next_action = "Stop loss hit"

        pos["market_value"] = round(value, 2)
        pos["pnl"] = round(pnl, 2)
        pos["pnl_pct"] = round(pnl_pct, 2)
        pos["days_held"] = days_held
        pos["horizon_progress"] = round(horizon_progress, 2)
        pos["traffic"] = traffic
        pos["next_action"] = next_action
        return pos

    def refresh_status_flags(self, current_sub_phase: str = "") -> None:
        """Mark exit_due / thesis_broken based on dates and phase."""
        positions = self.list_positions()
        today = date.today()
        for pos in positions:
            if pos["status"] == "closed":
                continue
            new_status = pos["status"]
            if pos.get("exit_by_date"):
                try:
                    if date.fromisoformat(pos["exit_by_date"][:10]) < today:
                        new_status = "exit_due"
                except ValueError:
                    pass
            invalid = (pos.get("thesis_invalid_if") or "").strip()
            if invalid and current_sub_phase and invalid in current_sub_phase:
                new_status = "thesis_broken"
            if new_status != pos["status"]:
                self.update_position(pos["id"], {"status": new_status})

    def attention_queue(self, current_sub_phase: str = "") -> List[Dict[str, Any]]:
        self.refresh_status_flags(current_sub_phase)
        items = []
        for pos in self.list_positions():
            if pos["traffic"] in ("red", "amber") or pos["status"] in ("exit_due", "thesis_broken", "watch"):
                items.append(pos)
        items.sort(key=lambda p: (0 if p["traffic"] == "red" else 1, p.get("exit_by_date") or "9999"))
        return items

    # ── SIPs ───────────────────────────────────────────────

    def create_sip(self, position_id: str, amount: float, sip_day: int, start_date: str) -> Dict[str, Any]:
        sid = str(uuid.uuid4())[:10]
        now = self._now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sips (id, position_id, amount, sip_day, start_date, active, created_at)
                VALUES (?,?,?,?,?,1,?)
                """,
                (sid, position_id, amount, sip_day, start_date, now),
            )
            conn.commit()
        return self.get_sip(sid)

    def get_sip(self, sip_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sips WHERE id=?", (sip_id,)).fetchone()
        return self._row(row) if row else None

    def list_sips(self, active_only: bool = True) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            if active_only:
                rows = conn.execute(
                    """
                    SELECT s.*, p.instrument, p.scheme_code, p.sector
                    FROM sips s JOIN positions p ON p.id = s.position_id
                    WHERE s.active=1 ORDER BY s.sip_day
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT s.*, p.instrument, p.scheme_code, p.sector
                    FROM sips s JOIN positions p ON p.id = s.position_id
                    ORDER BY s.sip_day
                    """
                ).fetchall()
        return [self._row(r) for r in rows]

    def deactivate_sip(self, sip_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE sips SET active=0, end_date=? WHERE id=?",
                (date.today().isoformat(), sip_id),
            )
            conn.commit()

    def credit_sip(self, sip_id: str, tx_date: str, nav: float) -> Optional[Dict[str, Any]]:
        sip = self.get_sip(sip_id)
        if not sip or not sip["active"]:
            return None
        amount = float(sip["amount"])
        units = amount / nav if nav else 0
        pos = self.get_position(sip["position_id"])
        if not pos:
            return None
        new_units = float(pos["units"]) + units
        new_invested = float(pos["invested_amount"]) + amount
        new_avg = new_invested / new_units if new_units else 0
        now = self._now()
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE positions SET units=?, invested_amount=?, avg_cost=?, last_nav=?, last_nav_date=?,
                market_value=?, updated_at=? WHERE id=?
                """,
                (new_units, new_invested, new_avg, nav, tx_date, new_units * nav, now, pos["id"]),
            )
            conn.execute(
                """
                INSERT INTO transactions (id, position_id, tx_type, tx_date, amount, units, nav, note, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (str(uuid.uuid4())[:10], pos["id"], "sip", tx_date, amount, units, nav, f"SIP {sip_id}", now),
            )
            conn.execute("UPDATE sips SET last_credited_date=? WHERE id=?", (tx_date, sip_id))
            conn.commit()
        return self.get_position(pos["id"])

    def process_due_sips(self, nav_lookup) -> List[Dict[str, Any]]:
        """Credit SIPs whose sip_day has passed since last_credited. nav_lookup(scheme_code)->nav."""
        credited = []
        today = date.today()
        for sip in self.list_sips(active_only=True):
            start = date.fromisoformat(sip["start_date"][:10])
            if today < start:
                continue
            last = sip.get("last_credited_date")
            # Candidate credit date this month
            try:
                credit_day = min(int(sip["sip_day"]), 28)
                candidate = date(today.year, today.month, credit_day)
            except ValueError:
                continue
            if candidate > today:
                # previous month
                if today.month == 1:
                    candidate = date(today.year - 1, 12, credit_day)
                else:
                    candidate = date(today.year, today.month - 1, credit_day)
            if candidate < start:
                continue
            if last and date.fromisoformat(last[:10]) >= candidate:
                continue
            scheme = sip.get("scheme_code")
            if not scheme:
                logger.warning(f"SIP {sip['id']} missing scheme_code — skip credit")
                continue
            nav = nav_lookup(scheme)
            if not nav or nav <= 0:
                logger.warning(f"No NAV for scheme {scheme}")
                continue
            pos = self.credit_sip(sip["id"], candidate.isoformat(), float(nav))
            if pos:
                credited.append({"sip_id": sip["id"], "position": pos, "date": candidate.isoformat(), "nav": nav})
        return credited

    # ── Transactions ───────────────────────────────────────

    def list_transactions(self, position_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            if position_id:
                rows = conn.execute(
                    "SELECT * FROM transactions WHERE position_id=? ORDER BY tx_date DESC",
                    (position_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM transactions ORDER BY tx_date DESC LIMIT 100").fetchall()
        return [self._row(r) for r in rows]

    def add_lumpsum(self, position_id: str, amount: float, nav: float, tx_date: Optional[str] = None) -> Optional[Dict]:
        pos = self.get_position(position_id)
        if not pos or not nav:
            return None
        tx_date = tx_date or date.today().isoformat()
        units = amount / nav
        new_units = float(pos["units"]) + units
        new_invested = float(pos["invested_amount"]) + amount
        new_avg = new_invested / new_units if new_units else 0
        now = self._now()
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE positions SET units=?, invested_amount=?, avg_cost=?, last_nav=?, last_nav_date=?,
                market_value=?, updated_at=? WHERE id=?
                """,
                (new_units, new_invested, new_avg, nav, tx_date, new_units * nav, now, position_id),
            )
            conn.execute(
                """
                INSERT INTO transactions (id, position_id, tx_type, tx_date, amount, units, nav, note, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (str(uuid.uuid4())[:10], position_id, "buy", tx_date, amount, units, nav, "Lumpsum", now),
            )
            conn.commit()
        return self.get_position(position_id)

    def update_nav(self, position_id: str, nav: float, nav_date: Optional[str] = None) -> Optional[Dict]:
        pos = self.get_position(position_id)
        if not pos:
            return None
        nav_date = nav_date or date.today().isoformat()
        value = float(pos["units"]) * nav
        return self.update_position(
            position_id,
            {"last_nav": nav, "last_nav_date": nav_date, "market_value": value},
        )

    # ── Portfolio aggregates ───────────────────────────────

    def portfolio_summary(self) -> Dict[str, Any]:
        positions = self.list_positions()
        total_invested = sum(float(p["invested_amount"]) for p in positions)
        total_value = sum(float(p["market_value"]) for p in positions)
        core_value = sum(float(p["market_value"]) for p in positions if p.get("sleeve") == "core")
        sat_value = sum(float(p["market_value"]) for p in positions if p.get("sleeve") != "core")
        by_sector: Dict[str, float] = {}
        for p in positions:
            sec = p.get("sector") or "Other"
            by_sector[sec] = by_sector.get(sec, 0) + float(p["market_value"])
        return {
            "total_invested": round(total_invested, 2),
            "total_value": round(total_value, 2),
            "pnl": round(total_value - total_invested, 2),
            "pnl_pct": round((total_value - total_invested) / total_invested * 100, 2) if total_invested else 0,
            "core_value": round(core_value, 2),
            "satellite_value": round(sat_value, 2),
            "core_pct": round(core_value / total_value * 100, 1) if total_value else 0,
            "satellite_pct": round(sat_value / total_value * 100, 1) if total_value else 0,
            "by_sector": {k: round(v, 2) for k, v in sorted(by_sector.items(), key=lambda x: -x[1])},
            "position_count": len(positions),
        }

    def take_snapshot(self) -> Dict[str, Any]:
        summary = self.portfolio_summary()
        sid = str(uuid.uuid4())[:10]
        now = self._now()
        today = date.today().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO portfolio_snapshots
                (id, snapshot_date, total_invested, total_value, core_value, satellite_value, details_json, created_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    sid,
                    today,
                    summary["total_invested"],
                    summary["total_value"],
                    summary["core_value"],
                    summary["satellite_value"],
                    json.dumps(summary.get("by_sector", {})),
                    now,
                ),
            )
            conn.commit()
        summary["id"] = sid
        summary["snapshot_date"] = today
        return summary

    def list_snapshots(self, limit: int = 90) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM portfolio_snapshots ORDER BY snapshot_date ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row(r) for r in rows]

    # ── Reviews ────────────────────────────────────────────

    def create_review(
        self,
        decisions: List[Dict[str, Any]],
        cycle_phase: str = "",
        cycle_sub_phase: str = "",
        notes: str = "",
        action_checklist: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        rid = str(uuid.uuid4())[:10]
        now = self._now()
        today = date.today().isoformat()
        checklist = action_checklist or []
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO review_sessions (id, review_date, cycle_phase, cycle_sub_phase, notes, action_checklist, created_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (rid, today, cycle_phase, cycle_sub_phase, notes, json.dumps(checklist), now),
            )
            for d in decisions:
                conn.execute(
                    """
                    INSERT INTO review_decisions (id, review_id, position_id, decision, reason)
                    VALUES (?,?,?,?,?)
                    """,
                    (str(uuid.uuid4())[:10], rid, d["position_id"], d["decision"], d.get("reason", "")),
                )
                # bump review_date 30 days for keep/trim
                if d["decision"] in ("keep", "trim", "extend"):
                    new_review = (date.today() + timedelta(days=30)).isoformat()
                    fields: Dict[str, Any] = {"review_date": new_review, "status": "open"}
                    if d["decision"] == "extend":
                        pos = self.get_position(d["position_id"])
                        if pos and pos.get("exit_by_date"):
                            try:
                                ed = date.fromisoformat(pos["exit_by_date"][:10]) + timedelta(days=90)
                                fields["exit_by_date"] = ed.isoformat()
                            except ValueError:
                                pass
                    conn.execute(
                        f"UPDATE positions SET {', '.join(k+'=?' for k in fields)}, updated_at=? WHERE id=?",
                        (*fields.values(), now, d["position_id"]),
                    )
            conn.commit()
        return self.get_review(rid)

    def get_review(self, review_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM review_sessions WHERE id=?", (review_id,)).fetchone()
            if not row:
                return None
            decisions = conn.execute(
                "SELECT * FROM review_decisions WHERE review_id=?", (review_id,)
            ).fetchall()
        result = self._row(row)
        result["action_checklist"] = json.loads(result.get("action_checklist") or "[]")
        result["decisions"] = [self._row(d) for d in decisions]
        return result

    def list_reviews(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM review_sessions ORDER BY review_date DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for r in rows:
            item = self._row(r)
            item["action_checklist"] = json.loads(item.get("action_checklist") or "[]")
            out.append(item)
        return out

    def last_review_date(self) -> Optional[str]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT review_date FROM review_sessions ORDER BY review_date DESC LIMIT 1"
            ).fetchone()
        return row["review_date"] if row else None

    # ── Groww credentials ──────────────────────────────────

    def save_groww_token(self, api_key: str, access_token: str, expires_at: Optional[str] = None) -> None:
        now = self._now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO groww_credentials (id, api_key, access_token, token_expires_at, updated_at)
                VALUES (1,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    api_key=excluded.api_key,
                    access_token=excluded.access_token,
                    token_expires_at=excluded.token_expires_at,
                    updated_at=excluded.updated_at
                """,
                (api_key, access_token, expires_at, now),
            )
            conn.commit()

    def get_groww_credentials(self) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM groww_credentials WHERE id=1").fetchone()
        return self._row(row) if row else None

    def mark_groww_synced(self) -> None:
        now = self._now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO groww_credentials (id, last_sync_at, updated_at) VALUES (1,?,?)
                ON CONFLICT(id) DO UPDATE SET last_sync_at=excluded.last_sync_at, updated_at=excluded.updated_at
                """,
                (now, now),
            )
            conn.commit()

    def closed_calibration_stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT outcome_tags, entry_date, closed_at, exit_by_date FROM positions WHERE status='closed'"
            ).fetchall()
        tags: Dict[str, int] = {}
        exited_late = 0
        for r in rows:
            for t in (r["outcome_tags"] or "").split(","):
                t = t.strip()
                if t:
                    tags[t] = tags.get(t, 0) + 1
            if r["exit_by_date"] and r["closed_at"]:
                try:
                    if date.fromisoformat(r["closed_at"][:10]) > date.fromisoformat(r["exit_by_date"][:10]):
                        exited_late += 1
                except ValueError:
                    pass
        return {"total_closed": len(rows), "tags": tags, "exited_late": exited_late}

    def clear_book(self) -> Dict[str, int]:
        """Remove all positions, SIPs, and transactions (for clean re-seed)."""
        with self._conn() as conn:
            n_tx = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            n_sip = conn.execute("SELECT COUNT(*) FROM sips").fetchone()[0]
            n_pos = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM sips")
            conn.execute("DELETE FROM review_decisions")
            conn.execute("DELETE FROM positions")
            conn.commit()
        return {"positions": n_pos, "sips": n_sip, "transactions": n_tx}

