import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional, Any, List

import pandas as pd

from backend.config import DB_PATH, DATA_DIR

logger = logging.getLogger(__name__)


class CacheManager:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DB_PATH
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache_entries (
                    key TEXT PRIMARY KEY,
                    data_blob TEXT NOT NULL,
                    data_type TEXT NOT NULL DEFAULT 'json',
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    source TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cache_expires
                ON cache_entries(expires_at)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kite_instruments (
                    instrument_token INTEGER PRIMARY KEY,
                    exchange TEXT NOT NULL,
                    tradingsymbol TEXT NOT NULL,
                    name TEXT,
                    segment TEXT NOT NULL,
                    expiry TEXT,
                    strike REAL,
                    lot_size INTEGER,
                    instrument_type TEXT,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_kite_instruments_symbol
                ON kite_instruments(exchange, tradingsymbol)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS economic_indicators (
                    series_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    value REAL NOT NULL,
                    frequency TEXT NOT NULL,
                    source TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (series_id, date, frequency)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_economic_indicators_date
                ON economic_indicators(series_id, date)
            """)
            conn.commit()

    def get(self, key: str) -> Optional[Any]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT data_blob, data_type, expires_at FROM cache_entries WHERE key = ?",
                (key,),
            ).fetchone()

            if row is None:
                return None

            expires_at = datetime.fromisoformat(row["expires_at"])
            if datetime.now() > expires_at:
                self.delete(key)
                return None

            if row["data_type"] == "json":
                return json.loads(row["data_blob"])
            if row["data_type"] == "csv":
                df = pd.read_json(row["data_blob"], orient="split")
                df.index = pd.to_datetime(df.index)
                return df
            return row["data_blob"]

    def set(
        self,
        key: str,
        data: Any,
        ttl_hours: int = 24,
        source: str = "unknown",
        data_type: str = "json",
    ) -> None:
        now = datetime.now()
        expires_at = now + timedelta(hours=ttl_hours)

        if isinstance(data, pd.DataFrame):
            df = data.copy()
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            data_blob = df.to_json(orient="split", date_format="iso")
            data_type = "csv"
        elif not isinstance(data, str):
            data_blob = json.dumps(data, default=str)
        else:
            data_blob = data

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cache_entries
                (key, data_blob, data_type, created_at, expires_at, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (key, data_blob, data_type, now.isoformat(), expires_at.isoformat(), source),
            )
            conn.commit()

    def delete(self, key: str) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
            conn.commit()

    def is_fresh(self, key: str, max_age_hours: Optional[int] = None) -> bool:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT expires_at FROM cache_entries WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return False
            cutoff = datetime.now()
            if max_age_hours is not None:
                cutoff -= timedelta(hours=max_age_hours)
            else:
                expires_at = datetime.fromisoformat(row["expires_at"])
                return datetime.now() <= expires_at
            created_at = datetime.fromisoformat(row.get("created_at", row["expires_at"]))
            return created_at > cutoff

    def store_economic_indicator(
        self, series_id: str, data: pd.DataFrame, frequency: str, source: str
    ) -> None:
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            for _, row in data.iterrows():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO economic_indicators
                    (series_id, date, value, frequency, source, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (series_id, str(row.name.date()), float(row.iloc[0]), frequency, source, now),
                )
            conn.commit()

    def get_economic_indicator(self, series_id: str) -> pd.DataFrame:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT date, value FROM economic_indicators
                WHERE series_id = ?
                ORDER BY date ASC
                """,
                (series_id,),
            ).fetchall()
            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame(
                [{"date": pd.Timestamp(r["date"]), "value": r["value"]} for r in rows]
            )
            df = df.set_index("date")
            return df

    def store_kite_instruments(self, instruments: List[dict]) -> None:
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute("DELETE FROM kite_instruments")
            conn.executemany(
                """
                INSERT OR REPLACE INTO kite_instruments
                (instrument_token, exchange, tradingsymbol, name, segment, expiry,
                 strike, lot_size, instrument_type, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        i.get("instrument_token"),
                        i.get("exchange", ""),
                        i.get("tradingsymbol", ""),
                        i.get("name", ""),
                        i.get("segment", ""),
                        i.get("expiry", ""),
                        i.get("strike", 0),
                        i.get("lot_size", 0),
                        i.get("instrument_type", ""),
                        now,
                    )
                    for i in instruments
                ],
            )
            conn.commit()

    def get_instrument_token(self, exchange: str, symbol: str) -> Optional[int]:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT instrument_token FROM kite_instruments
                WHERE exchange = ? AND tradingsymbol = ?
                """,
                (exchange, symbol),
            ).fetchone()
            return row["instrument_token"] if row else None

    def cache_sector_data(self, sector: str, df: pd.DataFrame) -> None:
        cache_key = f"sector_daily_{sector.lower()}"
        self.set(cache_key, df, ttl_hours=24, source="kite")

    def get_sector_data(self, sector: str) -> Optional[pd.DataFrame]:
        cache_key = f"sector_daily_{sector.lower()}"
        result = self.get(cache_key)
        if result is not None:
            return result
        csv_path = DATA_DIR / f"{sector}_data.csv"
        if csv_path.exists():
            df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
            self.cache_sector_data(sector, df)
            return df
        return None

    def vacuum(self) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM cache_entries WHERE expires_at < ?", (datetime.now().isoformat(),))
            conn.execute("VACUUM")
            conn.commit()

    def clear_all(self) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM cache_entries")
            conn.execute("DELETE FROM economic_indicators")
            conn.execute("DELETE FROM kite_instruments")
            conn.commit()
        logger.info("Cache cleared entirely")
