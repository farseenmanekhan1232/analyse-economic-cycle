import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta, datetime
from typing import Dict, List, Optional

import pandas as pd
from kiteconnect import KiteConnect, KiteTicker

from backend.config import (
    API_KEY,
    API_SECRET,
    SECTOR_INDICES,
    KITE_HISTORICAL_CHUNK_DAYS,
    KITE_RATE_LIMIT_SLEEP,
    DEFAULT_START_DATE,
)
from backend.data.cache_manager import CacheManager

logger = logging.getLogger(__name__)


class KiteClient:
    def __init__(self, access_token: Optional[str] = None, cache: Optional[CacheManager] = None) -> None:
        self._kite: Optional[KiteConnect] = None
        self._access_token = access_token
        self.cache = cache or CacheManager()

        if access_token:
            self._kite = KiteConnect(api_key=API_KEY)
            self._kite.set_access_token(access_token)

    @property
    def kite(self) -> KiteConnect:
        if self._kite is None:
            raise RuntimeError(
                "Kite client not initialized. Set access_token or call authenticate()."
            )
        return self._kite

    def authenticate(self, request_token: str) -> str:
        kite = KiteConnect(api_key=API_KEY)
        session = kite.generate_session(request_token, api_secret=API_SECRET)
        self._access_token = session["access_token"]
        self._kite = kite
        self._kite.set_access_token(self._access_token)
        logger.info("Kite authentication successful")
        return self._access_token

    def get_login_url(self) -> str:
        kite = KiteConnect(api_key=API_KEY)
        return kite.login_url()

    @property
    def access_token(self) -> Optional[str]:
        return self._access_token

    def is_authenticated(self) -> bool:
        return self._kite is not None and self._access_token is not None

    def fetch_instruments(self, exchange: str = "NSE") -> List[dict]:
        cache_key = f"instruments_{exchange.lower()}"
        cached = self.cache.get(cache_key)
        if cached:
            logger.info(f"Using cached instruments for {exchange}")
            return cached

        instruments = self.kite.instruments(exchange)
        self.cache.set(cache_key, instruments, ttl_hours=1, source="kite")
        self.cache.store_kite_instruments(instruments)
        logger.info(f"Fetched {len(instruments)} instruments for {exchange}")
        return instruments

    def get_instrument_token(self, exchange: str, trading_symbol: str) -> Optional[int]:
        token = self.cache.get_instrument_token(exchange, trading_symbol)
        if token:
            return token

        instruments = self.fetch_instruments(exchange)
        for inst in instruments:
            if inst["tradingsymbol"] == trading_symbol and inst["exchange"] == exchange:
                return inst["instrument_token"]
        return None

    def resolve_sector_tokens(self, indices: Dict[str, str]) -> Dict[str, int]:
        resolved: Dict[str, int] = {}
        instruments = self.fetch_instruments("NSE")
        for key, symbol in indices.items():
            for inst in instruments:
                if (
                    inst["tradingsymbol"] == symbol
                    and inst["exchange"] == "NSE"
                    and inst["segment"] == "INDICES"
                ):
                    resolved[key] = inst["instrument_token"]
                    break
            else:
                logger.warning(f"Could not find instrument token for {symbol}")
        return resolved

    def _generate_date_ranges(
        self, start: str, end: str, chunk_days: Optional[int] = None
    ) -> List[tuple]:
        chunk_days = chunk_days or KITE_HISTORICAL_CHUNK_DAYS
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")

        ranges: List[tuple] = []
        current = start_date
        while current < end_date:
            chunk_end = min(current + timedelta(days=chunk_days), end_date)
            ranges.append((current.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))
            current = chunk_end + timedelta(days=1)
        return ranges

    def fetch_historical(
        self,
        instrument_token: int,
        start: str,
        end: str,
        interval: str = "day",
        continuous: bool = False,
        oi: bool = False,
    ) -> pd.DataFrame:
        cache_key = f"historical_{instrument_token}_{start}_{end}_{interval}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        all_candles: List[list] = []
        date_ranges = self._generate_date_ranges(start, end)

        for chunk_start, chunk_end in date_ranges:
            try:
                candles = self.kite.historical_data(
                    instrument_token=instrument_token,
                    from_date=chunk_start,
                    to_date=chunk_end,
                    interval=interval,
                    continuous=continuous,
                    oi=oi,
                )
                all_candles.extend(candles)
                if len(date_ranges) > 1:
                    time.sleep(KITE_RATE_LIMIT_SLEEP)
            except Exception as e:
                logger.error(f"Failed to fetch {chunk_start} to {chunk_end}: {e}")

        if not all_candles:
            logger.warning(f"No data for token {instrument_token} from {start} to {end}")
            return pd.DataFrame()

        columns = ["date", "open", "high", "low", "close", "volume"]
        if oi:
            columns.append("oi")

        df = pd.DataFrame(all_candles, columns=columns)
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df = df.set_index("date").sort_index()

        self.cache.set(cache_key, df, ttl_hours=1, source="kite")
        return df

    def fetch_all_sectors(
        self, start: Optional[str] = None, end: Optional[str] = None
    ) -> Dict[str, pd.DataFrame]:
        start = start or DEFAULT_START_DATE
        end = end or datetime.now().strftime("%Y-%m-%d")

        tokens = self.resolve_sector_tokens(SECTOR_INDICES)
        results: Dict[str, pd.DataFrame] = {}

        for key, token in tokens.items():
            cached = self.cache.get_sector_data(key)
            if cached is not None:
                cached_start = cached.index[0].strftime("%Y-%m-%d")
                cached_end = cached.index[-1].strftime("%Y-%m-%d")
                if cached_start <= start and cached_end >= end:
                    logger.info(f"Using cached data for {key}")
                    results[key] = cached.loc[start:end]
                    continue
                else:
                    logger.info(f"Updating stale cache for {key}")

            df = self.fetch_historical(token, start, end)
            if not df.empty:
                self.cache.cache_sector_data(key, df)
                results[key] = df
            time.sleep(KITE_RATE_LIMIT_SLEEP)

        return results

    def _fetch_one_sector(
        self, key: str, token: int, start: str, end: str, sem: threading.Semaphore,
    ) -> tuple:
        with sem:
            cached = self.cache.get_sector_data(key)
            if cached is not None:
                cached_start = cached.index[0].strftime("%Y-%m-%d")
                cached_end = cached.index[-1].strftime("%Y-%m-%d")
                if cached_start <= start and cached_end >= end:
                    logger.info(f"Using cached data for {key}")
                    time.sleep(KITE_RATE_LIMIT_SLEEP / 2)
                    return (key, cached.loc[start:end])

            df = self.fetch_historical(token, start, end)
            time.sleep(KITE_RATE_LIMIT_SLEEP / 2)
            if not df.empty:
                self.cache.cache_sector_data(key, df)
                return (key, df)
            return (key, pd.DataFrame())

    def fetch_all_sectors_parallel(
        self, start: Optional[str] = None, end: Optional[str] = None, max_workers: int = 3,
    ) -> Dict[str, pd.DataFrame]:
        start = start or DEFAULT_START_DATE
        end = end or datetime.now().strftime("%Y-%m-%d")

        tokens = self.resolve_sector_tokens(SECTOR_INDICES)
        results: Dict[str, pd.DataFrame] = {}
        sem = threading.Semaphore(max_workers)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._fetch_one_sector, key, token, start, end, sem): key
                for key, token in tokens.items()
            }
            for f in as_completed(futures):
                try:
                    key, df = f.result()
                    if not df.empty:
                        results[key] = df
                except Exception as e:
                    logger.error(f"Failed to fetch sector {futures[f]}: {e}")

        return results

    def get_quote(self, instruments: List[str]) -> dict:
        return self.kite.quote(instruments)

    def get_profile(self) -> dict:
        return self.kite.profile()

    def get_margins(self) -> dict:
        return self.kite.margins()
