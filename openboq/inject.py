"""Plant known errors into a clean BoQ and record ground truth – our evaluation harness.

Each mutation mirrors a real-world defect class seen in tender/bid BoQs.
"""
from __future__ import annotations

import copy
import random
import re

from . import knowledge as K
from .model import BoQ, Item
from .units import family, norm_unit


def _wt(it: Item):
    return K.classify(it.short_text, it.long_text)


def _recalc(it: Item):
    if it.qty is not None and it.up is not None:
        it.it = round(it.qty * it.up, 2)


# ---------------------------------------------------------------- LV-level mutations (delete items)

def _del(boq: BoQ, pred) -> list[str]:
    gone = [i.oz for i in boq.items if pred(i)]
    boq.items = [i for i in boq.items if not pred(i)]
    return gone


def m_missing_formwork(boq, rng, used):
    members = []
    for member, rx in K.MEMBERS.items():
        fw = [i for i in boq.items if _wt(i) and _wt(i).key == "schalung" and re.search(rx, i.text.lower()) and i.oz not in used]
        conc = [i for i in boq.items if _wt(i) and _wt(i).key == "beton" and re.search(rx, i.short_text.lower())]
        if fw and conc:
            members.append((member, fw))
    if not members:
        return None
    member, fw = rng.choice(members)
    ids = {i.oz for i in fw}
    _del(boq, lambda i: i.oz in ids)
    return {"type": "missing_formwork", "oz": "", "rule": "R10", "match": f"Schalung fehlt: {member}", "deleted": sorted(ids)}


def _lv_delete(kind, rule_match, pred):
    def f(boq, rng, used):
        if not any(pred(i) for i in boq.items) or any(pred(i) and i.oz in used for i in boq.items):
            return None
        gone = _del(boq, pred)
        return {"type": kind, "oz": "", "rule": "R10", "match": rule_match, "deleted": gone}
    return f


m_missing_be = _lv_delete("missing_site_setup", "Baustelleneinrichtung fehlt",
                          lambda i: "baustelleneinrichtung" in i.short_text.lower())
m_missing_disposal = _lv_delete("missing_disposal", "Entsorgung Aushub fehlt",
                                lambda i: bool(_wt(i)) and _wt(i).key == "entsorgung")
m_missing_rebar = _lv_delete("missing_rebar", "Bewehrung fehlt",
                             lambda i: bool(_wt(i)) and _wt(i).key == "betonstahl")
m_missing_scaffold = _lv_delete("missing_scaffold", "Gerüst fehlt",
                                lambda i: bool(_wt(i)) and _wt(i).key == "geruest")
m_missing_waterproof = _lv_delete("missing_waterproofing", "Abdichtung erdberührter Bauteile fehlt",
                                  lambda i: bool(_wt(i)) and _wt(i).key == "abdichtung")

LV_MUTATIONS = [m_missing_formwork, m_missing_be, m_missing_disposal, m_missing_rebar, m_missing_scaffold, m_missing_waterproof]


# ---------------------------------------------------------------- item-level mutations

def _pick(boq, rng, used, pred):
    cands = [i for i in boq.items if i.oz not in used and not i.provisional and pred(i)]
    return rng.choice(cands) if cands else None


def m_arithmetic(boq, rng, used):
    it = _pick(boq, rng, used, lambda i: i.qty and i.up and i.qty * i.up > 500)
    if not it:
        return None
    kind = rng.choice(["digit", "factor"])
    if kind == "digit":   # transposed digits in the total
        s = f"{it.it:.2f}"
        digits = [k for k in range(len(s) - 1) if s[k].isdigit() and s[k + 1].isdigit() and s[k] != s[k + 1]]
        if digits:
            k = rng.choice(digits)
            s = s[:k] + s[k + 1] + s[k] + s[k + 2:]
            it.it = float(s)
        else:
            it.it = round(it.it * 1.1, 2)
    else:
        it.it = round(it.it * rng.choice([0.9, 1.1, 10, 0.1]), 2)
    return {"type": "arithmetic", "oz": it.oz, "rule": "R01"}


_SWAP = {"volume": "m2", "area": "St", "mass": "m3", "length": "t"}


def m_unit_swap(boq, rng, used):
    it = _pick(boq, rng, used, lambda i: _wt(i) and _wt(i).measurable and family(i.unit) in _SWAP)
    if not it:
        return None
    it.unit = _SWAP[family(it.unit)]
    return {"type": "unit_swap", "oz": it.oz, "rule": "R02"}


def m_lump_sum(boq, rng, used):
    it = _pick(boq, rng, used, lambda i: _wt(i) and _wt(i).measurable and family(i.unit) in ("volume", "area", "length", "mass"))
    if not it:
        return None
    total = it.total
    it.qty, it.unit, it.up, it.it, it.lump_sum = 1.0, "psch", round(total, 2), round(total, 2), True
    return {"type": "lump_sum", "oz": it.oz, "rule": "R03"}


def m_duplicate(boq, rng, used):
    it = _pick(boq, rng, used, lambda i: i.qty and i.qty > 1)
    if not it:
        return None
    dup = copy.deepcopy(it)
    sec = it.oz.rsplit(".", 1)[0]
    existing = {i.oz for i in boq.items}
    n = 9000
    while f"{sec}.{n:04d}" in existing:
        n += 10
    dup.oz = f"{sec}.{n:04d}"
    dup.raw_id = ""
    boq.items.append(dup)
    used.add(it.oz)
    return {"type": "duplicate", "oz": dup.oz, "rule": "R04"}


def m_price_high(boq, rng, used):
    def ok(i):
        wt = _wt(i)
        return wt and i.up and norm_unit(i.unit) in wt.price
    it = _pick(boq, rng, used, ok)
    if not it:
        return None
    hi = _wt(it).price[norm_unit(it.unit)][1]
    it.up = round(max(it.up * rng.uniform(2.2, 3.0), hi * rng.uniform(1.6, 2.0)), 2)
    _recalc(it)
    return {"type": "price_outlier_high", "oz": it.oz, "rule": "R05"}


def m_price_low(boq, rng, used):
    def ok(i):
        wt = _wt(i)
        return wt and i.up and norm_unit(i.unit) in wt.price
    it = _pick(boq, rng, used, ok)
    if not it:
        return None
    lo = _wt(it).price[norm_unit(it.unit)][0]
    it.up = round(lo * rng.uniform(0.15, 0.5), 2)
    _recalc(it)
    return {"type": "price_outlier_low", "oz": it.oz, "rule": "R05"}


_VAGUE_INSERTS = [
    " Ausführung nach Angabe der Bauleitung.",
    " Zusätzliche Maßnahmen nach Erfordernis.",
    " Fabrikat nach Wahl des AN.",
    " Einschließlich aller erforderlichen Nebenleistungen.",
    " Ggf. Mehraufwand für Erschwernisse.",
]


def m_vague(boq, rng, used):
    it = _pick(boq, rng, used, lambda i: len(i.long_text) > 40)
    if not it:
        return None
    if re.search(r"d = \d", it.long_text) and rng.random() < 0.4:
        it.long_text = re.sub(r"d = (\d)", r"d = ca. \1", it.long_text, count=1)
    else:
        it.long_text = it.long_text.rstrip() + rng.choice(_VAGUE_INSERTS)
    return {"type": "vague_wording", "oz": it.oz, "rule": "R08"}


_REMOVE = {
    "Festigkeitsklasse": r"C\d{1,2}/\d{2}",
    "Expositionsklasse": r"\bX(?:0|C[1-4]|D[1-3]|S[1-3]|F[1-4]|A[1-3]|M[1-3])\b",
    "Wanddicke": r"d\s?=\s?\d+(?:,\d+)?\s?cm",
    "Dämmdicke": r"d\s?=\s?\d+\s?mm",
    "Wärmeleitfähigkeit": r"WLS\s?\d+",
    "Stahlsorte": r"B\s?500\s?[AB]?",
    "Lastklasse": r"Lastklasse\s?\d",
    "Nennweite": r"DN\s?\d+",
    "Wassereinwirkungsklasse": r"Wassereinwirkungsklasse\s+W\d\.\d-E\s+nach\s+DIN 18533",
}


def m_missing_param(boq, rng, used):
    cands = []
    for i in boq.items:
        if i.oz in used or i.provisional:
            continue
        wt = _wt(i)
        if not wt or not wt.params:
            continue
        for name, rx, _ in wt.params:
            if re.search(rx, i.text.lower()):
                cands.append((i, name, rx))
    if not cands:
        return None
    cands = [c for c in cands if c[1] in _REMOVE]
    if not cands:
        return None
    it, name, rx = rng.choice(cands)
    before = (it.short_text, it.long_text)
    rm = r",?\s*(?:" + _REMOVE[name] + r")"
    it.short_text = re.sub(rm, "", it.short_text, flags=re.IGNORECASE).strip(" ,")
    it.long_text = re.sub(rm, "", it.long_text, flags=re.IGNORECASE)
    if re.search(rx, it.text.lower()):      # could not cleanly remove – undo and skip
        it.short_text, it.long_text = before
        return None
    return {"type": "missing_parameter", "oz": it.oz, "rule": "R09", "param": name}


def m_outdated(boq, rng, used):
    it = _pick(boq, rng, used, lambda i: "homogenbereich" in i.long_text.lower())
    if not it:
        return None
    it.long_text = re.sub(r"Homogenbereich \w+( gemäß Geotechnischem Bericht vom [\d.]+)?", "Bodenklasse 3–5 nach DIN 18300",
                          it.long_text, count=1)
    return {"type": "outdated_norm", "oz": it.oz, "rule": "R11"}


def m_zero_qty(boq, rng, used):
    it = _pick(boq, rng, used, lambda i: i.qty and i.qty > 1)
    if not it:
        return None
    it.qty, it.it = 0.0, 0.0
    return {"type": "zero_quantity", "oz": it.oz, "rule": "R06"}


ITEM_MUTATIONS = [m_arithmetic, m_unit_swap, m_lump_sum, m_duplicate, m_price_high, m_price_low,
                  m_vague, m_missing_param, m_outdated, m_zero_qty]


def inject(clean: BoQ, n_item: int = 10, n_lv: int = 2, seed: int = 0) -> tuple[BoQ, list[dict]]:
    rng = random.Random(seed)
    boq = copy.deepcopy(clean)
    used: set[str] = set()
    truth: list[dict] = []

    for fn in rng.sample(LV_MUTATIONS, k=min(n_lv, len(LV_MUTATIONS))):
        g = fn(boq, rng, used)
        if g:
            truth.append(g)

    pool = ITEM_MUTATIONS * 3
    rng.shuffle(pool)
    for fn in pool:
        if sum(1 for t in truth if t["oz"]) >= n_item:
            break
        g = fn(boq, rng, used)
        if g:
            used.add(g["oz"])
            truth.append(g)
    boq.items.sort(key=lambda i: [int(p) if p.isdigit() else p for p in i.oz.split(".")])
    return boq, truth
