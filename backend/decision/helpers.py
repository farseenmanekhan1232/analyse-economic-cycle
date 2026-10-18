"""Helpers: hold_for string → months; sector normalize re-exports registry."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional, Tuple

# Re-export registry as the single sector API used across Decision OS
from backend.decision.sectors import (  # noqa: F401
    normalize_sector,
    resolve_sector_id,
    sectors_match,
)


def parse_hold_months(hold_for: str) -> Tuple[float, float]:
    """Parse '6–9 months' / '12+ months' / '1-2 months' into (lo, hi)."""
    s = (hold_for or "").lower().strip()
    if not s or s == "unknown":
        return 6.0, 9.0
    if "12+" in s or "12 +" in s:
        return 12.0, 18.0
    m = re.search(r"(\d+)\s*[–\-to]+\s*(\d+)", s)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"(\d+)\s*months?", s)
    if m:
        n = float(m.group(1))
        return max(1.0, n - 1), n + 1
    return 6.0, 9.0


def hold_until_from_months(hi: float, from_day: Optional[date] = None) -> date:
    base = from_day or date.today()
    return base + timedelta(days=int(round(hi * 30)))


def format_display_date(value: Optional[date]) -> str:
    """Human date: 09 Apr 2027."""
    if not value:
        return "—"
    return value.strftime("%d %b %Y")


def normalize_instrument_key(value: str) -> str:
    """Lowercase alphanumeric key for matching holdings ↔ catalog picks."""
    s = (value or "").lower().strip()
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]+", "", s)


_FUND_SUFFIXES = (
    "directplangrowth",
    "directplanidcw",
    "directplan",
    "directgrowth",
    "regulargrowth",
    "regularplan",
    "growthoption",
    "growth",
)


def fund_core_key(value: str) -> str:
    """Strip plan/option suffixes so Direct Plan ≈ Direct Growth."""
    k = normalize_instrument_key(value)
    if not k:
        return ""
    changed = True
    while changed:
        changed = False
        for suf in _FUND_SUFFIXES:
            if k.endswith(suf) and len(k) > len(suf) + 6:
                k = k[: -len(suf)]
                changed = True
                break
    return k


# Tokens too generic to use for ownership matching
_INSTRUMENT_STOPWORDS = {
    "fund",
    "direct",
    "growth",
    "plan",
    "and",
    "the",
    "ltd",
    "limited",
    "mutual",
    "scheme",
    "option",
    "regular",
    "idcw",
    "capital",
    "opportunities",
    "prudential",
    "etf",
    "bees",
}


def instrument_keys_for_holding(
    *,
    instrument: str = "",
    external_key: str = "",
    scheme_code: Optional[str] = None,
    symbol: Optional[str] = None,
) -> set:
    keys = set()
    for raw in (external_key, scheme_code or "", symbol or ""):
        k = normalize_instrument_key(str(raw))
        if k and len(k) >= 3 and k not in _INSTRUMENT_STOPWORDS:
            keys.add(k)
    full = normalize_instrument_key(instrument or "")
    if full and len(full) >= 8:
        keys.add(full)
        core = fund_core_key(instrument or "")
        if core and len(core) >= 8:
            keys.add(core)
    name = (instrument or "").strip()
    if name:
        for part in re.split(r"[\s\-_/|]+", name):
            if not part or not re.match(r"^[A-Za-z0-9]{4,16}$", part):
                continue
            if part.isupper() or (part.isalnum() and len(part) <= 12 and part.isalpha()):
                k = normalize_instrument_key(part)
                if k and k not in _INSTRUMENT_STOPWORDS and len(k) >= 4:
                    if k in {"energy", "pharma", "healthcare", "auto", "bank", "metal", "realty"}:
                        continue
                    keys.add(k)
    return keys


def catalog_pick_keys(pick: dict, asset_class: str = "") -> set:
    keys = set()
    sym = normalize_instrument_key(str(pick.get("symbol") or ""))
    if sym and len(sym) >= 3 and sym not in _INSTRUMENT_STOPWORDS:
        keys.add(sym)
    name = str(pick.get("name") or "")
    full = normalize_instrument_key(name)
    if full and len(full) >= 8:
        keys.add(full)
        core = fund_core_key(name)
        if core and len(core) >= 8:
            keys.add(core)
    return keys


def keys_overlap(a: set, b: set) -> bool:
    if not a or not b:
        return False
    if a & b:
        return True
    long_a = {x for x in a if len(x) >= 10}
    long_b = {x for x in b if len(x) >= 10}
    for x in long_a:
        for y in long_b:
            if x in y or y in x:
                return True
    return False
