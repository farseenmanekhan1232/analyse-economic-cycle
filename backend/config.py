import os
import logging
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_a, **_k):  # type: ignore
        return False

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=ENV_PATH)

API_KEY: str = os.getenv("API_KEY", "")
API_SECRET: str = os.getenv("API_SECRET", "")

DATA_DIR: Path = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH: Path = DATA_DIR / "economic_cycle.db"

DEFAULT_START_DATE = "2005-01-01"
KITE_HISTORICAL_CHUNK_DAYS = 2000
KITE_RATE_LIMIT_SLEEP = 0.35

# Kite-derived additional indices
INDIA_VIX_SYMBOL = "INDIAVIX"
NIFTY_50_SYMBOL = "NIFTY 50"

# yfinance global tickers (free, no API key needed)
YFINANCE_TICKERS: dict[str, str] = {
    "WTI_CRUDE": "CL=F",
    "US_VIX": "^VIX",
    "DOLLAR_INDEX": "DX-Y.NYB",
    "INRUSD": "INR=X",
    "US_10Y_YIELD": "^TNX",
    "NIFTY_50": "^NSEI",
}



SECTOR_INDICES: dict[str, str] = {
    "BANK": "NIFTY BANK",
    "IT": "NIFTY IT",
    "PHARMA": "NIFTY PHARMA",
    "FMCG": "NIFTY FMCG",
    "AUTO": "NIFTY AUTO",
    "METAL": "NIFTY METAL",
    "MEDIA": "NIFTY MEDIA",
    "REALTY": "NIFTY REALTY",
    "ENERGY": "NIFTY ENERGY",
    "INFRA": "NIFTY INFRA",
    "PSU_BANK": "NIFTY PSU BANK",
    "PVT_BANK": "NIFTY PVT BANK",
    "OIL_GAS": "NIFTY OIL AND GAS",
    "CONSUMER_DURABLES": "NIFTY CONSR DURBL",
    "HEALTHCARE": "NIFTY HEALTHCARE",
}




def validate_config() -> list[str]:
    issues: list[str] = []
    if not API_KEY:
        issues.append("API_KEY is not set")
    if not API_SECRET:
        issues.append("API_SECRET is not set")
    if API_KEY == API_SECRET:
        issues.append("API_KEY and API_SECRET appear identical — check your .env")
    return issues


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
