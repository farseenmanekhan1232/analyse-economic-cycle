import logging
from typing import Dict, List, Optional

from backend.data.kite_client import KiteClient
from backend.data.mf_client import MFClient

logger = logging.getLogger(__name__)


def _etf_symbol_map() -> Dict[str, List[str]]:
    """Prefer Decision OS catalog; fall back to legacy hardcodes if import fails."""
    try:
        from backend.decision.instruments import etf_symbols_by_sector

        return etf_symbols_by_sector()
    except Exception:
        return {
            "BANK": ["BANKIETF", "BANKBEES"],
            "IT": ["SBIETFIT", "ITBEES"],
            "PHARMA": ["PHARMABEES"],
            "FMCG": ["FMCGIETF"],
            "AUTO": ["AUTOIETF", "AUTOBEES"],
            "METAL": ["METALIETF", "GROWWMETAL"],
            "REALTY": ["MOREALTY"],
            "ENERGY": ["MOENERGY", "ENERGY"],
            "INFRA": ["INFRABEES", "MOINFRA"],
            "PSU_BANK": ["PSUBNKBEES"],
            "OIL_GAS": ["OILIETF"],
            "CONSUMER_DURABLES": ["CONSUMBEES"],
            "HEALTHCARE": ["HEALTHIETF", "MOHEALTH"],
        }


# Kept for import compatibility; built from catalog at call time
SECTOR_ETF_SYMBOLS: Dict[str, List[str]] = {}


class FundRecommender:
    """Map recommended sectors → tradable ETF/MF proxies.

    Does not rank alpha. Prefers catalog NSE symbols that quote successfully,
    then keyword-filtered Direct Growth equity MFs (index-named preferred).
    """

    def __init__(
        self,
        kite: Optional[KiteClient] = None,
        mf_client: Optional[MFClient] = None,
    ) -> None:
        self.kite = kite
        self.mf = mf_client

    def get_picks(self, recommended_sectors: List[str]) -> Dict[str, Dict]:
        if not self.kite or not self.mf:
            return {}

        try:
            self.mf.fetch_instruments()
        except Exception as e:
            logger.warning(f"MF instruments fetch failed: {e}")

        picks: Dict[str, Dict] = {}
        symbol_map = _etf_symbol_map()
        global SECTOR_ETF_SYMBOLS
        SECTOR_ETF_SYMBOLS = symbol_map

        for sector_key in recommended_sectors:
            etf_picks: List[dict] = []
            mf_picks: List[dict] = []

            symbols = symbol_map.get(sector_key, [])
            for symbol in symbols:
                try:
                    token = self.kite.get_instrument_token("NSE", symbol)
                    if token:
                        quote = self.kite.get_quote([f"NSE:{symbol}"])
                        if quote and quote.get(f"NSE:{symbol}"):
                            q = quote[f"NSE:{symbol}"]
                            etf_picks.append({
                                "symbol": symbol,
                                "name": q.get("name", symbol),
                                "ltp": q.get("last_price", 0),
                                "change_pct": q.get("change_percent", 0),
                                "source": "catalog",
                            })
                except Exception:
                    pass

            try:
                funds = self.mf.find_funds(sector_key, max_results=2)
                for f in funds:
                    mf_picks.append({
                        "name": f.get("name", ""),
                        "symbol": f.get("tradingsymbol", ""),
                        "nav": f.get("last_price", 0),
                        "amc": f.get("amc", ""),
                        "relevance": f.get("relevance"),
                        "source": "mf_keyword",
                    })
            except Exception as e:
                logger.warning(f"MF lookup failed for {sector_key}: {e}")

            if etf_picks or mf_picks:
                picks[sector_key] = {"etfs": etf_picks, "mfs": mf_picks}

        return picks
