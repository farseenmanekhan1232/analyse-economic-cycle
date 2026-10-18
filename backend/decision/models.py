"""Decision OS domain models — analysis runs, holdings, decisions, order log."""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.decision.db import Base


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    phase: Mapped[str] = mapped_column(String(64), default="")
    sub_phase: Mapped[str] = mapped_column(String(64), default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    market_story: Mapped[str] = mapped_column(Text, default="")
    risk_label: Mapped[str] = mapped_column(String(128), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")  # extras / fund picks

    sectors: Mapped[List["SectorScore"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    decisions: Mapped[List["Decision"]] = relationship(back_populates="run")


class SectorScore(Base):
    __tablename__ = "analysis_sector_scores"
    __table_args__ = (UniqueConstraint("run_id", "sector", name="uq_run_sector"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    sector: Mapped[str] = mapped_column(String(64), index=True)
    sector_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    rating: Mapped[str] = mapped_column(String(32), default="")
    hold_months_lo: Mapped[float] = mapped_column(Float, default=6.0)
    hold_months_hi: Mapped[float] = mapped_column(Float, default=9.0)
    stop_loss_pct: Mapped[float] = mapped_column(Float, default=12.0)
    exit_triggers: Mapped[str] = mapped_column(Text, default="")  # JSON list or text
    rank: Mapped[int] = mapped_column(Integer, default=999)

    run: Mapped["AnalysisRun"] = relationship(back_populates="sectors")


class Instrument(Base):
    """Canonical tradable identity shared by holdings and suggestions."""

    __tablename__ = "instruments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(16), index=True)  # mf | etf | stock
    display_name: Mapped[str] = mapped_column(String(256), default="")
    sector: Mapped[str] = mapped_column(String(64), default="", index=True)
    sector_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    isin: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    amfi_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    nse_symbol: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    kite_tradingsymbol: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    needs_id_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    holdings: Mapped[List["Holding"]] = relationship(back_populates="instrument_row")


class Holding(Base):
    __tablename__ = "holdings"
    __table_args__ = (
        UniqueConstraint("asset_class", "external_key", name="uq_holding_key"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    instrument: Mapped[str] = mapped_column(String(256))
    asset_class: Mapped[str] = mapped_column(String(16))  # mf | etf | stock
    external_key: Mapped[str] = mapped_column(String(128))  # scheme_code / ISIN / symbol
    scheme_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    instrument_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("instruments.id"), nullable=True, index=True
    )
    sector: Mapped[str] = mapped_column(String(64), default="")
    sector_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    units: Mapped[float] = mapped_column(Float, default=0.0)
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)
    invested_amount: Mapped[float] = mapped_column(Float, default=0.0)
    last_price: Mapped[float] = mapped_column(Float, default=0.0)
    market_value: Mapped[float] = mapped_column(Float, default=0.0)
    hold_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="holding")  # holding|due|overdue|closed
    opened_by_run_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_reviewed_run_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    missing_from_sync: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_plan: Mapped[bool] = mapped_column(Boolean, default=False)  # new from sync
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    closed_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    instrument_row: Mapped[Optional["Instrument"]] = relationship(back_populates="holdings")


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    holding_id: Mapped[Optional[str]] = mapped_column(ForeignKey("holdings.id"), nullable=True)
    sector: Mapped[str] = mapped_column(String(64), default="")
    instrument: Mapped[str] = mapped_column(String(256), default="")
    action: Mapped[str] = mapped_column(String(16))  # keep|sell|buy|extend
    hold_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    run: Mapped["AnalysisRun"] = relationship(back_populates="decisions")


class OrderLog(Base):
    __tablename__ = "order_log"
    __table_args__ = (UniqueConstraint("groww_order_id", name="uq_groww_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    groww_order_id: Mapped[str] = mapped_column(String(64))
    trading_symbol: Mapped[str] = mapped_column(String(64), default="")
    transaction_type: Mapped[str] = mapped_column(String(16), default="")
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    order_status: Mapped[str] = mapped_column(String(32), default="")
    trade_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    synced_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SyncMeta(Base):
    __tablename__ = "sync_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # always 1
    last_stocks_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_mf_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
