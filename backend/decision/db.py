"""SQLAlchemy engine / session for Pulse Decision OS."""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import DATA_DIR

logger = logging.getLogger(__name__)

DECISION_DB_PATH = DATA_DIR / "pulse_decision.db"
DATABASE_URL = f"sqlite:///{DECISION_DB_PATH}"


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragma(dbapi_conn, _connection_record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _add_column_if_missing(conn, table: str, column: str, ddl: str) -> None:
    cols = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}
    if cols and column not in cols:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
        logger.info("Added %s.%s", table, column)


def _ensure_sqlite_columns() -> None:
    """Add columns introduced after initial create_all (SQLite has no ALTER IF)."""
    with engine.begin() as conn:
        _add_column_if_missing(conn, "holdings", "instrument_id", "instrument_id VARCHAR(32)")
        _add_column_if_missing(conn, "holdings", "sector_id", "sector_id VARCHAR(32)")
        _add_column_if_missing(
            conn, "analysis_sector_scores", "sector_id", "sector_id VARCHAR(32)"
        )
        _add_column_if_missing(conn, "instruments", "sector_id", "sector_id VARCHAR(32)")


def _backfill_sector_ids() -> None:
    from sqlalchemy import select

    from backend.decision.models import Holding, Instrument, SectorScore
    from backend.decision.sectors import normalize_sector

    with SessionLocal() as db:
        n = 0
        for row in list(db.scalars(select(Holding)).all()) + list(
            db.scalars(select(Instrument)).all()
        ) + list(db.scalars(select(SectorScore)).all()):
            sid = normalize_sector(getattr(row, "sector", "") or "")
            if sid and getattr(row, "sector_id", None) != sid:
                row.sector_id = sid
                n += 1
            elif sid and not getattr(row, "sector_id", None):
                row.sector_id = sid
                n += 1
        db.commit()
        logger.info("Backfilled sector_id on %s rows", n)


def init_db() -> None:
    from backend.decision import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns()
    try:
        _backfill_sector_ids()
    except Exception as exc:
        logger.warning("sector_id backfill skipped: %s", exc)
    try:
        from backend.decision.instruments import (
            backfill_holding_instruments,
            merge_duplicate_instruments,
            seed_catalog,
        )

        with SessionLocal() as db:
            seeded = seed_catalog(db)
            linked = backfill_holding_instruments(db)
            merged = merge_duplicate_instruments(db)
            logger.info(
                "Instruments catalog seed=%s backfill=%s merge=%s", seeded, linked, merged
            )
    except Exception as exc:
        logger.warning("Instrument seed/backfill skipped: %s", exc)
    try:
        from backend.decision.migrate_data import run_data_migrations

        with SessionLocal() as db:
            summary = run_data_migrations(db)
            logger.info("Data migrations: %s", summary)
    except Exception as exc:
        logger.warning("Data migrations skipped: %s", exc)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
