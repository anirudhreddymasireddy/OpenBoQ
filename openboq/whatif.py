"""What-if analyses (milestone 5): how material prices, alternatives and quantities change the bid.

Each work type gets a cost structure: shares of the unit price driven by steel, concrete/cement, bitumen,
diesel/energy, disposal fees, plastics, aggregates, timber and wages (typical German civil-works calculations –
editable assumptions, shown in the app). A scenario moves drivers by a percentage:

    new unit price = unit price × (1 + Σ share_driver × change_driver)

Contract context decides who pays: under a fixed price without a price escalation clause the contractor carries the
whole increase; with a material price escalation clause (Stoffpreisgleitklausel, Formblatt 225) the named materials
are largely passed on.

Alternatives are concrete spec swaps with factor tables (concrete class, disposal class, pipe material, asphalt
thickness) – candidates for a value-engineering offer (Nebenangebot) or a risk to price in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import knowledge as K
from .model import BoQ, Item
from .units import norm_unit

DRIVERS = {   # key: (German, English)
    "steel": ("Stahl / Betonstahl", "Steel / rebar"),
    "concrete": ("Beton / Zement", "Concrete / cement"),
    "bitumen": ("Bitumen / Asphalt", "Bitumen / asphalt"),
    "fuel": ("Diesel / Energie", "Diesel / energy"),
    "disposal": ("Deponie / Entsorgung", "Landfill / disposal"),
    "plastic": ("Kunststoffe (PE, PVC, EPS)", "Plastics (PE, PVC, EPS)"),
    "aggregates": ("Kies / Schotter / Sand", "Gravel / crushed stone / sand"),
    "timber": ("Holz / Schalung", "Timber / formwork"),
    "labour": ("Lohn", "Wages"),
}

# share of the unit price per driver (rest: plant depreciation, overheads, profit – not moved by the scenario)
SHARES: dict[str, dict[str, float]] = {
    "be": {"labour": 0.40, "fuel": 0.10},
    "schalung": {"timber": 0.25, "labour": 0.55},
    "betonstahl": {"steel": 0.55, "labour": 0.30, "fuel": 0.02},
    "sauberkeit": {"concrete": 0.50, "labour": 0.20, "fuel": 0.03},
    "fertigteil": {"concrete": 0.30, "steel": 0.15, "labour": 0.20, "fuel": 0.05},
    "beton": {"concrete": 0.45, "labour": 0.25, "fuel": 0.03},
    "oberboden": {"fuel": 0.30, "labour": 0.35},
    "aushub": {"fuel": 0.30, "labour": 0.35},
    "entsorgung": {"disposal": 0.60, "fuel": 0.20, "labour": 0.10},
    "verfuellen": {"aggregates": 0.35, "fuel": 0.20, "labour": 0.25},
    "planum": {"fuel": 0.30, "labour": 0.40},
    "tragschicht": {"aggregates": 0.45, "fuel": 0.15, "labour": 0.20},
    "wasserhaltung": {"fuel": 0.35, "labour": 0.30},
    "mauerwerk": {"concrete": 0.30, "labour": 0.45},
    "sturz": {"concrete": 0.30, "steel": 0.10, "labour": 0.35},
    "abdichtung": {"bitumen": 0.35, "labour": 0.40},
    "daemmung": {"plastic": 0.40, "labour": 0.35},
    "rohr": {"plastic": 0.40, "aggregates": 0.05, "fuel": 0.05, "labour": 0.30},
    "drainage": {"plastic": 0.25, "aggregates": 0.20, "labour": 0.30},
    "geruest": {"steel": 0.10, "labour": 0.50, "fuel": 0.05},
    "strasse": {"bitumen": 0.30, "aggregates": 0.20, "fuel": 0.12, "labour": 0.20},
}
DEFAULT_SHARES = {"labour": 0.40, "fuel": 0.05}

ESCALATION_RX = re.compile(r"stoffpreisgleit|preisgleitklausel|preisgleitung|formblatt\s*225|lohngleit|"
                           r"price\s+(?:adjustment|escalation)\s+clause", re.I)
FIXED_RX = re.compile(r"festpreis|preisbindung|preise\s+(?:sind|gelten)\s+(?:fest|bis\s+zur)|fixed\s+price|"
                      r"keine\s+preisgleitung|ohne\s+preisgleit", re.I)
ESCALATED = {"steel", "bitumen", "fuel", "plastic"}   # materials typically named in Formblatt 225


def shares(it: Item) -> tuple[dict[str, float], str]:
    """Cost structure of an item and the work type it was based on."""
    wt = K.classify(it.short_text, it.long_text)
    if wt is None:
        low = it.short_text.lower()
        if re.search(r"stahl|stütze|träger|geländer", low):
            return {"steel": 0.40, "labour": 0.35}, "Stahlbau"
        return dict(DEFAULT_SHARES), ""
    sh = dict(SHARES.get(wt.key, DEFAULT_SHARES))
    if wt.key == "rohr":
        low = it.text.lower()
        if re.search(r"guss|stahlrohr|duktil", low):
            sh["steel"], sh["plastic"] = sh.pop("plastic"), 0.0
        elif re.search(r"steinzeug|beton|stb", low):
            sh["concrete"], sh["plastic"] = sh.pop("plastic"), 0.0
    return {k: v for k, v in sh.items() if v}, wt.label


def unit_price(it: Item, sugg: dict | None = None) -> tuple[float | None, bool]:
    """Unit price of the item, or the comparable-price suggestion when the BoQ is unpriced (flag: suggested)."""
    if it.up and it.up > 0:
        return it.up, False
    if it.it and it.qty:
        return it.it / it.qty, False
    s = (sugg or {}).get(it.oz)
    return (s.median, True) if s else (None, False)


def contract_context(boq: BoQ) -> dict:
    """Is there a price escalation clause, or an explicit fixed price? Searched in notes and item texts."""
    txt = " ".join([n.get("text", "") for n in boq.notes] + [i.text for i in boq.items])
    fixed = bool(FIXED_RX.search(txt))
    # "ohne Preisgleitung" / "keine Preisgleitklausel" names the clause only to exclude it
    positive = re.sub(r"(?:ohne|keine?n?|nicht|without|no)\s+(?:\w+\s+){0,2}?(?:stoff)?preisgleit\w*", " ", txt, flags=re.I)
    return {"escalation": bool(ESCALATION_RX.search(positive)), "fixed": fixed}


@dataclass
class ScenarioResult:
    base_total: float
    new_total: float
    by_driver: dict            # driver -> € change
    items: list[dict]          # per item
    priced: int                # items with a price (own or suggested)
    suggested: int             # of which with a suggested price
    passed_on: float           # € covered by a price escalation clause
    carried: float             # € the contractor carries: material change not passed on + uncovered overheads
    material: float = 0.0      # € extra cost from price changes (all drivers)
    uncovered: float = 0.0     # € overheads no longer recovered because quantities fall
    qty_revenue: float = 0.0   # € revenue change from changed quantities at bid prices


def run_scenario(boq: BoQ, changes: dict[str, float], sugg: dict | None = None, qty_ratio: dict | None = None,
                 escalation: bool | None = None, overhead_share: float = 0.10) -> ScenarioResult:
    """changes: driver -> relative change (0.15 = +15 %). qty_ratio: oz -> quantity factor (e.g. from history).
    For unit-price items a quantity change moves revenue and variable cost alike; the overhead share spread over the
    unit price is fixed, so a reduced quantity leaves it uncovered (shown as a cost)."""
    if escalation is None:
        escalation = contract_context(boq)["escalation"]
    base = new = passed = unc = qrev = 0.0
    by_driver = {d: 0.0 for d in DRIVERS}
    rows = []
    priced = suggested = 0
    for it in boq.items:
        up, is_sugg = unit_price(it, sugg)
        if up is None or not it.qty:
            continue
        priced += 1
        suggested += is_sugg
        sh, label = shares(it)
        q0 = it.qty
        qf = (qty_ratio or {}).get(it.oz, 1.0) if norm_unit(it.unit) != "psch" else 1.0
        q1 = q0 * qf
        delta_up = 0.0
        for d, s in sh.items():
            c = changes.get(d, 0.0)
            if c:
                by_driver[d] += up * s * c * q1
                delta_up += up * s * c
                if escalation and d in ESCALATED:
                    passed += up * s * c * q1
        cost0 = up * q0
        cost1 = (up + delta_up) * q1
        uncovered_oh = max(0.0, (q0 - q1) * up * overhead_share)    # fixed overheads no longer recovered
        base += cost0
        new += cost1 + uncovered_oh
        unc += uncovered_oh
        qrev += (q1 - q0) * up
        rows.append({"oz": it.oz, "short_text": it.short_text, "unit": it.unit, "qty": q0, "qty_new": q1, "up": up,
                     "up_new": up + delta_up, "suggested": is_sugg, "basis": label, "shares": sh,
                     "delta": cost1 + uncovered_oh - cost0, "delta_material": delta_up * q1})
    material = sum(by_driver.values())
    return ScenarioResult(base_total=base, new_total=new, by_driver=by_driver, items=rows, priced=priced,
                          suggested=suggested, passed_on=passed, carried=material - passed + unc, material=material,
                          uncovered=unc, qty_revenue=qrev)


def sensitivity(boq: BoQ, sugg: dict | None = None, step: float = 0.10) -> list[tuple[str, float]]:
    """€ effect of +step on each driver alone – which price matters most for this bid."""
    out = []
    for d in DRIVERS:
        r = run_scenario(boq, {d: step}, sugg, escalation=False)
        out.append((d, r.by_driver[d]))
    return sorted(out, key=lambda t: -abs(t[1]))


# ---------------------------------------------------------------- alternatives (spec swaps)

CONCRETE = ["C12/15", "C16/20", "C20/25", "C25/30", "C30/37", "C35/45", "C40/50", "C45/55", "C50/60"]
CONCRETE_F = {"C12/15": 0.86, "C16/20": 0.90, "C20/25": 0.94, "C25/30": 1.00, "C30/37": 1.07, "C35/45": 1.15,
              "C40/50": 1.23, "C45/55": 1.32, "C50/60": 1.42}          # concrete material price relative to C25/30
DISPOSAL = [("Z0", 1.0), ("Z1.1", 1.35), ("Z1.2", 1.6), ("Z2", 2.2), ("DK 0", 1.0), ("DK I", 1.7), ("DK II", 2.6)]
PIPES = {"PVC": 1.0, "PP": 1.15, "PE": 1.25, "Steinzeug": 1.45, "Guss": 2.2}


def _row(it, up, what_de, what_en, new_up, kind, note_de, note_en):
    return {"oz": it.oz, "short_text": it.short_text, "current": what_de[0], "alternative": what_de[1],
            "current_en": what_en[0], "alternative_en": what_en[1], "up": up, "up_new": new_up,
            "delta_up": new_up - up, "delta_total": (new_up - up) * (it.qty or 0), "kind": kind,
            "note_de": note_de, "note_en": note_en}


def alternatives(boq: BoQ, sugg: dict | None = None) -> list[dict]:
    return [a for a in _alternatives(boq, sugg) if abs(a["delta_total"]) >= 1]


def _alternatives(boq: BoQ, sugg: dict | None = None) -> list[dict]:
    out = []
    for it in boq.items:
        up, _ = unit_price(it, sugg)
        if up is None or not it.qty:
            continue
        txt = it.text
        sh, _ = shares(it)
        # concrete class one step up / down
        m = re.search(r"\bC\s?(\d{2})\s?/\s?(\d{2})\b", txt)
        if m and sh.get("concrete"):
            cur = f"C{m.group(1)}/{m.group(2)}"
            if cur in CONCRETE:
                k = CONCRETE.index(cur)
                for j, kind in ((k - 1, "nebenangebot"), (k + 1, "risk")):
                    if 0 <= j < len(CONCRETE) and CONCRETE[j] != "C12/15":
                        alt = CONCRETE[j]
                        new = up * (1 + sh["concrete"] * (CONCRETE_F[alt] / CONCRETE_F[cur] - 1))
                        out.append(_row(it, up, (cur, alt), (cur, alt), new, kind,
                                        "Nur mit statischem Nachweis / Freigabe (Nebenangebot)" if j < k else
                                        "Falls Statik oder Expositionsklasse eine höhere Klasse verlangt",
                                        "Only with structural proof / approval (alternative offer)" if j < k else
                                        "If structure or exposure class requires a higher class"))
        # disposal class: what if the material is more contaminated than tendered
        m = re.search(r"\b(Z\s?0|Z\s?1\.1|Z\s?1\.2|Z\s?2|DK\s?0|DK\s?I{1,2})\b", txt)
        if m and sh.get("disposal"):
            cur = re.sub(r"\s", "", m.group(1)).replace("DK", "DK ")
            seq = [d for d in DISPOSAL if d[0].startswith(cur[:2])]
            names = [d[0] for d in seq]
            if cur in names and names.index(cur) + 1 < len(names):
                f0 = dict(seq)[cur]
                alt, f1 = seq[names.index(cur) + 1]
                new = up * (1 + sh["disposal"] * (f1 / f0 - 1))
                out.append(_row(it, up, (cur, alt), (cur, alt), new, "risk",
                                "Höher belastetes Material als ausgeschrieben → Nachtrag nach § 2 Abs. 5/6 anmelden; "
                                "Beprobung vereinbaren",
                                "More contaminated material than tendered → announce a change order under § 2(5)/(6); "
                                "agree on sampling"))
        # pipe material
        if sh.get("plastic") and K.classify(it.short_text) and K.classify(it.short_text).key == "rohr":
            low = txt.lower()
            cur = "PE" if re.search(r"\bpe\b|pe-hd|pe 100|pe100", low) else "PP" if re.search(r"\bpp\b", low) else \
                "PVC" if "pvc" in low else ""
            if cur:
                for alt in ("PVC", "PP", "PE"):
                    if alt != cur:
                        new = up * (1 + sh["plastic"] * (PIPES[alt] / PIPES[cur] - 1))
                        if new < up:
                            out.append(_row(it, up, (cur, alt), (cur, alt), new, "nebenangebot",
                                            "Gleichwertigkeit (Druckstufe, Ringsteifigkeit, Zulassung) nachweisen",
                                            "Prove equivalence (pressure class, ring stiffness, approval)"))
        # vitrified clay sewer pipe -> PP / PVC (common alternative offer for gravity sewers)
        wt_ = K.classify(it.short_text)
        if wt_ and wt_.key == "rohr" and re.search(r"steinzeug", txt, re.I) and sh.get("concrete"):
            for alt in ("PP", "PVC"):
                new = up * (1 + sh["concrete"] * (PIPES[alt] / PIPES["Steinzeug"] - 1))
                out.append(_row(it, up, ("Steinzeug", alt), ("vitrified clay", alt), new, "nebenangebot",
                                "Nur für Freispiegelkanäle; Zulassung, Ringsteifigkeit (SN) und Zustimmung des AG nötig",
                                "Gravity sewers only; approval, ring stiffness (SN) and the client's consent required"))
        # natural gravel / crushed stone -> recycled aggregate (Ersatzbaustoffverordnung)
        if sh.get("aggregates") and wt_ and wt_.key in ("verfuellen", "tragschicht") and \
                re.search(r"kies|schotter|sand|mineralgemisch", txt, re.I) and not re.search(r"\brc\b|recycling", txt, re.I):
            new = up * (1 + sh["aggregates"] * (0.75 - 1))
            out.append(_row(it, up, ("Naturbaustoff", "RC-Baustoff"), ("natural aggregate", "recycled aggregate"), new,
                            "nebenangebot", "RC-Material nach EBV (Materialklasse RC-1) mit Güteüberwachung; Einbauort prüfen",
                            "Recycled material to EBV (class RC-1) with quality control; check where it may be placed"))
        # asphalt thickness ±1 cm
        m = re.search(r"(?:dicke|d\s?=)\s*(\d+(?:[.,]\d)?)\s*cm", txt, re.I)
        if m and sh.get("bitumen") and norm_unit(it.unit) == "m2":
            d0 = float(m.group(1).replace(",", "."))
            if 2 <= d0 <= 30:
                mat = sh.get("bitumen", 0) + sh.get("aggregates", 0)
                for d1, kind in ((d0 + 1, "risk"),):
                    new = up * (1 + mat * (d1 / d0 - 1))
                    out.append(_row(it, up, (f"{d0:g} cm", f"{d1:g} cm"), (f"{d0:g} cm", f"{d1:g} cm"), new, kind,
                                    "Einbautoleranz / Mehrdicke wird bei m²-Abrechnung nicht vergütet",
                                    "Laying tolerance / extra thickness is not paid when billed per m²"))
    return out
