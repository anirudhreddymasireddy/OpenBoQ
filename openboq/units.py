"""Unit normalisation for German BoQs."""
from __future__ import annotations

import re

_ALIASES = {
    "m2": ["m2", "m²", "qm", "m^2", "m 2"],
    "m3": ["m3", "m³", "cbm", "m^3", "m 3"],
    "m": ["m", "lfm", "lfdm", "lfd.m", "lfd m", "meter"],
    "St": ["st", "stk", "stck", "stück", "st.", "stk.", "pcs", "pc", "nr"],
    "psch": ["psch", "pa", "pauschal", "psch.", "pausch", "ls", "pau"],
    "t": ["t", "to", "tn", "tonne", "tonnen"],
    "kg": ["kg"],
    "h": ["h", "std", "std.", "stunde", "stunden"],
    "d": ["d", "tag", "tage", "at"],
    "Wo": ["wo", "woche", "wochen", "wo."],
    "Mt": ["mt", "monat", "monate", "mon"],
    "m2Wo": ["m2wo", "m²wo", "m2xwo", "m² x wo", "m2 x wo"],
    "mWo": ["mwo", "m x wo", "mxwo", "lfmwo"],
    "StWo": ["stwo", "st x wo", "stxwo", "stkwo"],
    "StTag": ["sttag", "st x tag"],
    "Jahr": ["jahr", "jahre", "a"],
    "Satz": ["satz", "sa", "set", "sat"],
    "l": ["l", "ltr", "liter"],
    "km": ["km"],
    "ha": ["ha"],
    "LE": ["le", "lst", "leistungseinheit", "vb"],
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
    "mWo": "length_time", "StWo": "count_time", "StTag": "count_time", "Jahr": "time", "Satz": "count", "l": "volume_l",
    "km": "length", "ha": "area", "LE": "unit",
}


def family(u: str) -> str:
    return FAMILY.get(norm_unit(u), "unknown")


KNOWN = set(_ALIASES)


def is_known(u: str) -> bool:
    return norm_unit(u) in KNOWN
