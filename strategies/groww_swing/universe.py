"""Liquid sector ETF universe for Groww Cloud CNC swings.

Self-contained copy of Pulse sector ETF symbols — no backend imports.
"""

from __future__ import annotations

from typing import Dict, List

# Primary liquid ETF per sector (Groww trading_symbol / NSE symbol).
SECTOR_ETFS: Dict[str, List[str]] = {
    "AUTO": ["AUTOBEES", "AUTOIETF"],
    "PHARMA": ["PHARMABEES"],
    "HEALTHCARE": ["HEALTHIETF", "MOHEALTH"],
    "ENERGY": ["MOENERGY", "ENERGY"],
    "REALTY": ["MOREALTY"],
    "METAL": ["METALIETF", "GROWWMETAL"],
    "FMCG": ["FMCGIETF"],
    "BANK": ["BANKBEES", "BANKIETF"],
    "IT": ["ITBEES", "SBIETFIT"],
    "INFRA": ["INFRABEES", "MOINFRA"],
    "OIL_GAS": ["OILIETF"],
    "PSU_BANK": ["PSUBNKBEES"],
    "CONSUMER_DURABLES": ["CONSUMBEES"],
}

# Prefer index proxies when available on Groww CASH segment for cycle math.
SECTOR_INDEX_SYMBOLS: Dict[str, str] = {
    "BANK": "NIFTY BANK",
    "IT": "NIFTY IT",
    "PHARMA": "NIFTY PHARMA",
    "FMCG": "NIFTY FMCG",
    "AUTO": "NIFTY AUTO",
    "METAL": "NIFTY METAL",
    "REALTY": "NIFTY REALTY",
    "ENERGY": "NIFTY ENERGY",
    "INFRA": "NIFTY INFRA",
    "PSU_BANK": "NIFTY PSU BANK",
    "OIL_GAS": "NIFTY OIL AND GAS",
    "HEALTHCARE": "NIFTY HEALTHCARE",
    "CONSUMER_DURABLES": "NIFTY CONSR DURBL",
}

# Fallback: use the first ETF as the sector close series if index fetch fails.
SECTOR_PROXY_ETF: Dict[str, str] = {
    sector: symbols[0] for sector, symbols in SECTOR_ETFS.items() if symbols
}


def symbols_for_sectors(sectors: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for sector in sectors:
        for sym in SECTOR_ETFS.get(sector, []):
            if sym not in seen:
                seen.add(sym)
                out.append(sym)
    return out


def sector_for_symbol(symbol: str) -> str | None:
    upper = symbol.upper()
    for sector, symbols in SECTOR_ETFS.items():
        if upper in {s.upper() for s in symbols}:
            return sector
    return None
