import logging
from typing import Dict, List, Optional

from backend.config import API_KEY
from backend.data.cache_manager import CacheManager

logger = logging.getLogger(__name__)

# Primary keywords must match; exclude_keywords reject false positives.
SECTOR_KEYWORDS: Dict[str, Dict[str, List[str]]] = {
    "BANK": {
        "include": ["nifty bank", "banking", "bank be", "banketf", "private bank"],
        "exclude": ["psu bank", "public sector"],
    },
    "IT": {
        "include": ["nifty it", "information technology", "technology fund", "digital india"],
        "exclude": ["biotech", "fintech"],
    },
    "PHARMA": {
        "include": ["pharma", "pharmaceutical"],
        "exclude": [],
    },
    "FMCG": {
        "include": ["fmcg", "fast moving consumer"],
        "exclude": ["durables"],
    },
    "AUTO": {
        "include": ["auto", "automobile", "nifty auto"],
        "exclude": [],
    },
    "METAL": {
        "include": ["metal", "nifty metal"],
        "exclude": ["precious"],
    },
    "MEDIA": {
        "include": ["media", "entertainment"],
        "exclude": [],
    },
    "REALTY": {
        "include": ["realty", "real estate", "nifty realty"],
        "exclude": [],
    },
    "ENERGY": {
        "include": ["nifty energy", "energy fund", "power &"],
        "exclude": ["renewable only"],
    },
    "INFRA": {
        "include": ["infrastructure", "nifty infra", "infra fund"],
        "exclude": [],
    },
    "PSU_BANK": {
        "include": ["psu bank", "public sector bank"],
        "exclude": [],
    },
    "PVT_BANK": {
        "include": ["private bank", "private sector bank"],
        "exclude": ["psu"],
    },
    "OIL_GAS": {
        "include": ["oil & gas", "oil and gas", "petroleum"],
        "exclude": [],
    },
    "CONSUMER_DURABLES": {
        "include": ["consumption", "consumer durables", "nifty india consumption"],
        "exclude": ["fmcg"],
    },
    "HEALTHCARE": {
        "include": ["healthcare", "health care", "nifty healthcare"],
        "exclude": [],
    },
}


class MFClient:
    def __init__(self, cache: Optional[CacheManager] = None, kite=None) -> None:
        self.cache = cache or CacheManager()
        self._kite = kite
        self._instruments: Optional[List[dict]] = None

    def fetch_instruments(self) -> List[dict]:
        cached = self.cache.get("mf_instruments")
        if cached:
            logger.info("Using cached MF instruments")
            self._instruments = cached
            return cached

        if self._kite is None:
            from kiteconnect import KiteConnect
            k = KiteConnect(api_key=API_KEY)
            self._kite = k

        instruments = self._kite.mf_instruments()
        self.cache.set("mf_instruments", instruments, ttl_hours=24, source="kite_mf")
        self._instruments = instruments
        logger.info(f"Fetched {len(instruments)} MF instruments")
        return instruments

    def find_funds(self, sector_key: str, max_results: int = 3) -> List[dict]:
        rules = SECTOR_KEYWORDS.get(sector_key)
        if not rules:
            keywords = [sector_key.lower().replace("_", " ")]
            excludes: List[str] = []
        else:
            keywords = rules["include"]
            excludes = rules.get("exclude") or []

        instruments = self._instruments or self.fetch_instruments()

        matches: List[dict] = []
        for mf in instruments:
            name = (mf.get("name", "") + " " + mf.get("tradingsymbol", "")).lower()
            scheme = mf.get("scheme_type", "").lower()

            if scheme not in ("equity",):
                continue
            if any(ex in name for ex in excludes):
                continue

            # Prefer longer / more specific keyword hits
            best_kw_len = 0
            for kw in keywords:
                if kw in name:
                    best_kw_len = max(best_kw_len, len(kw))
            if best_kw_len == 0:
                continue
            matches.append({**mf, "_kw_len": best_kw_len})

        scored: List[tuple] = []
        seen: set = set()
        for mf in matches:
            plan = mf.get("plan", "").lower()
            div_type = mf.get("dividend_type", "").lower()
            purchase = mf.get("purchase_allowed", False)

            clean_name = mf.get("name", "").strip()
            if clean_name in seen:
                continue
            seen.add(clean_name)

            score = int(mf.get("_kw_len") or 0)
            if plan == "direct":
                score += 3
            if div_type == "growth":
                score += 2
            if purchase:
                score += 1
            # Prefer index / ETF-style sector funds over broad themes when named
            lname = clean_name.lower()
            if "nifty" in lname or "index" in lname:
                score += 4
            if "etf" in lname:
                score += 2

            scored.append((score, mf))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {k: v for k, v in s[1].items() if not str(k).startswith("_")} | {"relevance": s[0]}
            for s in scored[:max_results]
        ]
