"""Unit normalisation for German BoQs."""
from __future__ import annotations

import re

_ALIASES = {
    "m2": ["m2", "m²", "qm", "m^2", "m 2"],
    "m3": ["m3", "m³", "cbm", "m^3", "m 3"],
    "m": ["m", "lfm", "lfdm", "lfd.m", "lfd m", "meter"],
    "St": ["st", "stk", "stck", "stück", "st.", "stk.", "pcs", "pc", "nr"],
    "psch": ["psch", "pa", "pauschal", "psch.", "pausch", "ls"],
    "t": ["t", "to", "tonne", "tonnen"],
    "kg": ["kg"],
    "h": ["h", "std", "std.", "stunde", "stunden"],
    "d": ["d", "tag", "tage", "at"],
    "Wo": ["wo", "woche", "wochen", "wo."],
    "Mt": ["mt", "monat", "monate", "mon"],
    "m2Wo": ["m2wo", "m²wo", "m2xwo", "m² x wo", "m2 x wo"],
}
_LOOKUP = {a: k for k, al in _ALIASES.items() for a in al}


def norm_unit(u: str) -> str:
    if not u:
        return ""
    key = re.sub(r"\s+", " ", u.strip().lower())
    if key in _LOOKUP:
        return _LOOKUP[key]
    key2 = key.replace(" ", "")
    return _LOOKUP.get(key2, u.strip())


# Unit families: what a quantity physically is
FAMILY = {
    "m3": "volume", "m2": "area", "m": "length", "St": "count", "t": "mass", "kg": "mass",
    "psch": "lump", "h": "time", "d": "time", "Wo": "time", "Mt": "time", "m2Wo": "area_time",
}


def family(u: str) -> str:
    return FAMILY.get(norm_unit(u), "unknown")
