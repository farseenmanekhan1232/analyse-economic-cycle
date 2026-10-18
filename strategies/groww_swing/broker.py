"""Thin growwapi wrapper for candles, quotes, holdings, orders, and GTT.

Designed for Groww Cloud: depends only on growwapi (+ optional pyotp).
Falls back gracefully when growwapi is not installed (research / dry unit tests).
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

logger = logging.getLogger(__name__)


def _ref_id(prefix: str = "sw") -> str:
    # Groww: 8–20 alphanumeric, at most two hyphens
    raw = f"{prefix}-{uuid.uuid4().hex[:10]}"
    return raw[:20]


def candles_to_df(payload: Any) -> pd.DataFrame:
    """Normalize Groww historical candle payload to OHLCV DataFrame."""
    if payload is None:
        return pd.DataFrame()
    candles = payload
    if isinstance(payload, dict):
        candles = payload.get("candles") or payload.get("payload", {}).get("candles") or []
    rows = []
    for c in candles or []:
        if not isinstance(c, (list, tuple)) or len(c) < 5:
            continue
        ts = c[0]
        if isinstance(ts, (int, float)):
            # epoch seconds or ms
            if ts > 1e12:
                ts = pd.to_datetime(ts, unit="ms")
            else:
                ts = pd.to_datetime(ts, unit="s")
        else:
            ts = pd.to_datetime(ts)
        row = {
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "volume": float(c[5]) if len(c) > 5 and c[5] is not None else 0.0,
        }
        rows.append((ts, row))
    if not rows:
        return pd.DataFrame()
    idx = [r[0] for r in rows]
    data = [r[1] for r in rows]
    df = pd.DataFrame(data, index=pd.DatetimeIndex(idx))
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


class GrowwBroker:
    """Auth + market data + CNC order / GTT helpers."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        totp_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        dry_run: bool = True,
    ) -> None:
        self.api_key = api_key or os.getenv("GROWW_API_KEY", "") or os.getenv("GROWW_TOTP_TOKEN", "")
        self.api_secret = api_secret or os.getenv("GROWW_API_SECRET", "")
        self.totp_secret = totp_secret or os.getenv("GROWW_TOTP_SECRET", "")
        self.access_token = access_token or os.getenv("GROWW_ACCESS_TOKEN", "")
        self.dry_run = dry_run
        self._client = None

    def connect(self) -> Any:
        """Return GrowwAPI client, exchanging token if needed."""
        if self._client is not None:
            return self._client
        try:
            from growwapi import GrowwAPI
        except ImportError as exc:
            raise RuntimeError(
                "growwapi is not installed. pip install growwapi pyotp"
            ) from exc

        token = self.access_token
        if not token:
            if self.totp_secret and self.api_key:
                import pyotp

                totp = pyotp.TOTP(self.totp_secret).now()
                token = GrowwAPI.get_access_token(api_key=self.api_key, totp=totp)
            elif self.api_key and self.api_secret:
                token = GrowwAPI.get_access_token(
                    api_key=self.api_key, secret=self.api_secret
                )
            else:
                raise RuntimeError(
                    "Set GROWW_ACCESS_TOKEN or GROWW_API_KEY + "
                    "(GROWW_API_SECRET or GROWW_TOTP_SECRET)"
                )
        self.access_token = token
        self._client = GrowwAPI(token)
        return self._client

    @property
    def client(self) -> Any:
        return self.connect()

    def get_ltp(self, exchange: str, segment: str, trading_symbol: str) -> Optional[float]:
        groww = self.client
        try:
            # SDK method names vary slightly across versions
            if hasattr(groww, "get_ltp"):
                resp = groww.get_ltp(
                    exchange=getattr(groww, f"EXCHANGE_{exchange}", exchange),
                    segment=getattr(groww, f"SEGMENT_{segment}", segment),
                    trading_symbols=trading_symbol,
                )
            else:
                resp = groww.get_quote(
                    exchange=getattr(groww, f"EXCHANGE_{exchange}", exchange),
                    segment=getattr(groww, f"SEGMENT_{segment}", segment),
                    trading_symbol=trading_symbol,
                )
            return self._extract_ltp(resp, trading_symbol)
        except Exception as exc:
            logger.warning("LTP failed for %s: %s", trading_symbol, exc)
            return None

    @staticmethod
    def _extract_ltp(resp: Any, symbol: str) -> Optional[float]:
        if resp is None:
            return None
        if isinstance(resp, (int, float)):
            return float(resp)
        if isinstance(resp, dict):
            for key in ("ltp", "last_price", "lastPrice"):
                if key in resp and resp[key] is not None:
                    return float(resp[key])
            payload = resp.get("payload") if isinstance(resp.get("payload"), dict) else resp
            if isinstance(payload, dict):
                if symbol in payload:
                    return GrowwBroker._extract_ltp(payload[symbol], symbol)
                for key in ("ltp", "last_price", "lastPrice"):
                    if key in payload and payload[key] is not None:
                        return float(payload[key])
        return None

    def get_historical_candles(
        self,
        *,
        trading_symbol: str,
        exchange: str = "NSE",
        segment: str = "CASH",
        days: int = 180,
        interval: str = "day",
        groww_symbol: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Fetch candles, chunked to Groww backtesting API limits.

        Daily / 1h: max 180 days per request.
        15/30m: max 90 days per request.
        Equity/index history on Groww starts ~2020 (vendor limit).
        """
        groww = self.client
        end_dt = end or datetime.now()
        if start is not None:
            start_dt = start
        else:
            start_dt = end_dt - timedelta(days=days)
        gsym = groww_symbol or f"{exchange}-{trading_symbol}"

        frames: List[pd.DataFrame] = []
        # Docs: day/1h/4h/week/month → 180d; 10/15/30m → 90d; 1–5m → 30d
        key = interval.lower()
        if key in ("day", "1d", "1440", "1day", "week", "month", "hour", "60min", "4hour"):
            chunk_days = 180
        elif key in ("10min", "15min", "30min"):
            chunk_days = 90
        else:
            chunk_days = 30

        cursor = start_dt
        while cursor < end_dt:
            chunk_end = min(cursor + timedelta(days=chunk_days), end_dt)
            start_s = cursor.strftime("%Y-%m-%d %H:%M:%S")
            end_s = chunk_end.strftime("%Y-%m-%d %H:%M:%S")
            try:
                if hasattr(groww, "get_historical_candles"):
                    candle_interval = self._candle_interval(groww, interval)
                    resp = groww.get_historical_candles(
                        exchange=getattr(groww, f"EXCHANGE_{exchange}", exchange),
                        segment=getattr(groww, f"SEGMENT_{segment}", segment),
                        groww_symbol=gsym,
                        start_time=start_s,
                        end_time=end_s,
                        candle_interval=candle_interval,
                    )
                else:
                    minutes = self._interval_minutes(interval)
                    resp = groww.get_historical_candle_data(
                        trading_symbol=trading_symbol,
                        exchange=getattr(groww, f"EXCHANGE_{exchange}", exchange),
                        segment=getattr(groww, f"SEGMENT_{segment}", segment),
                        start_time=start_s,
                        end_time=end_s,
                        interval_in_minutes=minutes,
                    )
                df = candles_to_df(resp)
                if not df.empty:
                    frames.append(df)
            except Exception as exc:
                logger.warning(
                    "Candles failed %s %s→%s: %s", trading_symbol, start_s, end_s, exc
                )
            cursor = chunk_end
            time.sleep(0.05)

        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames).sort_index()
        return out[~out.index.duplicated(keep="last")]

    @staticmethod
    def _interval_minutes(interval: str) -> int:
        mapping = {
            "1min": 1,
            "5min": 5,
            "15min": 15,
            "30min": 30,
            "60min": 60,
            "hour": 60,
            "day": 1440,
            "1d": 1440,
            "1day": 1440,
        }
        return mapping.get(interval.lower(), 1440)

    @staticmethod
    def _candle_interval(groww: Any, interval: str) -> Any:
        key = interval.lower()
        attr_map = {
            "1min": "CANDLE_INTERVAL_MIN_1",
            "5min": "CANDLE_INTERVAL_MIN_5",
            "15min": "CANDLE_INTERVAL_MIN_15",
            "30min": "CANDLE_INTERVAL_MIN_30",
            "60min": "CANDLE_INTERVAL_HOUR_1",
            "hour": "CANDLE_INTERVAL_HOUR_1",
            "day": "CANDLE_INTERVAL_DAY",
            "1d": "CANDLE_INTERVAL_DAY",
            "1day": "CANDLE_INTERVAL_DAY",
        }
        attr = attr_map.get(key, "CANDLE_INTERVAL_DAY")
        return getattr(groww, attr, attr)

    def get_holdings(self) -> List[Dict[str, Any]]:
        groww = self.client
        try:
            resp = groww.get_holdings_for_user(timeout=10)
        except Exception as exc:
            logger.warning("Holdings failed: %s", exc)
            return []
        holdings = []
        if isinstance(resp, dict):
            payload = resp.get("payload") if isinstance(resp.get("payload"), dict) else resp
            holdings = payload.get("holdings") or resp.get("holdings") or []
        out = []
        for h in holdings or []:
            if not isinstance(h, dict):
                continue
            sym = h.get("trading_symbol") or h.get("symbol") or ""
            qty = float(h.get("quantity") or 0)
            if not sym or qty <= 0:
                continue
            out.append(
                {
                    "trading_symbol": str(sym).upper(),
                    "quantity": qty,
                    "average_price": float(h.get("average_price") or h.get("avg_price") or 0),
                    "isin": h.get("isin") or "",
                }
            )
        return out

    def estimate_capital(self, fallback: float = 100_000.0) -> float:
        """Rough capital from holdings market value; else fallback."""
        holdings = self.get_holdings()
        total = 0.0
        for h in holdings:
            ltp = self.get_ltp("NSE", "CASH", h["trading_symbol"])
            px = ltp or h["average_price"]
            total += h["quantity"] * px
        return total if total > 0 else fallback

    def place_cnc_buy(
        self,
        *,
        trading_symbol: str,
        quantity: int,
        price: Optional[float] = None,
        order_type: str = "LIMIT",
        exchange: str = "NSE",
    ) -> Dict[str, Any]:
        ref = _ref_id("buy")
        if self.dry_run:
            logger.info(
                "[DRY_RUN] BUY %s qty=%s type=%s price=%s ref=%s",
                trading_symbol,
                quantity,
                order_type,
                price,
                ref,
            )
            return {
                "dry_run": True,
                "groww_order_id": f"DRY-{ref}",
                "order_status": "DRY_RUN",
                "order_reference_id": ref,
                "trading_symbol": trading_symbol,
                "quantity": quantity,
            }

        groww = self.client
        kwargs: Dict[str, Any] = {
            "trading_symbol": trading_symbol,
            "quantity": int(quantity),
            "validity": groww.VALIDITY_DAY,
            "exchange": getattr(groww, f"EXCHANGE_{exchange}", exchange),
            "segment": groww.SEGMENT_CASH,
            "product": groww.PRODUCT_CNC,
            "transaction_type": groww.TRANSACTION_TYPE_BUY,
            "order_reference_id": ref,
        }
        if order_type.upper() == "MARKET":
            kwargs["order_type"] = groww.ORDER_TYPE_MARKET
        else:
            kwargs["order_type"] = groww.ORDER_TYPE_LIMIT
            if price is None:
                raise ValueError("LIMIT order requires price")
            kwargs["price"] = float(price)

        resp = groww.place_order(**kwargs)
        logger.info("Placed BUY %s: %s", trading_symbol, resp)
        return resp if isinstance(resp, dict) else {"raw": resp, "order_reference_id": ref}

    def place_cnc_sell(
        self,
        *,
        trading_symbol: str,
        quantity: int,
        price: Optional[float] = None,
        order_type: str = "MARKET",
        exchange: str = "NSE",
    ) -> Dict[str, Any]:
        """CNC sell (time exits / manual flatten)."""
        ref = _ref_id("sell")
        if self.dry_run:
            logger.info(
                "[DRY_RUN] SELL %s qty=%s type=%s price=%s ref=%s",
                trading_symbol,
                quantity,
                order_type,
                price,
                ref,
            )
            return {
                "dry_run": True,
                "groww_order_id": f"DRY-{ref}",
                "order_status": "DRY_RUN",
                "order_reference_id": ref,
                "trading_symbol": trading_symbol,
                "quantity": quantity,
                "side": "SELL",
            }

        groww = self.client
        kwargs: Dict[str, Any] = {
            "trading_symbol": trading_symbol,
            "quantity": int(quantity),
            "validity": groww.VALIDITY_DAY,
            "exchange": getattr(groww, f"EXCHANGE_{exchange}", exchange),
            "segment": groww.SEGMENT_CASH,
            "product": groww.PRODUCT_CNC,
            "transaction_type": groww.TRANSACTION_TYPE_SELL,
            "order_reference_id": ref,
        }
        if order_type.upper() == "MARKET":
            kwargs["order_type"] = groww.ORDER_TYPE_MARKET
        else:
            kwargs["order_type"] = groww.ORDER_TYPE_LIMIT
            if price is None:
                raise ValueError("LIMIT sell requires price")
            kwargs["price"] = float(price)

        resp = groww.place_order(**kwargs)
        logger.info("Placed SELL %s: %s", trading_symbol, resp)
        return resp if isinstance(resp, dict) else {"raw": resp, "order_reference_id": ref}

    def place_gtt_stop(
        self,
        *,
        trading_symbol: str,
        quantity: int,
        trigger_price: float,
        exchange: str = "NSE",
    ) -> Dict[str, Any]:
        """Arm a GTT sell when price falls through stop (CNC)."""
        ref = _ref_id("gtt")
        if self.dry_run:
            logger.info(
                "[DRY_RUN] GTT STOP SELL %s qty=%s trigger=%s ref=%s",
                trading_symbol,
                quantity,
                trigger_price,
                ref,
            )
            return {
                "dry_run": True,
                "smart_order_id": f"DRY-{ref}",
                "status": "DRY_RUN",
                "reference_id": ref,
            }

        groww = self.client
        kwargs = {
            "smart_order_type": groww.SMART_ORDER_TYPE_GTT,
            "reference_id": ref,
            "segment": groww.SEGMENT_CASH,
            "trading_symbol": trading_symbol,
            "quantity": int(quantity),
            "product_type": groww.PRODUCT_CNC,
            "exchange": getattr(groww, f"EXCHANGE_{exchange}", exchange),
            "duration": groww.VALIDITY_DAY,
            "trigger_price": f"{float(trigger_price):.2f}",
            "trigger_direction": groww.TRIGGER_DIRECTION_DOWN,
            "order": {
                "order_type": groww.ORDER_TYPE_STOP_LOSS_MARKET
                if hasattr(groww, "ORDER_TYPE_STOP_LOSS_MARKET")
                else groww.ORDER_TYPE_MARKET,
                "transaction_type": groww.TRANSACTION_TYPE_SELL,
            },
        }
        # Some SDK versions require price=None explicitly for SL-M
        try:
            resp = groww.create_smart_order(**kwargs)
        except TypeError:
            kwargs["order"]["price"] = None
            resp = groww.create_smart_order(**kwargs)
        logger.info("GTT stop %s: %s", trading_symbol, resp)
        return resp if isinstance(resp, dict) else {"raw": resp, "reference_id": ref}

    def place_gtt_target(
        self,
        *,
        trading_symbol: str,
        quantity: int,
        trigger_price: float,
        exchange: str = "NSE",
    ) -> Dict[str, Any]:
        ref = _ref_id("tgt")
        if self.dry_run:
            logger.info(
                "[DRY_RUN] GTT TARGET SELL %s qty=%s trigger=%s ref=%s",
                trading_symbol,
                quantity,
                trigger_price,
                ref,
            )
            return {
                "dry_run": True,
                "smart_order_id": f"DRY-{ref}",
                "status": "DRY_RUN",
                "reference_id": ref,
            }

        groww = self.client
        resp = groww.create_smart_order(
            smart_order_type=groww.SMART_ORDER_TYPE_GTT,
            reference_id=ref,
            segment=groww.SEGMENT_CASH,
            trading_symbol=trading_symbol,
            quantity=int(quantity),
            product_type=groww.PRODUCT_CNC,
            exchange=getattr(groww, f"EXCHANGE_{exchange}", exchange),
            duration=groww.VALIDITY_DAY,
            trigger_price=f"{float(trigger_price):.2f}",
            trigger_direction=groww.TRIGGER_DIRECTION_UP,
            order={
                "order_type": groww.ORDER_TYPE_LIMIT,
                "price": f"{float(trigger_price):.2f}",
                "transaction_type": groww.TRANSACTION_TYPE_SELL,
            },
        )
        logger.info("GTT target %s: %s", trading_symbol, resp)
        return resp if isinstance(resp, dict) else {"raw": resp, "reference_id": ref}

    def fetch_sector_closes(
        self,
        sector_symbols: Dict[str, str],
        *,
        days: int = 400,
        exchange: str = "NSE",
        etf_fallback: Optional[Dict[str, str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch OHLCV for each sector proxy symbol → {sector_id: df}.

        Index names often fail on Groww CASH; pass etf_fallback for per-sector ETF retry.
        """
        out: Dict[str, pd.DataFrame] = {}
        for sector, symbol in sector_symbols.items():
            df = self._fetch_one_proxy(symbol, days=days, exchange=exchange)
            if df.empty and etf_fallback and sector in etf_fallback:
                etf = etf_fallback[sector]
                if etf.upper() != symbol.upper():
                    logger.info(
                        "Index proxy failed for %s (%s); trying ETF %s",
                        sector,
                        symbol,
                        etf,
                    )
                    df = self._fetch_one_proxy(etf, days=days, exchange=exchange)
            if not df.empty:
                out[sector] = df
            else:
                logger.warning("No candles for sector proxy %s (%s)", sector, symbol)
        return out

    def _fetch_one_proxy(
        self,
        symbol: str,
        *,
        days: int,
        exchange: str,
        start: Optional[datetime] = None,
    ) -> pd.DataFrame:
        kwargs: Dict[str, Any] = {
            "trading_symbol": symbol,
            "exchange": exchange,
            "interval": "day",
            "groww_symbol": f"{exchange}-{symbol}",
        }
        if start is not None:
            kwargs["start"] = start
        else:
            kwargs["days"] = days
        df = self.get_historical_candles(**kwargs)
        if df.empty and " " in symbol:
            alt = symbol.replace(" ", "")
            kwargs["trading_symbol"] = alt
            kwargs["groww_symbol"] = f"{exchange}-{alt}"
            df = self.get_historical_candles(**kwargs)
        return df

    def fetch_symbol_candles(
        self,
        symbols: Sequence[str],
        *,
        days: int = 180,
        exchange: str = "NSE",
    ) -> Dict[str, pd.DataFrame]:
        out: Dict[str, pd.DataFrame] = {}
        for sym in symbols:
            df = self.get_historical_candles(
                trading_symbol=sym,
                exchange=exchange,
                days=days,
                interval="day",
            )
            if not df.empty:
                out[sym.upper()] = df
        return out
