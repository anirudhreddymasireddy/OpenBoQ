"""Deterministic, explainable checks on a bill of quantities.

Every flag carries: the rule, a legal/normative reference, a suggested fix, and an
estimated € exposure (transparent heuristics, see RISK below – tune with the sponsor).
Texts are German (field values) with English versions in Flag.en for the language toggle.
"""
from __future__ import annotations

import re
from collections import defaultdict

from rapidfuzz import fuzz

from . import knowledge as K
from .fmt import de
from .fmt import en as E
from .model import BoQ, Flag, Item
from .units import family, norm_unit

# Share of the item value assumed to be at risk, per finding type (heuristic, configurable).
RISK = {
    "unit_mismatch": 0.25,
    "lump_sum": 0.15,
    "vague": 0.08,
    "vague_cap": 0.20,
    "missing_param": 0.10,
    "outdated_norm": 0.15,
}

ARITH_TOL_ABS = 0.02     # EUR
ARITH_TOL_REL = 0.0005


def _nums(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", s))


def _wt(item: Item):
    return K.classify(item.short_text, item.long_text)


def _label_en(wt) -> str:
    return K.WT_LABEL_EN.get(wt.key, wt.label)


def _price_only(boq: BoQ) -> bool:
    """D84-style bid files carry only OZ + prices; texts and units live in the tender LV."""
    return bool(boq.items) and not any(i.short_text.strip() for i in boq.items)


# ---------------------------------------------------------------- item-level rules

def check_arithmetic(boq: BoQ) -> list[Flag]:
    out = []
    for it in boq.items:
        if it.qty is None or it.up is None or it.it is None:
            continue
        expected = round(it.qty * it.up, 2)
        diff = it.it - expected
        if abs(diff) > max(ARITH_TOL_ABS, abs(expected) * ARITH_TOL_REL):
            out.append(Flag(
                "R01", "Rechenfehler Menge × EP ≠ GP", "high",
                f"{it.qty:g} {it.unit} × {de(it.up, 2)} € = {de(expected, 2)} €, im LV steht {de(it.it, 2)} € "
                f"(Differenz {de(diff, 2)} €).",
                oz=it.oz, reference="VOB/A § 16c Abs. 2 (Prüfung der Angebote, maßgeblich ist der EP)",
                exposure_eur=abs(diff), suggestion=f"GP auf {de(expected, 2)} € korrigieren.",
                en=dict(title="Calculation error: qty × unit price ≠ total",
                        message=f"{it.qty:g} {it.unit} × €{E(it.up)} = €{E(expected)}, but the BoQ says €{E(it.it)} "
                                f"(difference €{E(diff)}).",
                        suggestion=f"Correct the total to €{E(expected)} (the unit price governs).")))
    return out


def check_units(boq: BoQ) -> list[Flag]:
    out = []
    price_only = _price_only(boq)
    for it in boq.items:
        if not it.unit:
            if price_only:
                continue
            out.append(Flag("R12", "Einheit fehlt", "high", "Position ohne Mengeneinheit – nicht abrechenbar.",
                            oz=it.oz, reference="VOB/A § 7 Abs. 1 (eindeutige Leistungsbeschreibung)",
                            suggestion="Einheit ergänzen.",
                            en=dict(title="Unit missing", message="Item has no unit of measurement – it cannot be billed.",
                                    suggestion="Add the unit.")))
            continue
        wt = _wt(it)
        if not wt:
            continue
        fam = family(it.unit)
        units = "/".join(sorted(wt.price)) or "m2/m3"
        if fam == "lump" and wt.measurable:
            out.append(Flag(
                "R03", "Pauschale für messbare Leistung", "medium",
                f"„{it.short_text}“ ist eine messbare Leistung ({wt.label}), wird aber pauschal ({it.unit}) ausgeschrieben. "
                "Mengenänderungen lassen sich so kaum nachvollziehen und führen zu Streit über Mehr-/Mindermengen.",
                oz=it.oz, reference="VOB/A § 4 Abs. 1 (Einheitspreisvertrag als Regel); VOB/B § 2 Abs. 7",
                exposure_eur=RISK["lump_sum"] * it.total,
                suggestion=f"Als Einheitspreisposition mit Einheit {units} und Vordersatz ausschreiben.",
                en=dict(title="Lump sum for measurable work",
                        message=f"'{it.short_text}' is measurable work ({_label_en(wt)}) but is tendered as a lump sum ({it.unit}). "
                                "Quantity changes can hardly be traced and lead to disputes about extra/reduced quantities.",
                        suggestion=f"Tender it as a unit-price item in {units} with a quantity.")))
        elif fam not in wt.families and fam != "unknown":
            usual = ", ".join(wt.price) or wt.families[0]
            out.append(Flag(
                "R02", "Einheit passt nicht zur Leistung", "high",
                f"„{it.short_text}“ ({wt.label}) in Einheit „{it.unit}“ – erwartet: {', '.join(wt.families)}.",
                oz=it.oz, reference=f"VOB/C {wt.norm}, Abschnitt 0.5 (Abrechnungseinheiten)",
                exposure_eur=RISK["unit_mismatch"] * it.total,
                suggestion=f"Einheit prüfen – üblich: {usual}.",
                en=dict(title="Unit does not fit the work",
                        message=f"'{it.short_text}' ({_label_en(wt)}) is measured in '{it.unit}' – expected: {', '.join(wt.families)}.",
                        suggestion=f"Check the unit – usual: {usual}.")))
    return out


def check_quantities(boq: BoQ) -> list[Flag]:
    out = []
    for it in boq.items:
        if it.qty_tbd:
            out.append(Flag("R06", "Menge noch festzulegen", "medium", "Vordersatz fehlt (QtyTBD).",
                            oz=it.oz, reference="VOB/A § 7 Abs. 1 Nr. 1",
                            suggestion="Menge ermitteln oder als Bedarfsposition kennzeichnen.",
                            en=dict(title="Quantity still to be determined", message="Quantity missing (QtyTBD).",
                                    suggestion="Determine the quantity or mark the item as provisional.")))
        elif it.qty is not None and it.qty <= 0 and not it.provisional:
            out.append(Flag("R06", "Menge 0 oder negativ", "medium",
                            f"Vordersatz {it.qty:g} {it.unit} – Position wird nicht bepreist/abgerechnet.",
                            oz=it.oz, reference="VOB/A § 7 Abs. 1 Nr. 1",
                            suggestion="Menge aus Plan/Modell ermitteln oder Position streichen.",
                            en=dict(title="Quantity zero or negative",
                                    message=f"Quantity {it.qty:g} {it.unit} – the item will not be priced or billed.",
                                    suggestion="Take the quantity from drawings/model or delete the item.")))
        if boq.phase in ("84", "86") and not it.provisional and not it.alternative and it.qty and (it.up is None or it.up <= 0):
            out.append(Flag("R13", "Einheitspreis fehlt", "high", "Angebotsposition ohne Einheitspreis.",
                            oz=it.oz, reference="VOB/A § 16 Abs. 1 Nr. 3 (fehlende Preisangaben)",
                            suggestion="Preis beim Bieter aufklären.",
                            en=dict(title="Unit price missing", message="Bid item without a unit price.",
                                    suggestion="Clarify the price with the bidder.")))
    return out


def check_special_items(boq: BoQ) -> list[Flag]:
    out = []
    for it in boq.items:
        if it.provisional:
            out.append(Flag("R07", "Bedarfsposition", "info",
                            f"Bedarfsposition „{it.short_text}“ ({de(it.total, 0)} €) ist nicht in der Angebotssumme enthalten.",
                            oz=it.oz, reference="VOB/A § 7 Abs. 1 Nr. 4 (Bedarfspositionen nur ausnahmsweise)",
                            exposure_eur=it.total, suggestion="Budget für den Fall der Ausführung einplanen.",
                            en=dict(title="Provisional item",
                                    message=f"Provisional item '{it.short_text}' (€{E(it.total, 0)}) is not included in the bid total.",
                                    suggestion="Plan budget in case it is executed.")))
        if it.alternative:
            out.append(Flag("R07", "Wahlposition", "info", f"Wahlposition „{it.short_text}“ – Entscheidung offen.",
                            oz=it.oz, reference="VOB/A § 7 Abs. 1",
                            en=dict(title="Alternative item", message=f"Alternative item '{it.short_text}' – decision open.")))
        if it.hourly:
            out.append(Flag("R07", "Stundenlohnarbeiten", "low", "Stundenlohnpositionen nur nach vorheriger Vereinbarung abrechenbar.",
                            oz=it.oz, reference="VOB/B § 15",
                            en=dict(title="Daywork", message="Daywork items can only be billed if agreed beforehand.")))
    return out


def check_duplicates(boq: BoQ) -> list[Flag]:
    out = []
    items = boq.items
    seen_oz = defaultdict(list)
    for it in items:
        seen_oz[it.oz].append(it)
    for oz, its in seen_oz.items():
        if len(its) > 1:
            out.append(Flag("R12", "Doppelte Ordnungszahl", "high", f"OZ {oz} kommt {len(its)}× vor.", oz=oz,
                            reference="GAEB DA XML (OZ eindeutig)", suggestion="OZ neu vergeben.",
                            en=dict(title="Duplicate item number", message=f"Item number {oz} occurs {len(its)} times.",
                                    suggestion="Renumber the item.")))
    texted = [it for it in items if len(it.short_text.strip()) >= 8]   # price-only bid files carry no texts
    for i, a in enumerate(texted):
        for b in texted[i + 1:]:
            if norm_unit(a.unit) != norm_unit(b.unit):
                continue
            if _nums(a.short_text) != _nums(b.short_text):
                continue
            s = fuzz.token_sort_ratio(a.short_text.lower(), b.short_text.lower())
            if s < 92:
                continue
            ls = fuzz.token_sort_ratio(a.long_text.lower(), b.long_text.lower()) if (a.long_text and b.long_text) else s
            if ls < 90 or _nums(a.long_text) != _nums(b.long_text):
                continue
            out.append(Flag(
                "R04", "Mögliche Doppelposition", "high",
                f"OZ {b.oz} „{b.short_text}“ entspricht inhaltlich OZ {a.oz} (Ähnlichkeit {s:.0f} %). Doppelte Vergütung möglich.",
                oz=b.oz, reference="VOB/A § 7 Abs. 1 (eindeutige, erschöpfende Beschreibung)",
                exposure_eur=b.total, suggestion=f"Mit OZ {a.oz} zusammenführen oder Abgrenzung im Langtext klarstellen.",
                en=dict(title="Possible duplicate item",
                        message=f"Item {b.oz} '{b.short_text}' matches item {a.oz} in content (similarity {s:.0f}%). "
                                "The same work could be paid twice.",
                        suggestion=f"Merge with item {a.oz} or clarify the difference in the long text.")))
    return out


def check_prices(boq: BoQ) -> list[Flag]:
    out = []
    for it in boq.items:
        if it.up is None or it.qty is None or it.up <= 0:
            continue
        wt = _wt(it)
        if not wt:
            continue
        rng = wt.price.get(norm_unit(it.unit))
        if not rng:
            continue
        lo, hi = rng
        if it.up > hi * 1.5:
            sev = "high" if it.up > hi * 3 else "medium"
            out.append(Flag(
                "R05", "Einheitspreis auffällig hoch", sev,
                f"EP {de(it.up, 2)} €/{it.unit} liegt deutlich über dem Referenzbereich {de(lo, 0)}–{de(hi, 0)} €/{it.unit} für {wt.label}.",
                oz=it.oz, reference="VOB/A § 16d Abs. 1 (ungewöhnlich hohe/niedrige Preise aufklären); Spekulationspreis?",
                exposure_eur=(it.up - hi) * it.qty,
                suggestion="Preisaufklärung beim Bieter; Mengenansatz auf Spekulationspotenzial prüfen.",
                en=dict(title="Unit price unusually high",
                        message=f"Unit price €{E(it.up)}/{it.unit} is well above the reference range €{E(lo, 0)}–{E(hi, 0)}/{it.unit} "
                                f"for {_label_en(wt)}.",
                        suggestion="Ask the bidder to explain the price; check whether the quantity invites speculative pricing.")))
        elif it.up < lo / 1.5:
            out.append(Flag(
                "R05", "Einheitspreis auffällig niedrig", "medium",
                f"EP {de(it.up, 2)} €/{it.unit} liegt deutlich unter dem Referenzbereich {de(lo, 0)}–{de(hi, 0)} €/{it.unit}. "
                "Typisches Muster: Unterpreis bei Positionen, deren Menge der Bieter für überschätzt hält.",
                oz=it.oz, reference="VOB/A § 16d Abs. 1",
                exposure_eur=(lo - it.up) * it.qty, suggestion="Kalkulation anfordern; Menge plausibilisieren.",
                en=dict(title="Unit price unusually low",
                        message=f"Unit price €{E(it.up)}/{it.unit} is well below the reference range €{E(lo, 0)}–{E(hi, 0)}/{it.unit}. "
                                "Typical pattern: underpricing items whose quantity the bidder believes is overestimated.",
                        suggestion="Request the cost breakdown; check the quantity is plausible.")))
    return out


def check_vague(boq: BoQ) -> list[Flag]:
    out = []
    for it in boq.items:
        hits = []
        txt = it.text.lower()
        for rx, label, why in K.VAGUE_PATTERNS:
            if re.search(rx, txt):
                hits.append((label, why))
        if not hits:
            continue
        share = min(RISK["vague_cap"], RISK["vague"] * len(hits))
        labels = ", ".join(h[0] for h in hits)
        out.append(Flag(
            "R08", "Unbestimmte Formulierung", "medium",
            f"{labels}: " + " | ".join(h[1] for h in hits),
            oz=it.oz, reference="VOB/A § 7 Abs. 1 Nr. 1 (eindeutig und erschöpfend); VOB/B § 2 Abs. 5/6",
            exposure_eur=share * it.total, suggestion="Konkrete Mengen, Maße und Qualitäten angeben.",
            en=dict(title="Vague wording",
                    message=f"{labels}: " + " | ".join(K.VAGUE_EN.get(h[0], h[1]) for h in hits),
                    suggestion="State concrete quantities, dimensions and qualities.")))
    return out


def check_parameters(boq: BoQ) -> list[Flag]:
    out = []
    for it in boq.items:
        wt = _wt(it)
        if not wt or not wt.params:
            continue
        txt = it.text.lower()
        missing = [(n, why) for n, rx, why in wt.params if not re.search(rx, txt)]
        if not missing:
            continue
        names_en = ", ".join(K.PARAM_EN.get(n, (n, w))[0] for n, w in missing)
        out.append(Flag(
            "R09", f"Pflichtangabe fehlt: {', '.join(m[0] for m in missing)}", "high" if len(missing) > 1 else "medium",
            " | ".join(m[1] for m in missing),
            oz=it.oz, reference=f"VOB/C {wt.norm}, Abschnitt 0 (Hinweise für das Aufstellen der Leistungsbeschreibung)",
            exposure_eur=RISK["missing_param"] * it.total,
            suggestion="Fehlende Angaben gemäß STLB-Bau-Standardtext ergänzen.",
            en=dict(title=f"Mandatory detail missing: {names_en}",
                    message=" | ".join(K.PARAM_EN.get(n, (n, w))[1] for n, w in missing),
                    suggestion="Add the missing details following the STLB-Bau standard text.")))
    return out


def check_outdated(boq: BoQ) -> list[Flag]:
    out = []
    for it in boq.items:
        txt = it.text.lower()
        for rx, title, why, ref in K.OUTDATED_PATTERNS:
            if re.search(rx, txt):
                t_en, why_en = K.OUTDATED_EN.get(title, (title, why))
                out.append(Flag("R11", f"Veralteter Normbezug: {title}", "high", why, oz=it.oz, reference=ref,
                                exposure_eur=RISK["outdated_norm"] * it.total,
                                suggestion="Text auf aktuellen Normstand (STLB-Bau aktuelle Ausgabe) umstellen.",
                                en=dict(title=f"Outdated standard: {t_en}", message=why_en,
                                        suggestion="Update the text to the current standard (latest STLB-Bau edition).")))
    return out


def check_long_text(boq: BoQ) -> list[Flag]:
    out = []
    if _price_only(boq):
        return out
    for it in boq.items:
        if it.provisional:
            continue
        if len(it.long_text.strip()) < 25 and not it.stlb:
            out.append(Flag("R12", "Langtext fehlt/zu kurz", "low",
                            "Ohne Langtext ist die Leistung nicht eindeutig beschrieben.", oz=it.oz,
                            reference="VOB/A § 7 Abs. 1", suggestion="Langtext aus STLB-Bau übernehmen.",
                            en=dict(title="Long text missing or too short",
                                    message="Without a long text the work is not clearly described.",
                                    suggestion="Take the long text from STLB-Bau.")))
    return out


# ---------------------------------------------------------------- LV-level completeness

def check_completeness(boq: BoQ) -> list[Flag]:
    out = []
    items = boq.items
    if _price_only(boq):
        return out
    keys = defaultdict(list)
    for it in items:
        wt = _wt(it)
        if wt:
            keys[wt.key].append(it)
    total = boq.total

    # 1) concrete member without formwork
    formwork_txt = " ".join(i.text.lower() for i in keys["schalung"])
    for member, rx in K.MEMBERS.items():
        conc = [i for i in keys["beton"] if re.search(rx, i.short_text.lower())]
        if not conc or re.search(rx, formwork_txt):
            continue
        vol = sum((i.qty or 0) for i in conc if norm_unit(i.unit) == "m3")
        area = vol * K.FORMWORK_RATIO.get(member, 4)
        ozs = ", ".join(i.oz for i in conc)
        m_en = K.MEMBER_EN.get(member, member)
        out.append(Flag(
            "R10", f"Schalung fehlt: {member}", "high",
            f"Beton für {member} ({ozs}; {de(vol, 1)} m³) ausgeschrieben, aber keine Schalungsposition. "
            f"Ob die Schalung im Betonpreis steckt, ist dann strittig – klassischer Nachtragsstreit. Geschätzt ~{de(area, 0)} m².",
            reference="VOB/C DIN 18331 Abschn. 0.5 (eigene Abrechnungseinheit für Schalung); VOB/B § 2 Abs. 6",
            exposure_eur=area * K.REF_FORMWORK_EUR_M2,
            suggestion=f"Position „Schalung {member}“ (m²) ergänzen.",
            en=dict(title=f"Formwork missing: {m_en}",
                    message=f"Concrete for {m_en} ({ozs}; {E(vol, 1)} m³) is tendered, but there is no formwork item. "
                            f"Whether formwork is included in the concrete price then becomes a classic change-order dispute. "
                            f"Estimated ~{E(area, 0)} m².",
                    suggestion=f"Add a 'formwork {m_en}' item (m²).")))

    # 2) reinforced concrete without rebar
    rc = [i for i in keys["beton"] if "stahlbeton" in i.text.lower()]
    if rc and not keys["betonstahl"]:
        vol = sum((i.qty or 0) for i in rc if norm_unit(i.unit) == "m3")
        t = vol * K.REF_REBAR_T_PER_M3
        out.append(Flag(
            "R10", "Bewehrung fehlt", "high",
            f"Stahlbeton ({de(vol, 0)} m³) ohne Betonstahlposition. Geschätzt ~{de(t, 1)} t Betonstahl.",
            reference="VOB/C DIN 18331; VOB/B § 2 Abs. 6", exposure_eur=t * K.REF_REBAR_EUR_T,
            suggestion="Position „Betonstahl B500B liefern und verlegen“ (t) ergänzen.",
            en=dict(title="Reinforcement missing",
                    message=f"Reinforced concrete ({E(vol, 0)} m³) without a reinforcing-steel item. Estimated ~{E(t, 1)} t of rebar.",
                    suggestion="Add an item 'supply and fix reinforcing steel B500B' (t).")))

    # 3) excavation without disposal / backfill
    exc = keys["aushub"]
    exc_vol = sum((i.qty or 0) for i in exc if norm_unit(i.unit) == "m3")
    exc_txt = " ".join(i.text.lower() for i in exc)
    if exc and not keys["entsorgung"] and not re.search(r"abfahren|entsorg|abtransport", exc_txt):
        out.append(Flag(
            "R10", "Entsorgung Aushub fehlt", "high",
            f"{de(exc_vol, 0)} m³ Aushub, aber weder Abfuhr noch Entsorgung beschrieben – Verbleib des Bodens ungeregelt, "
            "Abfuhr/Entsorgung wird typischerweise nachgefordert.",
            reference="VOB/C DIN 18300 Abschn. 0.2 (Angaben zum Verbleib des Bodens); VOB/B § 2 Abs. 6",
            exposure_eur=exc_vol * K.REF_DISPOSAL_EUR_M3,
            suggestion="Positionen „Boden laden, abfahren, entsorgen“ je Homogenbereich/Einbauklasse ergänzen.",
            en=dict(title="Disposal of excavated soil missing",
                    message=f"{E(exc_vol, 0)} m³ of excavation, but neither removal nor disposal is described – "
                            "what happens to the soil is unregulated, so removal/disposal is typically claimed later.",
                    suggestion="Add 'load, remove and dispose of soil' items per soil zone / material class.")))

    # 4) site setup
    if items and not any(re.search(r"baustelleneinrichtung", i.short_text.lower()) for i in keys["be"]):
        out.append(Flag(
            "R10", "Baustelleneinrichtung fehlt", "medium",
            "Keine eigene BE-Position. Einrichten/Räumen ist dann Nebenleistung und steckt verdeckt in den EPs – "
            "bei Mengenänderungen (VOB/B § 2 Abs. 3) wird die BE-Deckung strittig.",
            reference="VOB/C DIN 18299 Abschn. 0.4.1 / 4.1.1", exposure_eur=K.REF_BE_SHARE * total * 0.33,
            suggestion="Position „Baustelleneinrichtung einrichten, vorhalten, räumen“ ergänzen.",
            en=dict(title="Site setup item missing",
                    message="No separate site-setup item. Setup/clearing is then an ancillary service hidden in the unit prices – "
                            "when quantities change (VOB/B § 2(3)) the coverage of site costs becomes disputed.",
                    suggestion="Add an item 'set up, maintain and clear the site'.")))

    # 5) masonry facades without scaffold
    ext = [i for i in keys["mauerwerk"] if re.search(r"au[ßs]enwand|fassade", i.text.lower())]
    if ext and not keys["geruest"]:
        area = sum((i.qty or 0) for i in ext if norm_unit(i.unit) == "m2")
        out.append(Flag(
            "R10", "Gerüst fehlt", "high",
            f"Außenmauerwerk ({de(area, 0)} m²) ohne Gerüstposition. Gerüste über 2 m Arbeitshöhe sind Besondere Leistung.",
            reference="VOB/C DIN 18299 / DIN 18330 Abschn. 4.2; DIN 18451", exposure_eur=area * K.REF_SCAFFOLD_EUR_M2,
            suggestion="Position „Fassadengerüst, Lastklasse 3, Standzeit …“ ergänzen.",
            en=dict(title="Scaffolding missing",
                    message=f"External masonry ({E(area, 0)} m²) without a scaffolding item. "
                            "Scaffolds above 2 m working height are a separately paid special service.",
                    suggestion="Add an item 'facade scaffold, load class 3, standing time …'.")))

    # 6) basement walls without waterproofing
    basement = [i for i in items if re.search(r"kellerau[ßs]enwand|kellerwand|erdber[üu]hrt|untergeschoss|\bkg\b", i.text.lower())
                and _wt(i) and _wt(i).key in ("beton", "mauerwerk")]
    if basement and not keys["abdichtung"]:
        vol = sum((i.qty or 0) for i in basement if norm_unit(i.unit) == "m3")
        area = vol / 0.24 if vol else sum((i.qty or 0) for i in basement if norm_unit(i.unit) == "m2")
        ozs = ", ".join(i.oz for i in basement)
        out.append(Flag(
            "R10", "Abdichtung erdberührter Bauteile fehlt", "high",
            f"Erdberührte Bauteile ({ozs}) ohne Abdichtungsposition.",
            reference="DIN 18533; VOB/C DIN 18336", exposure_eur=area * K.REF_WATERPROOF_EUR_M2,
            suggestion="Abdichtungsposition nach DIN 18533 mit Wassereinwirkungsklasse ergänzen.",
            en=dict(title="Waterproofing of below-ground elements missing",
                    message=f"Below-ground elements ({ozs}) without a waterproofing item.",
                    suggestion="Add a waterproofing item to DIN 18533 including the water exposure class.")))
    return out


ITEM_RULES = [check_arithmetic, check_units, check_quantities, check_special_items, check_duplicates,
              check_prices, check_vague, check_parameters, check_outdated, check_long_text]
LV_RULES = [check_completeness]


def run_rules(boq: BoQ) -> list[Flag]:
    flags: list[Flag] = []
    for fn in ITEM_RULES + LV_RULES:
        flags.extend(fn(boq))
    return flags
