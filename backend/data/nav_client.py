"""Public mutual fund NAV lookup via mfapi.in (no Groww login)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

MFAPI_BASE = "https://api.mfapi.in"
_SCHEME_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}


def search_schemes(query: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Search AMFI schemes by name. Returns [{schemeCode, schemeName}, ...]."""
    q = (query or "").strip()
    if len(q) < 2:
        return []
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.get(f"{MFAPI_BASE}/mf/search", params={"q": q})
            r.raise_for_status()
            data = r.json()
        if not isinstance(data, list):
            return []
        out = []
        for item in data[:limit]:
            out.append(
                {
                    "scheme_code": str(item.get("schemeCode") or item.get("scheme_code") or ""),
                    "scheme_name": item.get("schemeName") or item.get("scheme_name") or "",
                }
            )
        return [x for x in out if x["scheme_code"]]
    except Exception as exc:
        logger.warning("mfapi search failed: %s", exc)
        return []


def fetch_latest_nav(scheme_code: str) -> Optional[Dict[str, Any]]:
    """Return {scheme_code, scheme_name, nav, date} or None."""
    code = str(scheme_code or "").strip()
    if not code:
        return None
    if code in _SCHEME_CACHE and _SCHEME_CACHE[code] is not None:
        cached = _SCHEME_CACHE[code]
        # refresh daily
        if cached and cached.get("fetched_on") == date.today().isoformat():
            return cached
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.get(f"{MFAPI_BASE}/mf/{code}")
            r.raise_for_status()
            data = r.json()
        meta = data.get("meta") or {}
        history = data.get("data") or []
        if not history:
            return None
        latest = history[0]
        nav = float(str(latest.get("nav", "0")).replace(",", ""))
        result = {
            "scheme_code": code,
            "scheme_name": meta.get("scheme_name") or meta.get("schemeName") or "",
            "nav": nav,
            "date": latest.get("date") or date.today().isoformat(),
            "fetched_on": date.today().isoformat(),
        }
        _SCHEME_CACHE[code] = result
        return result
    except Exception as exc:
        logger.warning("mfapi NAV fetch failed for %s: %s", code, exc)
        _SCHEME_CACHE[code] = None
        return None


def nav_for_scheme(scheme_code: str) -> Optional[float]:
    info = fetch_latest_nav(scheme_code)
    return float(info["nav"]) if info else None
