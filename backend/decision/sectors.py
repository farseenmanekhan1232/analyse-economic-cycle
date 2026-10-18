"""Canonical sector registry — single source of truth for ids, aliases, Kite indices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from backend.config import SECTOR_INDICES


@dataclass(frozen=True)
class SectorDef:
    id: str
    display_name: str
    aliases: Tuple[str, ...] = ()
    kite_index: Optional[str] = None


# Order matters for display; ids must match pipeline / SECTOR_INDICES keys where possible.
_SECTOR_DEFS: Tuple[SectorDef, ...] = (
    SectorDef("AUTO", "Auto", ("auto", "automotive", "automobile"), "NIFTY AUTO"),
    SectorDef("BANK", "Bank", ("bank", "banking", "banks"), "NIFTY BANK"),
    SectorDef("PSU_BANK", "PSU Bank", ("psu_bank", "psu bank", "psubank"), "NIFTY PSU BANK"),
    SectorDef("PVT_BANK", "Private Bank", ("pvt_bank", "private bank", "pvtbank"), "NIFTY PVT BANK"),
    SectorDef("IT", "IT", ("it", "technology", "tech", "infosys"), "NIFTY IT"),
    SectorDef(
        "PHARMA",
        "Pharma",
        ("pharma", "pharmaceutical", "pharmaceuticals"),
        "NIFTY PHARMA",
    ),
    SectorDef(
        "HEALTHCARE",
        "Healthcare",
        ("healthcare", "health care", "health"),
        "NIFTY HEALTHCARE",
    ),
    SectorDef("FMCG", "FMCG", ("fmcg", "consumption", "consumer staples"), "NIFTY FMCG"),
    SectorDef("METAL", "Metal", ("metal", "metals", "commodity", "commodities"), "NIFTY METAL"),
    SectorDef("MEDIA", "Media", ("media",), "NIFTY MEDIA"),
    SectorDef("REALTY", "Realty", ("realty", "real estate", "real_estate", "property"), "NIFTY REALTY"),
    SectorDef("ENERGY", "Energy", ("energy", "power"), "NIFTY ENERGY"),
    SectorDef("INFRA", "Infra", ("infra", "infrastructure"), "NIFTY INFRA"),
    SectorDef("OIL_GAS", "Oil & Gas", ("oil", "oil_gas", "oil and gas", "oilgas"), "NIFTY OIL AND GAS"),
    SectorDef(
        "CONSUMER_DURABLES",
        "Consumer Durables",
        ("consumer", "consumer_durables", "consumer durables", "durables"),
        "NIFTY CONSR DURBL",
    ),
)

# Labels that intentionally do not map to a scored sector
_UNMAPPED_ALIASES = {"thematic", "sectoral", "multi", "flexi", "hybrid", "other", "unknown"}

# Holdings / scores in either id should join each other
_EQUIVALENT: Dict[str, Set[str]] = {
    "PHARMA": {"PHARMA", "HEALTHCARE"},
    "HEALTHCARE": {"PHARMA", "HEALTHCARE"},
}

SECTORS: Dict[str, SectorDef] = {s.id: s for s in _SECTOR_DEFS}

# Build alias → id (lowercase keys). Prefer longer aliases first when resolving.
_ALIAS_TO_ID: Dict[str, str] = {}
for s in _SECTOR_DEFS:
    _ALIAS_TO_ID[s.id.lower()] = s.id
    for a in s.aliases:
        _ALIAS_TO_ID[a.lower().replace("-", " ").strip()] = s.id
        _ALIAS_TO_ID[a.lower().replace(" ", "_").strip()] = s.id
        _ALIAS_TO_ID[a.lower().replace("-", "_").strip()] = s.id

def all_sector_ids() -> List[str]:
    return [s.id for s in _SECTOR_DEFS]


def display_name(sector_id: str) -> str:
    s = SECTORS.get(sector_id)
    return s.display_name if s else (sector_id or "").replace("_", " ").title()


def kite_index_for(sector_id: str) -> Optional[str]:
    s = SECTORS.get(sector_id)
    if s and s.kite_index:
        return s.kite_index
    return SECTOR_INDICES.get(sector_id)


def equivalent_ids(sector_id: str) -> Set[str]:
    if not sector_id:
        return set()
    return set(_EQUIVALENT.get(sector_id, {sector_id}))


def resolve_sector_id(label: str) -> Tuple[Optional[str], str]:
    """
    Map free-text sector label → (sector_id | None, confidence).
    confidence: exact | alias | none
    """
    raw = (label or "").strip()
    if not raw:
        return None, "none"
    key = raw.lower().replace("-", "_").replace(" ", "_")
    spaced = raw.lower().replace("-", " ").replace("_", " ").strip()

    if key in _UNMAPPED_ALIASES or spaced in _UNMAPPED_ALIASES:
        return None, "none"

    if key.upper() in SECTORS:
        return key.upper(), "exact"

    for candidate in (raw.lower(), key, spaced, spaced.replace(" ", "_")):
        hit = _ALIAS_TO_ID.get(candidate)
        if hit:
            return hit, "alias"

    # Substring alias (longest first)
    alias_keys = sorted(_ALIAS_TO_ID.keys(), key=len, reverse=True)
    hay = raw.lower()
    for a in alias_keys:
        if len(a) >= 3 and a in hay and _ALIAS_TO_ID[a] not in (""):
            # avoid matching tiny tokens inside unrelated words
            if a in _UNMAPPED_ALIASES:
                continue
            return _ALIAS_TO_ID[a], "alias"

    # Unknown UPPER_SNAKE that looks like a sector id — keep for inspectability
    guess = raw.upper().replace(" ", "_").replace("-", "_")
    if guess in SECTORS:
        return guess, "exact"
    return None, "none"


def normalize_sector(label: str) -> str:
    """Canonical sector id string, or '' if unmapped/empty."""
    sid, _ = resolve_sector_id(label)
    return sid or ""


def sectors_match(a: str, b: str) -> bool:
    """Exact sector_id match including PHARMA↔HEALTHCARE equivalence."""
    id_a, _ = resolve_sector_id(a)
    id_b, _ = resolve_sector_id(b)
    if not id_a or not id_b:
        return False
    return id_b in equivalent_ids(id_a) or id_a in equivalent_ids(id_b)


def sector_registry_export() -> List[Dict]:
    """Inspectable dump for debug UI / API."""
    out = []
    for s in _SECTOR_DEFS:
        out.append(
            {
                "id": s.id,
                "display_name": s.display_name,
                "aliases": list(s.aliases),
                "kite_index": s.kite_index or SECTOR_INDICES.get(s.id),
                "equivalents": sorted(equivalent_ids(s.id)),
            }
        )
    return out
