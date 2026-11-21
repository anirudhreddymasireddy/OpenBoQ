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
from .units import family, is_known, norm_unit

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
        if fam not in ("volume", "area", "length", "count", "mass", "lump"):
            continue                    # composite units (mWo, StWo, Jahr …) – no reliable expectation
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
                "R02", "Einheit passt nicht zur Leistung", "medium",
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
            if a.section_oz != b.section_oz:
                continue            # same item in different lots/sections is normal (e.g. site setup per lot)
            if norm_unit(a.unit) != norm_unit(b.unit):
                continue
            if _nums(a.short_text) != _nums(b.short_text):
                continue
            s = fuzz.token_sort_ratio(a.short_text.lower(), b.short_text.lower())
            if s < 92:
                continue
            if len(a.long_text) < 25 or len(b.long_text) < 25:
                continue            # short-text-only prints (bids): "wie vor, jedoch …" items differ in the unprinted long text
            ls = fuzz.token_sort_ratio(a.long_text.lower(), b.long_text.lower())
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
            sev = "low"     # reference ranges are placeholders until prices are learned from real projects
            out.append(Flag(
                "R05", "Einheitspreis auffällig hoch", sev,
                f"EP {de(it.up, 2)} €/{it.unit} liegt deutlich über dem Referenzbereich {de(lo, 0)}–{de(hi, 0)} €/{it.unit} für {wt.label}.",
                oz=it.oz, reference="VOB/A § 16d Abs. 1 (ungewöhnlich hohe/niedrige Preise aufklären); Spekulationspreis?",
                exposure_eur=(it.up - hi) * it.qty, data={"direction": "high", "up": it.up, "ref": hi, "factor": 1.5},
                suggestion="Preisaufklärung beim Bieter; Mengenansatz auf Spekulationspotenzial prüfen.",
                en=dict(title="Unit price unusually high",
                        message=f"Unit price €{E(it.up)}/{it.unit} is well above the reference range €{E(lo, 0)}–{E(hi, 0)}/{it.unit} "
                                f"for {_label_en(wt)}.",
                        suggestion="Ask the bidder to explain the price; check whether the quantity invites speculative pricing.")))
        elif it.up < lo / 1.5:
            out.append(Flag(
                "R05", "Einheitspreis auffällig niedrig", "low",
                f"EP {de(it.up, 2)} €/{it.unit} liegt deutlich unter dem Referenzbereich {de(lo, 0)}–{de(hi, 0)} €/{it.unit}. "
                "Typisches Muster: Unterpreis bei Positionen, deren Menge der Bieter für überschätzt hält.",
                oz=it.oz, reference="VOB/A § 16d Abs. 1",
                exposure_eur=(lo - it.up) * it.qty, data={"direction": "low", "up": it.up, "ref": lo, "factor": 1 / 1.5},
                suggestion="Kalkulation anfordern; Menge plausibilisieren.",
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
        weak_only = all(h[0] == "„ca.“" for h in hits)      # "ca." alone is common and usually minor
        out.append(Flag(
            "R08", "Unbestimmte Formulierung", "low" if weak_only else "medium",
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
        if not wt or not wt.params or len(it.long_text.strip()) < 25:
            continue                    # without a long text (bid print-outs) we cannot judge completeness
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
        if vol <= 0:
            continue                    # concrete only as pieces (precast) – no formwork expectation
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
    rc_vol = sum((i.qty or 0) for i in rc if norm_unit(i.unit) == "m3")
    if rc and rc_vol > 0 and not keys["betonstahl"]:
        vol = rc_vol
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


# ---------------------------------------------------------------- cent prices (no history needed)

PRICE_FLOOR = {"m3": 1.0, "t": 1.0, "St": 1.0, "psch": 1.0, "h": 1.0, "d": 1.0, "Wo": 1.0, "Mt": 1.0, "m2": 0.3}


def check_cent_prices(boq: BoQ) -> list[Flag]:
    """Unit prices below any plausible cost (e.g. €0.95/t, €0.05/m³): decimal typo or speculative pricing."""
    out = []
    for it in boq.items:
        u = norm_unit(it.unit)
        floor = PRICE_FLOOR.get(u)
        if floor is None or not it.up or it.up <= 0 or not it.qty or it.provisional:
            continue
        if it.up < floor:
            out.append(Flag(
                "R25", "Cent-Preis – unplausibel niedrig", "high",
                f"EP {de(it.up, 2)} €/{it.unit} für „{it.short_text[:70]}“ liegt unter jedem realistischen Kostensatz "
                f"(Schwelle {de(floor, 2)} €/{u}). Kommafehler oder Spekulationspreis: Steigt die Menge, entsteht Verlust; "
                "fällt sie weg, wurde der Betrag in andere Positionen verschoben.",
                oz=it.oz, reference="VOB/A § 16d Abs. 1 (unangemessen niedrige Preise); VOB/B § 2 Abs. 3",
                suggestion="Kalkulation dieser Position prüfen – vor Angebotsabgabe korrigieren.",
                en=dict(title="Cent price – implausibly low",
                        message=f"Unit price €{E(it.up)}/{it.unit} for '{it.short_text[:70]}' is below any realistic cost "
                                f"(threshold €{E(floor)}/{u}). Decimal typo or speculative price: if the quantity grows you lose money; "
                                "if it disappears, the amount was shifted into other items.",
                        suggestion="Check the calculation of this item – correct it before submitting the bid.")))
    return out


# ---------------------------------------------------------------- data-quality checks

def check_parse_issues(boq: BoQ) -> list[Flag]:
    out = []
    for it in boq.items:
        if it.issues:
            out.append(Flag("R21", "Wert nicht lesbar", "high",
                            f"Feld(er) mit ungültigem Zahlenformat: {', '.join(it.issues)} – Wert wurde nicht übernommen.",
                            oz=it.oz, reference="GAEB DA XML / Datenqualität",
                            suggestion="Wert im Quell-LV korrigieren (Tippfehler, Buchstabe statt Ziffer, doppeltes Komma).",
                            en=dict(title="Unreadable value",
                                    message=f"Field(s) with invalid number format: {', '.join(it.issues)} – value was not taken over.",
                                    suggestion="Correct the value in the source BoQ (typo, letter instead of digit, double comma).")))
    return out


def check_value_format(boq: BoQ) -> list[Flag]:
    out = []
    for it in boq.items:
        u = norm_unit(it.unit)
        if it.unit and not is_known(it.unit):
            out.append(Flag("R22", "Unbekannte Einheit", "medium", f"Einheit „{it.unit}“ ist keine übliche Abrechnungseinheit – Tippfehler?",
                            oz=it.oz, reference="VOB/C ATV Abschnitt 0.5", suggestion="Einheit prüfen.",
                            en=dict(title="Unknown unit", message=f"Unit '{it.unit}' is not a usual billing unit – typo?",
                                    suggestion="Check the unit.")))
        if it.qty is None:
            continue
        if u in ("St", "Satz") and abs(it.qty - round(it.qty)) > 1e-9:
            out.append(Flag("R22", "Stückzahl mit Nachkommastellen", "medium",
                            f"{de(it.qty, 3)} {it.unit} – eine Stückzahl sollte ganzzahlig sein. Tippfehler oder falsche Einheit?",
                            oz=it.oz, reference="Plausibilität Vordersatz", suggestion="Menge oder Einheit korrigieren.",
                            en=dict(title="Count with decimals",
                                    message=f"{E(it.qty, 3)} {it.unit} – a count should be a whole number. Typo or wrong unit?",
                                    suggestion="Correct the quantity or the unit.")))
        if u == "psch" and it.qty not in (1, 1.0) and it.qty > 0:
            out.append(Flag("R22", "Pauschale mit Menge ≠ 1", "medium",
                            f"Pauschalposition mit Menge {it.qty:g} – üblich ist 1 psch.",
                            oz=it.oz, reference="Plausibilität Vordersatz", suggestion="Menge auf 1 setzen oder Einheit prüfen.",
                            en=dict(title="Lump sum with quantity ≠ 1", message=f"Lump-sum item with quantity {it.qty:g} – usually 1 psch.",
                                    suggestion="Set the quantity to 1 or check the unit.")))
    return out


def check_currency(boq: BoQ) -> list[Flag]:
    out = []
    cur = (boq.currency or "").strip().upper()
    if cur and cur not in ("EUR", "EURO", "€"):
        out.append(Flag("R23", "Währung nicht EUR", "high", f"LV-Währung „{boq.currency}“.",
                        reference="GAEB PrjInfo/Cur", suggestion="Währung und Umrechnung prüfen.",
                        en=dict(title="Currency is not EUR", message=f"BoQ currency '{boq.currency}'.",
                                suggestion="Check the currency and conversion.")))
    rx = re.compile(r"\b(\d[\d.,]*)\s*(DM|USD|CHF|GBP|\$|£)(?=\W|$)|\b(DM|USD|CHF|GBP)\s*\d", re.I)
    for it in boq.items:
        m = rx.search(it.text)
        if m:
            out.append(Flag("R23", "Fremdwährung im Text", "medium", f"Betrag in anderer Währung im Positionstext: „{m.group(0)}“.",
                            oz=it.oz, reference="Eindeutigkeit der Preisangaben", suggestion="Betrag in EUR angeben.",
                            en=dict(title="Foreign currency in text", message=f"Amount in another currency in the item text: '{m.group(0)}'.",
                                    suggestion="State the amount in EUR.")))
    return out


def check_injection(boq: BoQ) -> list[Flag]:
    """Hidden instructions aimed at AI review tools, and invisible characters."""
    out = []
    sources = [(it.oz, it.text) for it in boq.items] + [("", n["text"]) for n in boq.notes]
    for oz, text in sources:
        low = text.lower()
        m = re.search(K.INJECTION, low)
        inv = re.findall(K.INVISIBLE, text)
        if m:
            out.append(Flag("S01", "Versteckte Anweisung an KI-Systeme", "high",
                            f"Text enthält eine Anweisung an KI-Werkzeuge: „…{text[max(0, m.start()-30):m.end()+30]}…“. "
                            "Wird bei der KI-Prüfung als Daten behandelt, nicht befolgt.",
                            oz=oz, reference="Manipulationsversuch (Prompt Injection)",
                            suggestion="Herkunft des Textes klären; dem AG melden.",
                            en=dict(title="Hidden instruction aimed at AI tools",
                                    message=f"Text contains an instruction to AI tools: '…{text[max(0, m.start()-30):m.end()+30]}…'. "
                                            "It is treated as data during the AI review, never followed.",
                                    suggestion="Clarify where the text comes from; report it to the client.")))
        if len(inv) >= 3:
            out.append(Flag("S02", "Unsichtbare Zeichen im Text", "medium",
                            f"{len(inv)} unsichtbare Steuerzeichen gefunden – können Text verbergen oder Vergleiche verfälschen.",
                            oz=oz, reference="Datenintegrität", suggestion="Text bereinigen und Original prüfen.",
                            en=dict(title="Invisible characters in text",
                                    message=f"{len(inv)} invisible control characters found – they can hide text or distort comparisons.",
                                    suggestion="Clean the text and check the original.")))
    return out


# ---------------------------------------------------------------- contract-risk clauses (contractor's view)

def _is_public(boq: BoQ) -> bool:
    blob = " ".join([boq.project, boq.client, boq.name] + [n["text"][:3000] for n in boq.notes[:20]]).lower()
    return bool(re.search(K.PUBLIC_CLIENT, blob))


def _snippet(text: str, m) -> str:
    start = max(text.rfind(".", 0, m.start()) + 1, m.start() - 160)
    if start > 0 and text[start - 1].isalnum():          # don't start mid-word
        nxt = text.find(" ", start)
        start = nxt + 1 if 0 <= nxt < m.start() else start
    end = text.find(".", m.end())
    end = len(text) if end == -1 else min(end + 1, m.end() + 200)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def check_clauses(boq: BoQ) -> list[Flag]:
    out = []
    public = _is_public(boq)
    sources = [(it.oz, it.text, it.total, "Pos.") for it in boq.items] + \
              [("", n["text"], 0.0, f"Vorbemerkung {n['ref']}") for n in boq.notes]
    seen = set()
    for oz, text, value, where in sources:
        low = text.lower()
        for key, rx, weight, t_de, t_en, why_de, why_en, q_de, q_en in K.CLAUSES:
            m = re.search(rx, low)
            if not m:
                continue
            snip = _snippet(text, m)
            sig = (key, snip[:80])
            if sig in seen:
                continue
            seen.add(sig)
            sev = "medium" if public and key not in ("no_claims", "ground_risk") else "high"
            if key in ("site_knowledge", "price_lock", "one_sided") and public:
                sev = "low"
            ctx_de = "Öffentlicher AG – an VOB/A § 7 (kein ungewöhnliches Wagnis) gebunden." if public else \
                     "Privater AG – Klausel nur über AGB-Recht (§ 307 BGB) angreifbar, daher einpreisen."
            ctx_en = "Public client – bound by VOB/A § 7 (no unusual risk)." if public else \
                     "Private client – clause only contestable under standard-terms law (§ 307 BGB), so price it in."
            loc_de = where if not oz else f"Pos. {oz}"
            loc_en = where.replace("Vorbemerkung", "Preliminary note") if not oz else f"Item {oz}"
            f = Flag("R20", f"Vertragsrisiko: {t_de}", sev,
                     f"{loc_de}: „{snip}“ – {why_de} {ctx_de}",
                     oz=oz, reference="VOB/A § 7 Abs. 1 Nr. 3; VOB/B § 2; § 307 BGB",
                     exposure_eur=weight * value,
                     suggestion="Risiko einpreisen oder als Bieterfrage klären.",
                     en=dict(title=f"Contract risk: {t_en}", message=f"{loc_en}: '{snip}' – {why_en} {ctx_en}",
                             suggestion="Price the risk in or clarify it with a bidder question."))
            f.question = {"de": f"{loc_de}: „{snip[:160]}“ – {q_de}", "en": f"{loc_en}: '{snip[:160]}' – {q_en}"}
            out.append(f)
    return out


ITEM_RULES = [check_arithmetic, check_units, check_quantities, check_special_items, check_duplicates,
              check_prices, check_vague, check_parameters, check_outdated, check_long_text,
              check_parse_issues, check_value_format, check_currency, check_cent_prices]
LV_RULES = [check_completeness, check_clauses, check_injection]

# contractor's view: what kind of finding is it?
CATEGORY = {"R01": "error", "R04": "error", "R06": "error", "R12": "error", "R13": "error", "R21": "error", "R22": "error",
            "R23": "error", "R02": "error", "R05": "error", "R24": "risk", "R25": "error",
            "R03": "risk", "R09": "risk", "R11": "risk", "R20": "risk", "R07": "risk",
            "R08": "opportunity", "R10": "opportunity", "R14": "opportunity", "R15": "opportunity", "R16": "risk",
            "S01": "security", "S02": "security"}


def _question(f: Flag, boq: BoQ) -> dict:
    """Bidder question (Bieterfrage) for findings that need clarification before pricing."""
    if f.question:
        return f.question
    t_de, m_de, _ = f.txt("de")
    t_en, m_en, _ = f.txt("en")
    loc_de = f"Pos. {f.oz}" if f.oz else "LV"
    loc_en = f"Item {f.oz}" if f.oz else "BoQ"
    if f.rule_id == "R08":
        return {"de": f"{loc_de}: Die Beschreibung ist nicht eindeutig ({m_de.split(':')[0]}). Bitte konkretisieren Sie Umfang, Maße und Qualität.",
                "en": f"{loc_en}: The description is ambiguous ({m_en.split(':')[0]}). Please specify scope, dimensions and quality."}
    if f.rule_id == "R09":
        return {"de": f"{loc_de}: {t_de.replace('Pflichtangabe fehlt: ', 'Es fehlt die Angabe ')}. Bitte ergänzen Sie diese für eine eindeutige Kalkulation.",
                "en": f"{loc_en}: {t_en.replace('Mandatory detail missing: ', 'The ')} is missing. Please add it so the item can be priced unambiguously."}
    if f.rule_id == "R10":
        return {"de": f"{loc_de}: {t_de}. Ist diese Leistung in anderen Positionen enthalten oder wird sie gesondert vergütet?",
                "en": f"{loc_en}: {t_en}. Is this work included in other items or will it be paid separately?"}
    if f.rule_id in ("R02", "R03", "R22"):
        return {"de": f"{loc_de}: {t_de} – bitte bestätigen Sie Einheit und Vordersatz.",
                "en": f"{loc_en}: {t_en} – please confirm the unit and quantity."}
    if f.rule_id == "R11":
        return {"de": f"{loc_de}: {t_de}. Welcher aktuelle Normstand gilt für die Ausführung?",
                "en": f"{loc_en}: {t_en}. Which current standard applies to the execution?"}
    if f.rule_id in ("R04", "R12") and f.severity in ("high", "medium"):
        return {"de": f"{loc_de}: {t_de} – bitte um Klarstellung.", "en": f"{loc_en}: {t_en} – please clarify."}
    return {}


def run_rules(boq: BoQ) -> list[Flag]:
    flags: list[Flag] = []
    for fn in ITEM_RULES + LV_RULES:
        flags.extend(fn(boq))
    for f in flags:
        f.category = f.category or CATEGORY.get(f.rule_id, "risk")
        if f.severity in ("high", "medium"):
            f.question = _question(f, boq)
    return flags
