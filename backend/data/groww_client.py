"""Optional Groww Trade API — equity/ETF holdings sync (MFs not available)."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

GROWW_API_BASE = os.getenv("GROWW_API_BASE", "https://api.groww.in")


def _checksum(secret: str, timestamp: str) -> str:
    return hashlib.sha256(f"{secret}{timestamp}".encode("utf-8")).hexdigest()


class GrowwClient:
    """Auth via API key + secret (daily access token) or a ready-made access token."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("GROWW_API_KEY", "")
        self.api_secret = api_secret or os.getenv("GROWW_API_SECRET", "")
        self.access_token = access_token or os.getenv("GROWW_ACCESS_TOKEN", "")
        self._token_expiry: Optional[str] = None

    @property
    def configured(self) -> bool:
        return bool(self.access_token or (self.api_key and self.api_secret))

    def ensure_access_token(self) -> str:
        if self.api_key and self.api_secret:
            # Key+secret flow always needs a daily-approved access token.
            # Do not fall back to using the API key JWT as Bearer — that 403s holdings.
            token, expiry = self._exchange_token()
            self.access_token = token
            self._token_expiry = expiry
            return token
        if self.access_token:
            return self.access_token
        if self.api_key and self.api_key.count(".") >= 2:
            self.access_token = self.api_key
            return self.access_token
        raise RuntimeError("Groww credentials not configured")

    def _exchange_token(self) -> Tuple[str, Optional[str]]:
        timestamp = str(int(time.time()))
        checksum = _checksum(self.api_secret, timestamp)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-VERSION": "1.0",
        }
        body = {"key_type": "approval", "checksum": checksum, "timestamp": timestamp}
        with httpx.Client(timeout=30.0, base_url=GROWW_API_BASE) as client:
            r = client.post("/v1/token/api/access", headers=headers, json=body)
            if r.status_code >= 400:
                logger.error("Groww token exchange failed: %s %s", r.status_code, r.text[:500])
                msg = ""
                try:
                    err = r.json().get("error") or {}
                    if isinstance(err, dict):
                        msg = str(err.get("errorMessage") or err.get("message") or "")
                except Exception:
                    msg = r.text[:200]
                if r.status_code == 403 or "approval" in msg.lower():
                    raise RuntimeError(
                        "Groww session approval required. Open Groww → Settings → Trading APIs "
                        "→ API Keys, approve today’s session for this key, then Sync stocks again."
                        + (f" ({msg})" if msg else "")
                    )
                r.raise_for_status()
            data = r.json()
        # Response shapes vary: {token:...} or {payload:{token:...}} or {status, payload}
        token = None
        expiry = None
        if isinstance(data, dict):
            payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
            token = payload.get("token") or payload.get("access_token") or data.get("token")
            expiry = payload.get("expiry") or data.get("expiry")
        if not token:
            raise RuntimeError(f"Groww token response missing token: {data}")
        return str(token), expiry

    def _auth_headers(self) -> Dict[str, str]:
        token = self.ensure_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-VERSION": "1.0",
        }

    def fetch_holdings(self) -> List[Dict[str, Any]]:
        if not self.configured:
            logger.info("Groww client not configured — skip holdings sync")
            return []
        try:
            with httpx.Client(timeout=30.0, base_url=GROWW_API_BASE) as client:
                r = client.get("/v1/holdings/user", headers=self._auth_headers())
                if r.status_code >= 400:
                    logger.error("Groww holdings failed: %s %s", r.status_code, r.text[:500])
                    r.raise_for_status()
                data = r.json()
            return self._normalize_holdings(data)
        except Exception as exc:
            logger.warning("Groww holdings sync failed: %s", exc)
            raise

    def _normalize_holdings(self, data: Any) -> List[Dict[str, Any]]:
        payload = data.get("payload") if isinstance(data, dict) else None
        raw = []
        if isinstance(payload, dict):
            raw = payload.get("holdings") or []
        elif isinstance(data, dict):
            raw = data.get("holdings") or data.get("data") or []
        if not isinstance(raw, list):
            return []
        out = []
        for h in raw:
            if not isinstance(h, dict):
                continue
            symbol = h.get("trading_symbol") or h.get("symbol") or ""
            qty = float(h.get("quantity") or 0)
            avg = float(h.get("average_price") or h.get("avg_price") or 0)
            if not symbol or qty <= 0:
                continue
            upper = symbol.upper()
            asset = "etf" if ("BEES" in upper or "ETF" in upper or upper.endswith("IETF")) else "stock"
            # Known sector ETF tickers without ETF/BEES in the symbol (e.g. MOREALTY)
            if asset == "stock":
                try:
                    from backend.decision.instruments import etf_symbols_by_sector

                    known = {s.upper() for syms in etf_symbols_by_sector().values() for s in syms}
                    if upper in known:
                        asset = "etf"
                except Exception:
                    if upper in {
                        "MOREALTY",
                        "MOENERGY",
                        "MOHEALTH",
                        "MOINFRA",
                        "ENERGY",
                        "METAL",
                        "IT",
                        "CONSUMER",
                    }:
                        asset = "etf"
            out.append(
                {
                    "instrument": symbol,
                    "asset_class": asset,
                    "units": qty,
                    "avg_cost": avg,
                    "invested_amount": round(qty * avg, 2),
                    "last_nav": avg,
                    "scheme_code": h.get("isin") or "",
                    "sector": "",
                    "sleeve": "satellite",
                }
            )
        return out

    def status(self) -> Dict[str, Any]:
        return {
            "configured": self.configured,
            "has_api_key": bool(self.api_key),
            "has_api_secret": bool(self.api_secret),
            "has_access_token": bool(self.access_token),
            "token_expiry": self._token_expiry,
        }
