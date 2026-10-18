"""Free macro data client using yfinance for global indicators.

Replaces FRED (pandas_datareader) with yfinance for:
- WTI Crude Oil (CL=F)
- VIX (^VIX)
- US Dollar Index (DX-Y.NYB)
- INR/USD (INR=X)
- US 10Y Yield (^TNX)
- Nifty 50 (^NSEI) as benchmark

All free, no API key required.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

from backend.config import YFINANCE_TICKERS, DEFAULT_START_DATE
from backend.data.cache_manager import CacheManager

logger = logging.getLogger(__name__)


class MacroClient:
    """Fetches global macro indicators from yfinance (free tier)."""

    def __init__(self, cache: Optional[CacheManager] = None) -> None:
        self.cache = cache or CacheManager()

    def fetch_series(
        self,
        ticker_key: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        if ticker_key not in YFINANCE_TICKERS:
            raise ValueError(
                f"Unknown ticker key: {ticker_key}. Available: {list(YFINANCE_TICKERS.keys())}"
            )

        symbol = YFINANCE_TICKERS[ticker_key]
        start = start or DEFAULT_START_DATE
        end = end or datetime.now().strftime("%Y-%m-%d")

        cache_id = f"yf_{symbol}"

        if not force_refresh:
            cached = self.cache.get_economic_indicator(cache_id)
            if not cached.empty:
                cached_start = cached.index[0].strftime("%Y-%m-%d")
                cached_end = cached.index[-1].strftime("%Y-%m-%d")
                if cached_start <= start and cached_end >= end:
                    logger.info(f"Using cached data for {ticker_key} ({symbol})")
                    return cached.loc[start:end]

        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start, end=end, auto_adjust=True)

            if df.empty:
                logger.warning(f"No data returned for {ticker_key} ({symbol})")
                cached = self.cache.get_economic_indicator(cache_id)
                if not cached.empty:
                    logger.info(f"Returning stale cached data for {ticker_key}")
                    return cached.loc[start:end]
                return pd.DataFrame()

            # Use 'Close' column safely
            if "Close" in df.columns:
                result = pd.DataFrame({"value": df["Close"]})
            elif len(df.columns) > 0:
                result = pd.DataFrame({"value": df.iloc[:, 0]})
            else:
                return pd.DataFrame()

            result.index.name = "date"
            result = result.dropna()

            freq = self._infer_frequency(result)
            self.cache.store_economic_indicator(cache_id, result, freq, "yfinance")
            logger.info(f"Fetched {ticker_key} ({symbol}): {len(result)} records")

            return result

        except Exception as e:
            logger.error(f"Failed to fetch {ticker_key} ({symbol}): {e}")
            cached = self.cache.get_economic_indicator(cache_id)
            if not cached.empty:
                logger.warning(f"Returning stale cached data for {ticker_key}")
                return cached.loc[start:end]
            return pd.DataFrame()

    def _infer_frequency(self, df: pd.DataFrame) -> str:
        if len(df) < 2:
            return "unknown"
        diffs = df.index.to_series().diff().dropna()
        median_diff = diffs.median()
        if median_diff.days <= 1:
            return "daily"
        if median_diff.days <= 31:
            return "monthly"
        return "quarterly"

    def fetch_wti_crude(self, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        return self.fetch_series("WTI_CRUDE", start, end)

    def fetch_vix(self, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        return self.fetch_series("US_VIX", start, end)

    def fetch_dollar_index(self, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        return self.fetch_series("DOLLAR_INDEX", start, end)

    def fetch_inrusd(self, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        return self.fetch_series("INRUSD", start, end)

    def fetch_us_10y_yield(self, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        return self.fetch_series("US_10Y_YIELD", start, end)

    def fetch_nifty_50(self, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
        return self.fetch_series("NIFTY_50", start, end)

    def fetch_all_global(
        self, start: Optional[str] = None, end: Optional[str] = None
    ) -> Dict[str, pd.DataFrame]:
        """Fetch all global indicators in parallel."""
        start = start or DEFAULT_START_DATE
        end = end or datetime.now().strftime("%Y-%m-%d")

        keys = ["WTI_CRUDE", "US_VIX", "DOLLAR_INDEX", "INRUSD", "US_10Y_YIELD"]
        results: Dict[str, pd.DataFrame] = {}

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(self.fetch_series, k, start, end): k for k in keys}
            for f in as_completed(futures):
                key = futures[f]
                try:
                    df = f.result()
                    if not df.empty:
                        results[key] = df
                except Exception:
                    logger.warning(f"Parallel fetch failed for {key}")

        return results
