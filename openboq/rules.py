"""Deterministic, explainable checks on a bill of quantities.

Every flag carries: the rule, a legal/normative reference, a suggested fix, and an
estimated € exposure (transparent heuristics, see RISK below – tune with the sponsor).
Texts are German (field values) with English versions in Flag.en for the language toggle.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

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
        # price fits another usual unit of the same work ("Sauberkeitsschicht 136 €/m2" = an m3 price) → wrong unit
        other = [u for u, (a, b) in wt.price.items() if u != norm_unit(it.unit) and a <= it.up <= b * 1.2]
        if other and (it.up > hi * 3 or it.up < lo / 3):            # far off – a near miss is just a price question
            u2 = other[0]
            out.append(Flag(
                "R02", "Einheit passt nicht zum Preis", "high",
                f"EP {de(it.up, 2)} €/{it.unit} für „{it.short_text[:60]}“ ist ein typischer Preis je {u2} "
                f"(üblich {de(wt.price[u2][0], 0)}–{de(wt.price[u2][1], 0)} €/{u2}), nicht je {it.unit} "
                f"({de(lo, 0)}–{de(hi, 0)} €/{it.unit}). Einheit oder Preis ist falsch – der GP stimmt dann nicht.",
                oz=it.oz, reference="VOB/C Abschnitt 0.5 (Abrechnungseinheiten)",
                exposure_eur=abs(it.total - (it.qty or 0) * (hi if it.up > hi else lo)),
                suggestion=f"Einheit ({it.unit} oder {u2}) und Menge prüfen.",
                en=dict(title="Unit does not fit the price",
                        message=f"Unit price €{E(it.up)}/{it.unit} for '{it.short_text[:60]}' is a typical price per {u2} "
                                f"(usual €{E(wt.price[u2][0], 0)}–{E(wt.price[u2][1], 0)}/{u2}), not per {it.unit}. "
                                "Either unit or price is wrong – the amount is then wrong too.",
                        suggestion=f"Check the unit ({it.unit} or {u2}) and the quantity.")))
            continue
        if it.up > hi * 1.5:
            sev = "medium" if it.up > hi * 4 else "low"   # ranges are placeholders – only a gross outlier is more than a hint
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
                "R05", "Einheitspreis auffällig niedrig", "medium" if it.up < lo / 5 else "low",
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


def check_site_setup_share(boq: BoQ) -> list[Flag]:
    """A lump-sum site setup has no unit price to compare – but its share of the bid does: usually 2–15 %."""
    tot = sum(i.total for i in boq.items if not i.provisional and not i.alternative)
    be = [i for i in boq.items if _wt(i) and _wt(i).key == "be" and i.total > 0 and not i.provisional]
    if tot <= 0 or not be or len(boq.items) < 8:
        return []
    share = sum(i.total for i in be) / tot
    if share <= 0.20:
        return []
    exp = sum(i.total for i in be) - 0.10 * (tot - sum(i.total for i in be)) / 0.90
    return [Flag("R05", "Baustelleneinrichtung unplausibel hoch", "high" if share > 0.35 else "medium",
                 f"Die Baustelleneinrichtung macht {100 * share:.0f} % der Angebotssumme aus (üblich 2–15 %). "
                 "Kommafehler, falsche Menge oder Umlage anderer Kosten in die Pauschale (Spekulation auf Vorauszahlung)?",
                 oz=be[0].oz, reference="VOB/A § 16d Abs. 1 (unangemessene Preise)", exposure_eur=max(0.0, exp),
                 suggestion="Pauschale der BE prüfen und begründen; Kostenumlagen offenlegen.",
                 en=dict(title="Site setup implausibly high",
                         message=f"Site setup makes up {100 * share:.0f} % of the bid total (usual 2–15 %). Decimal error, "
                                 "wrong quantity, or other costs loaded into the lump sum (front-loading)?",
                         suggestion="Check and justify the site-setup lump sum; disclose cost allocations."))]


def _peer_key(it: Item) -> str:
    """Same work described the same way: 'Kabelgraben 0,60 x 1,00 m ausheben (Pos. 1050)' ≈ '… (Pos. 1900)'."""
    t = re.sub(r"\((?:pos\.?|position|vgl\.?|siehe)[^)]*\)", " ", it.short_text.lower())
    return re.sub(r"\s+", " ", t).strip() + "|" + norm_unit(it.unit)


def check_peer_prices(boq: BoQ) -> list[Flag]:
    """No price history needed: the same work in the same BoQ should cost about the same."""
    from statistics import median
    groups: dict[str, list] = {}
    for it in boq.items:
        if it.up and it.up > 0 and it.short_text.strip() and not it.provisional:
            groups.setdefault(_peer_key(it), []).append(it)
    out = []
    for key, its in groups.items():
        if len(its) < 3:
            continue
        for it in its:
            ref = median([x.up for x in its if x is not it])
            if ref <= 0:
                continue
            f = it.up / ref
            if f < 4 and f > 0.25:
                continue
            hi = f >= 4
            out.append(Flag(
                "R31", "EP weicht von gleichen Positionen ab", "high",
                f"EP {de(it.up, 2)} €/{it.unit} – {len(its) - 1} gleichartige Positionen in diesem LV liegen im Median bei "
                f"{de(ref, 2)} €/{it.unit} (Faktor {de(f, 1)}). "
                + ("Überhöhter Preis oder Kommafehler." if hi else "Kommafehler oder Spekulationspreis – bei Mehrmengen Verlust."),
                oz=it.oz, reference="VOB/A § 16d Abs. 1 (ungewöhnlich hohe/niedrige Preise)",
                exposure_eur=abs(it.up - ref) * (it.qty or 0),
                data={"ref": ref, "factor": f, "peers": [x.oz for x in its if x is not it][:10]},
                suggestion="Preis mit den gleichen Positionen abgleichen und korrigieren.",
                en=dict(title="Unit price differs from identical items",
                        message=f"Unit price €{E(it.up)}/{it.unit} – {len(its) - 1} identical items in this BoQ have a median of "
                                f"€{E(ref)}/{it.unit} (factor {E(f, 1)}).",
                        suggestion="Align the price with the identical items.")))
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


CORE_PARAMS = {("rohr", "Nennweite")}


def check_parameters(boq: BoQ) -> list[Flag]:
    out = []
    for it in boq.items:
        wt = _wt(it)
        if not wt or not wt.params:
            continue
        params = wt.params
        if len(it.long_text.strip()) < 25:
            # without a long text (bid print-outs) only the defining detail can be judged: a pipe's DN is always in the short text
            params = [p for p in params if (wt.key, p[0]) in CORE_PARAMS]
            if not params:
                continue
        txt = it.text.lower()
        missing = [(n, why) for n, rx, why in params if not re.search(rx, txt)]
        if not missing:
            continue
        names_en = ", ".join(K.PARAM_EN.get(n, (n, w))[0] for n, w in missing)
        out.append(Flag(
            # severity follows the money at stake: a missing exposure class on a €300 item is a hint, on €30k a risk
            "R09", f"Pflichtangabe fehlt: {', '.join(m[0] for m in missing)}",
            ("high" if len(missing) > 1 else "medium") if it.total >= 20000 else ("medium" if it.total >= 5000 else "low"),
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
    short_only = sum(1 for i in boq.items if len(i.long_text.strip()) < 25) >= 0.6 * max(1, len(boq.items))
    if short_only:
        # bid/price print-outs show short texts only – "long text missing" on every line is noise, not a finding.
        # Unclear short texts are handled by R27 (and judged by the AI when it runs).
        return [Flag("R12", "Ausdruck nur mit Kurztexten", "info",
                     "Das Dokument enthält fast nur Kurztexte (typisch für Angebotsausdrucke). Die Langtexte des "
                     "Leistungsverzeichnisses gelten trotzdem – bei Unklarheiten das Original-LV heranziehen.",
                     reference="VOB/A § 7 Abs. 1", suggestion="Original-LV (GAEB X83/X84) mit Langtexten anfordern.",
                     en=dict(title="Print-out with short texts only",
                             message="The document contains almost only short texts (typical for bid print-outs). The BoQ's "
                                     "long texts still apply – check the original BoQ where something is unclear.",
                             suggestion="Request the original BoQ (GAEB X83/X84) with long texts."))]
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


# ---------------------------------------------------------------- quantity relations (no model needed)

_DECK = re.compile(r"deckschicht|\bac\s?\d+\s?d\b|\bsma\s?\d|asphaltdeck|surface course", re.I)
_BINDER = re.compile(r"binderschicht|\bac\s?\d+\s?b\b|binder course", re.I)
_ATRAG = re.compile(r"asphalttragschicht|\bac\s?\d+\s?t\b|bituminöse tragschicht|asphalt base", re.I)
_FROST = re.compile(r"frostschutz|frost protection", re.I)
_STRIP = re.compile(r"abtrag|abschieben|aufnehmen|abheben|strip", re.I)
_SPREAD = re.compile(r"andeck|auftrag|wieder\s?einbau|einbauen|aufbring|spread", re.I)
_REBAR_INCL = re.compile(r"(?:inkl\.?|einschl\.?|einschließlich|mit)\s+(?:\w+\s+){0,2}bewehrung|stahlfaser", re.I)


def _sum(items, unit):
    return sum(i.qty or 0 for i in items if norm_unit(i.unit) == unit and not i.provisional and not i.alternative)


def _up(items, unit, default):
    ups = [i.up for i in items if norm_unit(i.unit) == unit and i.up]
    return sorted(ups)[len(ups) // 2] if ups else default


def _qflag(title_de, title_en, msg_de, msg_en, items, eur, sug_de, sug_en):
    ozs = ", ".join(i.oz for i in items[:8])
    return Flag("R35", title_de, "medium", f"{msg_de} (Pos. {ozs})", reference="Mengenplausibilität (Aufmaß-/Mengenermittlung)",
                exposure_eur=max(0.0, eur), suggestion=sug_de, data={"items": [i.oz for i in items]},
                en=dict(title=title_en, message=f"{msg_en} (items {ozs})", suggestion=sug_en))


def check_quantity_relations(boq: BoQ) -> list[Flag]:
    """Quantities that cannot fit each other – the estimator's cross-checks, without a building model:
    rebar per m³ of concrete, more disposal than excavation, an asphalt layer wider than the layer beneath it,
    more topsoil spread than stripped."""
    by: dict[str, list[Item]] = defaultdict(list)
    for it in boq.items:
        wt = _wt(it)
        if wt:
            by[wt.key].append(it)
    out = []
    # 1. reinforcement ratio
    conc, steel = by["beton"], by["betonstahl"]
    m3 = _sum(conc, "m3")
    t = _sum(steel, "t") + _sum(steel, "kg") / 1000
    if m3 >= 20 and t > 0 and m3 >= 0.6 * (m3 + _sum(conc, "m2") * 0.25):
        kg = 1000 * t / m3
        incl = any(_REBAR_INCL.search(i.text) for i in conc)
        p_kg = _up(steel, "t", 1600) / 1000 if _sum(steel, "t") else _up(steel, "kg", 1.6)
        if kg < 25 and not incl:
            out.append(_qflag("Bewehrungsmenge unplausibel niedrig", "Rebar quantity implausibly low",
                              f"{de(t, 1)} t Betonstahl auf {de(m3, 0)} m³ Ortbeton = {de(kg, 0)} kg/m³ (üblich 60–180 kg/m³). "
                              "Bewehrung zu knapp ermittelt oder in anderen Positionen enthalten?",
                              f"{E(t, 1)} t of rebar for {E(m3, 0)} m³ of cast concrete = {E(kg, 0)} kg/m³ (usual 60–180 kg/m³). "
                              "Rebar under-measured, or included in other items?",
                              steel + conc, (60 - kg) * m3 * p_kg,
                              "Bewehrungsmenge aus Statik/Bewehrungsplan prüfen; Mehrmenge > 10 % → VOB/B § 2 Abs. 3.",
                              "Check the rebar quantity against the structural design; extra quantity > 10 % → VOB/B § 2(3)."))
        elif kg > 250:
            out.append(_qflag("Bewehrungsmenge unplausibel hoch", "Rebar quantity implausibly high",
                              f"{de(t, 1)} t Betonstahl auf {de(m3, 0)} m³ Ortbeton = {de(kg, 0)} kg/m³ (üblich 60–180 kg/m³). "
                              "Einheit kg/t verwechselt oder Menge doppelt?",
                              f"{E(t, 1)} t of rebar for {E(m3, 0)} m³ of cast concrete = {E(kg, 0)} kg/m³ (usual 60–180 kg/m³). "
                              "kg and t mixed up, or quantity counted twice?",
                              steel + conc, (kg - 180) * m3 * p_kg,
                              "Menge und Einheit der Bewehrung prüfen.", "Check rebar quantity and unit."))
    # 2. disposal vs excavation
    dig = re.compile(r"aushub|ausheben|lösen|losen|abtrag|graben(?!verbau)|excavat", re.I)
    demo = re.compile(r"abbrech|aufbrech|abbruch|rückbau|fräs|ausbauen|lager\s+aufnehmen|zwischenlager\s+aufnehmen", re.I)
    # "Rohrgrabenaushub, auf Kippe abfahren" is excavation AND disposal; demolition / re-handled stockpiles are not excavation
    exc = by["aushub"] + [i for i in by["kabelgraben"] if norm_unit(i.unit) == "m3"] + \
        [i for i in by["entsorgung"] if dig.search(i.short_text) and not demo.search(i.short_text)]
    dis = [i for i in by["entsorgung"] if not demo.search(i.short_text) or re.search(r"lager\s+aufnehmen", i.short_text, re.I)]
    ex_m3 = _sum(exc, "m3")
    dis_m3 = _sum(dis, "m3") + _sum(dis, "t") / 1.9
    if ex_m3 >= 50 and dis_m3 > 1.35 * ex_m3:
        p = _up(dis, "m3", 0) or _up(dis, "t", 20) * 1.9
        out.append(_qflag("Mehr Entsorgung als Aushub", "More disposal than excavation",
                          f"Zu entsorgen: {de(dis_m3, 0)} m³ (t ÷ 1,9), ausgehoben werden aber nur {de(ex_m3, 0)} m³ – auch mit "
                          "Auflockerung passt das nicht.",
                          f"To dispose: {E(dis_m3, 0)} m³ (t ÷ 1.9), but only {E(ex_m3, 0)} m³ are excavated – that does not fit "
                          "even with bulking.",
                          dis + exc, (dis_m3 - 1.35 * ex_m3) * p,
                          "Massenbilanz (Aushub – Wiedereinbau – Entsorgung) prüfen; Abbruch/Rückbau als Quelle ausschließen.",
                          "Check the earthworks balance (excavation – reuse – disposal); rule out demolition as the source."))
    # 3. road layers: an upper layer is never wider than the layer beneath it
    road = [i for i in boq.items if norm_unit(i.unit) == "m2" and not i.provisional and not i.alternative
            and not re.search(r"zulage|reinig|fräs|abbruch|aufbrech|ausbau", i.short_text, re.I)]   # surcharges / removal are not layers
    layers = [("Asphaltdeckschicht", "asphalt surface course", [i for i in road if _DECK.search(i.short_text)]),
              ("Asphaltbinderschicht", "asphalt binder course", [i for i in road if _BINDER.search(i.short_text)]),
              ("Asphalttragschicht", "asphalt base course", [i for i in road if _ATRAG.search(i.short_text)]),
              ("Frostschutzschicht", "frost protection layer", [i for i in road if _FROST.search(i.short_text)])]
    layers = [(a, b, its, sum(i.qty or 0 for i in its)) for a, b, its in layers if its]
    for (ua, ub, ui, uq), (la, lb, li, lq) in zip(layers, layers[1:]):
        if lq > 0 and uq > 1.15 * lq:
            out.append(_qflag(f"{ua} größer als {la}", f"{ub.capitalize()} larger than {lb}",
                              f"{ua} {de(uq, 0)} m² liegt auf nur {de(lq, 0)} m² {la} – eine obere Schicht kann nicht breiter sein "
                              "als die darunter.",
                              f"{ub.capitalize()} of {E(uq, 0)} m² sits on only {E(lq, 0)} m² of {lb} – an upper layer cannot be "
                              "wider than the one beneath.",
                              ui + li, (uq - lq) * _up(li, "m2", 10),
                              "Flächen der Schichten aus demselben Aufmaß ermitteln.",
                              "Take the layer areas from the same take-off."))
    # 4. topsoil spread vs stripped
    top = by["oberboden"]
    strip = [i for i in top if _STRIP.search(i.short_text)]
    spread = [i for i in top if _SPREAD.search(i.short_text) and not _STRIP.search(i.short_text)]
    supply = any(re.search(r"liefer|supply", i.short_text, re.I) for i in spread)
    for u in ("m2", "m3"):
        s_q, p_q = _sum(strip, u), _sum(spread, u)
        if s_q > 0 and p_q > 1.2 * s_q and not supply:
            out.append(_qflag("Mehr Oberboden angedeckt als abgetragen", "More topsoil spread than stripped",
                              f"Angedeckt werden {de(p_q, 0)} {u}, abgetragen nur {de(s_q, 0)} {u} – ohne Position für Liefern "
                              "von Oberboden fehlt das Material.",
                              f"{E(p_q, 0)} {u} are spread but only {E(s_q, 0)} {u} stripped – without an item for supplying "
                              "topsoil the material is missing.",
                              strip + spread, (p_q - s_q) * (_up(spread, u, 6)),
                              "Position „Oberboden liefern“ ergänzen oder Mengen abgleichen.",
                              "Add an item 'supply topsoil' or reconcile the quantities."))
    return out


# ---------------------------------------------------------------- cent prices (no history needed)

# an hour of plant or labour and a day of anything cost more than a few euros; renting a small item per hour
# ("Warnleuchte vorhalten 3,36 €/h") can be cheap, so rental hours keep the old floor. Per metre there is no floor:
# marking tape or a pressure test at 0,20 €/m is a real price.
PRICE_FLOOR = {"m3": 1.0, "t": 1.0, "St": 1.0, "psch": 1.0, "h": 5.0, "d": 2.0, "Wo": 5.0, "Mt": 10.0, "m2": 0.3}
_RENTAL = re.compile(r"vorhalt|vorhaltung|miete|vorzuhalten", re.I)


def check_cent_prices(boq: BoQ) -> list[Flag]:
    """Unit prices below any plausible cost (e.g. €0.95/t, €0.05/m³): decimal typo or speculative pricing."""
    out = []
    for it in boq.items:
        u = norm_unit(it.unit)
        floor = PRICE_FLOOR.get(u)
        if floor is None or not it.up or it.up <= 0 or not it.qty or it.provisional:
            continue
        if u == "h" and _RENTAL.search(it.text):
            floor = 1.0
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
    pi = boq.parse_info or {}
    if pi.get("encoding_broken"):
        out.append(Flag("R21", "Zeichensatz fehlerhaft", "high",
                        "Umlaute sind zerstört („GrÃ¼ndung“ statt „Gründung“) – die Datei wurde mit falscher Kodierung "
                        "gespeichert. Texte (und Suchbegriffe) können verfälscht sein.", reference="Datenqualität",
                        suggestion="Datei in UTF-8 neu exportieren lassen.",
                        en=dict(title="Broken character encoding", message="Umlauts are corrupted ('GrÃ¼ndung' instead of "
                                "'Gründung') – the file was saved with the wrong encoding; texts may be distorted.",
                                suggestion="Ask for a new UTF-8 export.")))
    if pi.get("truncated"):
        out.append(Flag("R21", "Datei unvollständig", "high",
                        "Die Datei endet mitten in einer Zeile – sie wurde abgeschnitten. Positionen und Summen fehlen vermutlich.",
                        reference="Datenqualität", suggestion="Vollständige Datei anfordern.",
                        en=dict(title="File incomplete", message="The file ends in the middle of a row – it was cut off. "
                                "Items and totals are probably missing.", suggestion="Request the complete file.")))
    for it in boq.items:
        fmt = [i[4:] for i in it.issues if i.startswith("fmt:")]
        bad = [i for i in it.issues if not i.startswith("fmt:")]
        if fmt:
            out.append(Flag("R22", "Zahlenformat: Punkt statt Komma", "medium",
                            f"{', '.join(fmt)} – im deutschen Format steht hier ein Punkt als Dezimaltrenner. Gelesen als "
                            f"{de(it.up)} € EP; bei anderer Lesart (Tausenderpunkt) wäre der Wert 100-fach.",
                            oz=it.oz, reference="DIN 5008 / GAEB-Zahlenformat",
                            suggestion="Preis im Angebot einheitlich mit Komma schreiben; Wert prüfen.",
                            en=dict(title="Number format: dot instead of comma",
                                    message=f"{', '.join(fmt)} – German format expects a comma; a dot is used as decimal separator. "
                                            f"Read as €{E(it.up)} unit price; read as a thousands separator the value would be 100× larger.",
                                    suggestion="Write prices consistently with a comma; check the value.")))
        if bad:
            out.append(Flag("R21", "Wert nicht lesbar", "high",
                            f"Feld(er) mit ungültigem Zahlenformat: {', '.join(bad)} – Wert wurde nicht übernommen.",
                            oz=it.oz, reference="GAEB DA XML / Datenqualität",
                            suggestion="Wert im Quell-LV korrigieren (Tippfehler, Buchstabe statt Ziffer, doppeltes Komma).",
                            en=dict(title="Unreadable value",
                                    message=f"Field(s) with invalid number format: {', '.join(bad)} – value was not taken over.",
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
    rx = re.compile(r"\b(\d[\d.,]*)\s*(DM|USD|CHF|GBP|\$|£)(?=\W|$)|\b(DM|USD|CHF|GBP)\s*\d"
                    r"|\b(?:abrechnung|abgerechnet|preise?|zahlung|bezahlung|vergütung|billing|payment)\s+(?:\w+\s+){0,2}(?:in|auf|in der währung)\s+(?:DM|USD|CHF|GBP|US-Dollar|Dollar|Franken)\b", re.I)
    for it in boq.items:
        m = rx.search(it.text + " " + " ".join(i.split(":", 1)[1] for i in it.issues if i.startswith("Währung:")))
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
        zero_width = [c for c in inv if c != "\u00ad"]
        if len(inv) >= 3 or zero_width:
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


# ---------------------------------------------------------------- printed totals vs. items

def check_totals(boq: BoQ) -> list[Flag]:
    """Compare totals printed on the document with the sum of the items read. A gap means items were deleted,
    added or changed after the totals were calculated – or that the reader missed items."""
    t = boq.totals or {}
    priced = [i for i in boq.items if i.it is not None or (i.qty is not None and i.up is not None)]
    if not t or len(priced) < 0.5 * max(1, len(boq.items)):
        return []
    out = []
    sum_main, sum_all = boq.total, sum(i.total for i in boq.items)
    rate = t.get("vat_rate") or 0.19
    cands = []
    if t.get("net"):
        cands.append((t["net"], "Nettosumme", "net total"))
    if t.get("vat") and t.get("vat_rate"):
        cands.append((t["vat"] / t["vat_rate"], f"MwSt.-Zeile ({de(t['vat'])} € / {t['vat_rate']*100:g} %)",
                      f"VAT line (€{E(t['vat'])} / {t['vat_rate']*100:g}%)"))
    if t.get("gross"):
        cands.append((t["gross"] / (1 + rate), f"Gesamtsumme brutto {de(t['gross'])} € ÷ {1+rate:g}",
                      f"gross total €{E(t['gross'])} ÷ {1+rate:g}"))
    elif t.get("total") and not cands:
        cands.append((t["total"], "Gesamtsumme", "grand total"))
    if cands:
        net, src_de, src_en = cands[0]
        tol = max(1.0, 0.0005 * net)
        opt = [i for i in boq.items if (i.provisional or i.alternative) and i.total]
        if opt and abs(net - sum_all) <= tol and abs(net - sum_main) > tol:
            ozs = ", ".join(i.oz for i in opt[:10])
            out.append(Flag("R26", "Bedarfs-/Wahlpositionen in der Angebotssumme", "high",
                            f"Die gedruckte Nettosumme {de(net)} € enthält {len(opt)} Bedarfs-/Wahlpositionen ({ozs}; "
                            f"{de(sum_all - sum_main)} €). Diese gehören nicht in die Wertungssumme – sonst ist das Angebot "
                            "zu hoch und nicht vergleichbar.", reference="VOB/A § 7 Abs. 1 Nr. 4; Wertung nach § 16d",
                            exposure_eur=sum_all - sum_main, suggestion="Bedarfs-/Wahlpositionen aus der Angebotssumme herausnehmen (nur EP angeben).",
                            en=dict(title="Optional/alternative items included in the bid total",
                                    message=f"The printed net total €{E(net)} includes {len(opt)} optional/alternative items ({ozs}; "
                                            f"€{E(sum_all - sum_main)}). They do not belong in the evaluated total – the bid is too high "
                                            "and not comparable.", suggestion="Take optional/alternative items out of the total (unit price only).")))
            for i in opt:
                out.append(Flag("R26", "Bedarfs-/Wahlposition eingerechnet", "medium",
                                "Diese Bedarfs-/Wahlposition ist in der gedruckten Angebotssumme enthalten.", oz=i.oz,
                                reference="VOB/A § 7 Abs. 1 Nr. 4", exposure_eur=i.total,
                                en=dict(title="Optional/alternative item included", message="This optional/alternative item is "
                                        "included in the printed bid total.", suggestion="")))
            cands = []
        if min(abs(net - sum_main), abs(net - sum_all)) > tol:
            got = sum_main if abs(net - sum_main) <= abs(net - sum_all) else sum_all
            diff = net - got
            out.append(Flag("R26", "Summen stimmen nicht: gedruckte Summe ≠ Positionen", "high",
                            f"Laut {src_de} beträgt die Nettosumme {de(net)} €, die gelesenen Positionen ergeben {de(got)} € "
                            f"(Differenz {de(diff)} €). Positionen wurden gelöscht, eingefügt oder geändert, ohne die Summen anzupassen "
                            "(bei PDF-Ausdrucken auch möglich: Position nicht lesbar).",
                            reference="Rechnerische Prüfung (VOB/A § 16c Abs. 2)", exposure_eur=abs(diff),
                            suggestion="Positionen gegen Original-LV abgleichen; fehlende/geänderte Positionen suchen (Bereichssummen unten).",
                            en=dict(title="Totals don't match: printed total ≠ items",
                                    message=f"According to the {src_en} the net total is €{E(net)}, but the items read add up to €{E(got)} "
                                            f"(difference €{E(diff)}). Items were deleted, added or changed without updating the totals "
                                            "(with PDF prints also possible: an item could not be read).",
                                    suggestion="Compare the items with the original BoQ; look for missing/changed items (section totals below).")))
        if t.get("vat") and t.get("gross") and abs(net + t["vat"] - t["gross"]) > max(1.0, 0.0005 * t["gross"]):
            out.append(Flag("R26", "Summenblock in sich widersprüchlich", "high",
                            f"Netto {de(net)} € + MwSt. {de(t['vat'])} € ≠ Brutto {de(t['gross'])} €.",
                            reference="Rechnerische Prüfung", exposure_eur=abs(net + t["vat"] - t["gross"]),
                            suggestion="Summenblock nachrechnen.",
                            en=dict(title="Totals block contradicts itself",
                                    message=f"Net €{E(net)} + VAT €{E(t['vat'])} ≠ gross €{E(t['gross'])}.",
                                    suggestion="Recalculate the totals block.")))
    # section totals: pick the deepest printed level per section (e.g. 4.1 and 4)
    secs = t.get("sections") or {}
    by_sec = defaultdict(float)
    for i in boq.items:
        parts = i.oz.split(".")
        for d in range(1, len(parts)):
            by_sec[".".join(parts[:d])] += i.total
    reported = []
    for oz in sorted(secs, key=lambda o: (-o.count("."), o)):
        if any(r.startswith(oz + ".") for r in reported):
            continue                      # the gap is already reported at a deeper level
        printed, got = secs[oz], by_sec.get(oz, 0.0)
        if abs(printed - got) > max(1.0, 0.0005 * printed):
            reported.append(oz)
            label = boq.sections.get(oz, "")
            out.append(Flag("R26", f"Bereichssumme {oz} stimmt nicht", "high",
                            f"Gedruckte Summe {oz} {label}: {de(printed)} €, Positionen ergeben {de(got)} € (Differenz {de(printed-got)} €). "
                            "Hier fehlen oder wurden Positionen geändert.",
                            oz=oz, reference="Rechnerische Prüfung (VOB/A § 16c Abs. 2)", exposure_eur=abs(printed - got),
                            suggestion=f"Positionen in {oz} mit dem Original-LV vergleichen.",
                            en=dict(title=f"Section total {oz} does not match",
                                    message=f"Printed total {oz} {label}: €{E(printed)}, items add up to €{E(got)} "
                                            f"(difference €{E(printed-got)}). Items are missing or were changed here.",
                                    suggestion=f"Compare the items in {oz} with the original BoQ.")))
    return out


# ---------------------------------------------------------------- missing / truncated short texts

_DANGLING = re.compile(r"(?:\b\d+\s*[x×]|(?:^|\s)(?:und|oder|mit|für|aus|bis|von|in|im|zum|zur|der|die|das|inkl\.?|ca\.?|d\s*=|dn|da)|\s[\-–/(+=]|=)\s*$", re.I)


def check_short_text(boq: BoQ) -> list[Flag]:
    """A priced item must say what is priced. Empty, cut-off or one-word short texts without a long text
    leave the scope open – the bidder prices the wrong thing or the client later reads more into it."""
    out = []
    has_texts = sum(1 for i in boq.items if len(i.short_text.strip()) >= 8) >= 0.5 * max(1, len(boq.items))
    if not has_texts:
        return []                         # price-only file (GAEB D84 etc.): texts are simply not included
    for it in boq.items:
        lt = it.long_text.strip()
        st0 = it.short_text.strip()
        if lt and len(lt) >= 25:
            if not st0 or _DANGLING.search(st0):           # long text exists, but the short text is empty / cut off
                kind_de, kind_en = ("Kurztext fehlt", "Short text missing") if not st0 else ("Kurztext abgeschnitten", "Short text cut off")
                out.append(Flag("R27", kind_de, "medium",
                                (f"„{st0}“ endet unvollständig" if st0 else "Kein Kurztext") + " – der Langtext ist vorhanden, "
                                "aber der Kurztext (Vertragsbezeichnung) ist fehlerhaft.",
                                oz=it.oz, reference="VOB/A § 7 Abs. 1 Nr. 1", suggestion="Kurztext ergänzen bzw. korrigieren.",
                                en=dict(title=kind_en, message=(f"'{st0}' ends incomplete" if st0 else "No short text") +
                                        " – the long text exists, but the short text (contract designation) is faulty.",
                                        suggestion="Complete or correct the short text.")))
            continue
        st = lt if st0 and lt.startswith(st0) else f"{st0} {lt}"   # a wrapped short text continues on the next line
        st = re.sub(r"\s+", " ", st).strip()
        val = it.total
        if not st:
            sev, de_t, en_t, why_de, why_en = "high", "Kurztext fehlt", "Short text missing", \
                "Position ohne jede Beschreibung", "item without any description"
        elif _DANGLING.search(st):
            sev, de_t, en_t, why_de, why_en = "medium", "Kurztext abgeschnitten", "Short text cut off", \
                f"„{st}“ endet unvollständig", f"'{st}' ends incomplete"
        elif len(st.split()) == 1 and len(st) < 16 and not st.lower().startswith("wie vor"):
            sev = "medium" if val >= 1000 else "low"
            de_t, en_t = "Kurztext ohne Angaben", "Short text without details"
            why_de, why_en = f"nur „{st}“ – Typ, Maß, Material fehlen", f"only '{st}' – type, size, material missing"
        else:
            continue
        out.append(Flag("R27", de_t, sev,
                        f"{why_de}, kein Langtext. Was genau zu liefern/leisten ist, bleibt offen ({de(val)} €).",
                        oz=it.oz, reference="VOB/A § 7 Abs. 1 Nr. 1 (eindeutige, erschöpfende Beschreibung)", exposure_eur=0.15 * val,
                        suggestion="Vollständigen Kurz- und Langtext anfordern (Typ, Abmessung, Material, Norm).",
                        en=dict(title=en_t, message=f"{why_en}, no long text. What exactly must be supplied/done stays open (€{E(val)}).",
                                suggestion="Request the full short and long text (type, size, material, standard).")))
    return out


# ---------------------------------------------------------------- identical items (short-text-only prints)

def check_identical(boq: BoQ) -> list[Flag]:
    """Same short text, unit and unit price in the same section, no long text to tell them apart: the same work
    is probably listed twice (copy-paste) – or the distinguishing text was lost."""
    out = []
    groups = defaultdict(list)
    pos = {id(it): k for k, it in enumerate(boq.items)}
    norm = lambda t: re.sub(r"\s+", " ", t.strip().lower())

    def prev_text(it):
        k = pos[id(it)]
        return norm(boq.items[k - 1].short_text) if k > 0 else ""

    for it in boq.items:
        st = norm(it.short_text)
        if len(st) < 8 or len(it.long_text.strip()) >= 25:
            continue                     # items with long texts are handled by the duplicate check (R04)
        groups[(it.oz.rsplit(".", 1)[0], st, norm_unit(it.unit), it.up)].append(it)   # same sub-section
    for (_, st, _, _), its in groups.items():
        for b in its[1:]:
            a = its[0]
            if a.oz == b.oz:
                continue                 # same OZ twice: reported as duplicate item number (R12)
            if st.startswith("wie vor") and pos[id(b)] - pos[id(a)] > 1 and prev_text(a) != prev_text(b):
                continue                 # "wie vor, jedoch X" refers to different predecessors -> different work
            out.append(Flag("R04", "Identische Position (doppelt?)", "high",
                            f"OZ {b.oz} „{b.short_text}“ ist identisch mit OZ {a.oz} (Kurztext, Einheit, EP {de(b.up) if b.up is not None else '–'} €). "
                            "Doppelt erfasste Leistung würde zweimal bezahlt bzw. eine Position wurde falsch kopiert.",
                            oz=b.oz, reference="VOB/A § 7 Abs. 1 (eindeutige Beschreibung)", exposure_eur=b.total,
                            suggestion=f"Klären, ob OZ {b.oz} eine andere Leistung als OZ {a.oz} meint; sonst streichen.",
                            en=dict(title="Identical item (duplicate?)",
                                    message=f"Item {b.oz} '{b.short_text}' is identical to item {a.oz} (short text, unit, unit price "
                                            f"€{E(b.up) if b.up is not None else '–'}). Work listed twice would be paid twice, or an item was copied wrongly.",
                                    suggestion=f"Clarify whether item {b.oz} means different work than {a.oz}; otherwise delete it.")))
    return out


# ---------------------------------------------------------------- contract penalties

def check_penalties(boq: BoQ) -> list[Flag]:
    out = []
    public = _is_public(boq)
    base = boq.total
    sources = [(it.oz, it.text, f"Pos. {it.oz}", f"Item {it.oz}") for it in boq.items] + \
              [("", n["text"], f"Vorbemerkung {n['ref']}", f"Note {n['ref']}".replace("Hinweis nach Pos.", "after item")) for n in boq.notes]
    seen = set()
    for oz, text, loc_de, loc_en in sources:
        low = re.sub(r"\s+", " ", text.lower())
        m = re.search(K.PENALTY, low)
        if not m:
            continue
        snip = _snippet(re.sub(r"\s+", " ", text), m)
        if snip[:80] in seen:
            continue
        seen.add(snip[:80])
        sent = _snippet(low, m).lower()
        reasons_de, reasons_en, sev = [], [], "medium"
        am = re.search(K.PENALTY_AMOUNT, sent)
        pm = re.search(K.PENALTY_PCT, sent)
        if am:
            from .gaeb_parser import parse_number
            amount = parse_number(am.group(1)) or 0
            per = "Woche" if "woche" in am.group(0) else "Tag"
            daily = amount / (7 if per == "Woche" else 1)
            if base > 0:
                pct = 100 * daily / base
                reasons_de.append(f"{de(amount, 0)} € pro {per} = {pct:.2f} % der Angebotssumme ({de(base, 0)} €) je Tag – "
                                  "in AGB gelten ca. 0,2–0,3 % je Werktag als Obergrenze")
                reasons_en.append(f"€{E(amount, 0)} per {'week' if per == 'Woche' else 'day'} = {pct:.2f}% of the bid total "
                                  f"(€{E(base, 0)}) per day – standard terms are usually limited to about 0.2–0.3% per working day")
                if pct > 0.3:
                    sev = "high"
            else:
                reasons_de.append(f"{de(amount, 0)} € pro {per}")
                reasons_en.append(f"€{E(amount, 0)} per {'week' if per == 'Woche' else 'day'}")
        elif pm:
            pct = float(pm.group(1).replace(",", "."))
            reasons_de.append(f"{pm.group(1)} % je Tag")
            reasons_en.append(f"{pct:g}% per day")
            sev = "high" if pct > 0.3 else sev
        if not re.search(K.PENALTY_CAP, sent):
            reasons_de.append("keine Obergrenze (Rechtsprechung: max. 5 % der Auftragssumme)")
            reasons_en.append("no cap (case law: max. 5% of the contract sum)")
            sev = "high" if (am or pm) else sev
        vd = re.search(K.VAGUE_DEADLINE, sent)
        if vd:
            reasons_de.append(f"knüpft an eine unbestimmte Frist an („{vd.group(0)}“) – intransparent nach § 307 Abs. 1 S. 2 BGB")
            reasons_en.append(f"tied to an undefined deadline ('{vd.group(0)}') – non-transparent under § 307(1) sentence 2 BGB")
            sev = "high"
        ctx_de = "Öffentlicher AG: Vertragsstrafen nur bei erheblichen Nachteilen (VOB/A § 9a)." if public else                  "Privater AG: nur über AGB-Kontrolle angreifbar – einpreisen oder streichen lassen."
        ctx_en = "Public client: penalties only for significant disadvantages (VOB/A § 9a)." if public else                  "Private client: only contestable via standard-terms control – price it in or have it removed."
        f = Flag("R20", "Vertragsrisiko: Vertragsstrafe / Strafzahlung", sev,
                 f"{loc_de}: „{snip}“ – " + "; ".join(reasons_de or ["Strafzahlung zu Lasten des AN"]) + f". {ctx_de}",
                 oz=oz, reference="VOB/B § 11; §§ 339 ff., 307 BGB; BGH VII ZR 210/01",
                 exposure_eur=0.05 * base if sev == "high" else 0.0,
                 suggestion="Bieterfrage stellen: konkrete Frist, Tagessatz ≤ 0,2 % je Werktag, Obergrenze 5 %.",
                 en=dict(title="Contract risk: contract penalty",
                         message=f"{loc_en}: '{snip}' – " + "; ".join(reasons_en or ["penalty payment on the contractor"]) + f". {ctx_en}",
                         suggestion="Ask a bidder question: fixed deadline, daily rate ≤ 0.2% per working day, cap 5%."))
        f.question = {"de": f"{loc_de}: „{snip[:160]}“ – Bitte nennen Sie die maßgebliche Frist (Datum), die Höhe der Vertragsstrafe in % "
                            "der Auftragssumme je Werktag und die Obergrenze. Wir bitten um Anpassung an VOB/B § 11 (max. 0,2 %/Werktag, max. 5 %).",
                      "en": f"{loc_en}: '{snip[:160]}' – Please state the relevant deadline (date), the penalty as % of the contract sum per working "
                            "day and its cap. We ask to align it with VOB/B § 11 (max. 0.2%/working day, max. 5%)."}
        out.append(f)
    return out


# ---------------------------------------------------------------- short text vs. long text contradictions

_SPECS = [  # (name, regex capturing the value)
    ("DN", r"\bDN\s*(\d{2,4})\b"), ("da", r"\bda\s*(\d{2,3})\b"),
    ("Betonklasse", r"\bC\s?(\d{2}/\d{2})\b"), ("Expositionsklasse", r"\b(X[CDFAM]\d)\b"),
    ("Dicke", r"\b(?:d|dicke|stärke)\s*=?\s*(\d+(?:,\d+)?)\s*(?:cm|mm)\b"), ("Höhe", r"\bh\s*=\s*(\d+(?:,\d+)?)\s*(?:cm|mm|m)\b"),
    ("Belastungsklasse", r"\b([ABCDEF]\s?\d{2,3})\b(?=.*(?:klasse|abdeckung|deckel|rost))"),
    ("Korngröße", r"(?:körnung|korngruppe|kies|splitt|schotter|edelsplitt|mineralgemisch|brechsand)\s*(\d{1,2}/\d{1,2})\b"),
    ("Stahlgüte", r"\b(B\s?500\s?[AB])\b"),
]


# word pairs with opposite meaning – one letter or prefix apart, huge cost difference
ANTONYMS = [("bewehrt", "unbewehrt"), ("wasserdurchlässig", "wasserundurchlässig"), ("durchlässig", "undurchlässig"),
            ("brennbar", "nichtbrennbar|unbrennbar|nicht brennbar"), ("tragend", "nichttragend|nicht tragend"),
            ("befestigt", "unbefestigt"),
            ("frostsicher", "nicht frostsicher"), ("belastbar", "nicht belastbar"), ("befahrbar", "nicht befahrbar"),
            ("gedämmt", "ungedämmt"), ("beschichtet", "unbeschichtet"), ("verzinkt", "unverzinkt")]


def check_contradictions(boq: BoQ) -> list[Flag]:
    """The same specification with different values in the short and the long text (DN 150 vs DN 200, C25/30 vs
    C30/37): which one is priced and which one is built? A classic source of disputes."""
    out = []
    for it in boq.items:
        st, lt = it.short_text, it.long_text
        if not st or not lt:
            continue
        lines = [l for l in lt.split("\n") if l.strip()]
        if lines and (lines[0][:1].islower() or re.search(r"(?:\bbis|\bund|\bDN|[-–/=,(])\s*$", st)):
            st, lines = st + " " + lines[0], lines[1:]   # wrapped short text continues on the next line
        lt = "\n".join(lines)
        if not lt:
            continue
        diffs = []
        for name, rx in _SPECS:
            a = {m.group(1).replace(" ", "").lower() for m in re.finditer(rx, st, re.I)}
            b = {m.group(1).replace(" ", "").lower() for m in re.finditer(rx, lt, re.I)}
            if a and b and not (a & b) and not ({x for x in b if re.search(rf"\b{re.escape(x)}\b", st, re.I)} or
                                                {x for x in a if re.search(rf"\b{re.escape(x)}\b", lt, re.I)}):
                diffs.append((name, "/".join(sorted(a)), "/".join(sorted(b))))
        sl, ll = st.lower(), lt.lower()
        for pos_w, neg_w in ANTONYMS:
            a_pos = re.search(rf"(?<![a-zäöü]){pos_w}", sl) and not re.search(neg_w, sl)
            b_neg = re.search(neg_w, ll) and not re.search(rf"(?<![a-zäöü]){pos_w}", ll)
            a_neg = re.search(neg_w, sl) and not re.search(rf"(?<![a-zäöü]){pos_w}", sl)
            b_pos = re.search(rf"(?<![a-zäöü]){pos_w}", ll) and not re.search(neg_w, ll)
            if (a_pos and b_neg) or (a_neg and b_pos):
                x, y = (pos_w, neg_w) if a_pos else (neg_w, pos_w)
                diffs.append(("Gegenteil", x.split("|")[0], y.split("|")[0]))
        if diffs:
            d_de = "; ".join(f"{n}: Kurztext {x} ≠ Langtext {y}" for n, x, y in diffs)
            out.append(Flag("R28", "Widerspruch Kurztext ↔ Langtext", "high",
                            f"{d_de}. Unklar, was kalkuliert und was gebaut wird – eine klassische Ursache für Nachtragsstreit.",
                            oz=it.oz, reference="VOB/A § 7 Abs. 1 Nr. 1; VOB/B § 1 Abs. 2", exposure_eur=0.1 * it.total,
                            suggestion="Bieterfrage: welcher Wert gilt?",
                            en=dict(title="Contradiction short text ↔ long text",
                                    message="; ".join(f"{n}: short text {x} ≠ long text {y}" for n, x, y in diffs) +
                                            ". It is unclear what is priced and what is built.",
                                    suggestion="Bidder question: which value applies?")))
    return out


# ---------------------------------------------------------------- spelling (construction vocabulary)

_VOCAB = None


def _vocab() -> dict:
    global _VOCAB
    if _VOCAB is None:
        import json
        from pathlib import Path as _P
        try:
            _VOCAB = json.loads((_P(__file__).parent / "vocab_de.json").read_text(encoding="utf-8"))
        except Exception:
            _VOCAB = {}
    return _VOCAB


# material / work / specification terms: a typo here changes what is built and priced
SPEC_TERMS = (r"beton|bewehr|stahl|schalung|abdicht|dämm|dicht|rohr|schacht|asphalt|pflaster|estrich|putz|mauer|ziegel|"
              r"kalksand|holz|glas|fenster|tür|dach|fliese|naturstein|gips|trocken|kanal|leitung|kabel|schieber|armatur|"
              r"spundw|verbau|pfahl|anker|aushub|verfüll|frostschutz|schotter|splitt|kies|sand|boden|deponie|entsorg|"
              r"klasse|festigkeit|exposition|belastung|brandschutz|wärme|schall")
_FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "s"})


def _looks_like_typo(w: str, v: str) -> bool:
    """A typo, not a German word form: the edit is inside the word (Betton, Rohgraben, herstelen) or a doubled letter
    (Schalunng, Bewehhrung) – not an ending (Steine/Steinen, Planum/Planums) and not just an umlaut (starke/stärke)."""
    import difflib
    if w.translate(_FOLD) == v.translate(_FOLD) or w.replace("ß", "ss") == v.replace("ß", "ss"):
        return False
    if len(w) == len(v) + 1 and any(w[:i] + w[i + 1:] == v for i in range(1, len(w)) if w[i] == w[i - 1]):
        return True                                    # one letter typed twice: Schalunng, Oberbodden, lössen
    short, long_ = sorted((w, v), key=len)
    if long_.startswith(short) or (len(w) == len(v) and w[:-1] == v[:-1]):
        return False                                   # inflection: only the ending differs (Stein/Steine, lagern/lagert)
    if len(v) == len(w) + 1 and len(w) >= 4:
        return True                                    # a letter dropped inside the word: abtragn, Dike, Schalng
    ops = [o for o in difflib.SequenceMatcher(None, w, v).get_opcodes() if o[0] != "equal"]
    return bool(ops) and all(o[1] >= 2 and o[2] <= len(w) - 2 for o in ops)   # edit inside the word


def _compound_typo(w: str, vocab: dict) -> str | None:
    """German compounds are rarely in a word list as a whole. A doubled letter in any part ('fundamentschalunng',
    'bewehhrungsstahl') is a typo when removing it splits the word into two known words and the original does not split."""
    if len(w) < 9:
        return None
    pre = lambda x: vocab.get(x, 0) >= 3 or (x.endswith("s") and vocab.get(x[:-1], 0) >= 3)
    splits = lambda x: any(pre(x[:j]) and vocab.get(x[j:], 0) >= 8 for j in range(3, len(x) - 3))
    if splits(w):
        return None
    for f in {w[:i] + w[i + 1:] for i in range(1, len(w)) if w[i] == w[i - 1]}:
        if f in vocab or splits(f):
            return f
    return None


# real construction words that are one letter away from a more frequent one (Steifen/Streifen, Fugensand/Fugenband)
EXTRA_WORDS = {"steifen", "steife", "fugensand", "splittbett", "läuferverband", "verbauplatten", "haufwerk", "kaltfräsen",
               "rückverankerung", "spundwand", "spundbohlen", "trägerbohlwand", "kanaldielen", "ringraum", "rohrsohle",
               "schachtring", "schachthals", "konus", "gerinne", "berme", "böschung", "mutterboden", "rasengitter",
               "schotterrasen", "pflasterklinker", "rinnenplatte", "bankett", "frostschürze", "dränmatte"}


def check_spelling(boq: BoQ) -> list[Flag]:
    """Words that are one typo away from a common construction term ('Betton' → 'Beton', 'Rohgraben' → 'Rohrgraben').
    Vocabulary: words used across the organisers' BoQs plus the words used repeatedly in this BoQ itself."""
    from rapidfuzz.distance import Levenshtein
    vocab = dict(_vocab())
    for w_ in EXTRA_WORDS:
        vocab[w_] = max(vocab.get(w_, 0), 20)
    local = Counter(w.lower() for it in boq.items for w in re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", it.text))
    for w, c in local.items():
        if c >= 3:
            vocab[w] = vocab.get(w, 0) + c
    if len(vocab) < 50:
        return []
    by_len: dict[int, list[str]] = defaultdict(list)
    for w, c in vocab.items():
        if c >= 3:
            by_len[len(w)].append(w)
    out = []
    for it in boq.items:
        hits = []
        short_words = {x.lower() for x in re.findall(r"[A-Za-zÄÖÜäöüß]{5,}", it.short_text)}
        words = re.findall(r"[A-Za-zÄÖÜäöüß]{5,}", it.text) + \
            [w for w in re.findall(r"\b[A-Za-zÄÖÜäöüß]{4}\b", it.short_text) if w[:1].isupper()]   # Dike → Dicke
        for w in words:
            lw = w.lower()
            if lw in vocab or w.isupper() or any(c.isupper() for c in w[1:]):   # codes, names, PDF artefacts
                continue
            comp = _compound_typo(lw, vocab)                   # Fundamentschalunng → …schalung
            if comp and local[lw] <= 1:
                hits.append((w, comp))
                continue
            maxd = 1                                       # one typo; two edits mostly hit real words (Bauheizung/Bauleitung)
            cands = [v for n in range(len(lw) - maxd, len(lw) + maxd + 1) for v in by_len.get(n, [])
                     if Levenshtein.distance(lw, v, score_cutoff=maxd) <= maxd]
            if cands:
                best = max(cands, key=lambda v: vocab[v])
                if vocab[best] >= 8 and best[:2] == lw[:2] and _looks_like_typo(lw, best) and local[lw] <= 1:
                    hits.append((w, best))
        if hits:
            txt = ", ".join(f"„{a}“ → {b.capitalize() if a[:1].isupper() else b}" for a, b in hits[:4])
            # impact, not cosmetics: the short text is the contract designation; a typo in a material / specification
            # term on a valuable item can change what is owed (and what gets priced)
            in_short = any(a.lower() in short_words for a, _ in hits)
            spec = any(re.search(SPEC_TERMS, b) for _, b in hits)
            if in_short and spec and it.total >= 2000:
                sev, why_de, why_en = "high", "Tippfehler in einem Material-/Leistungsbegriff des Kurztexts", \
                    "typo in a material/work term of the short text"
            elif in_short and (spec or it.total >= 10000):
                sev, why_de, why_en = "medium", "Tippfehler im Kurztext (Vertragsbezeichnung)", "typo in the short text (contract designation)"
            elif in_short:
                sev, why_de, why_en = "low", "Tippfehler im Kurztext", "typo in the short text"
            else:
                sev, why_de, why_en = "low", "Tippfehler im Langtext", "typo in the long text"
            out.append(Flag("R29", "Tippfehler im Text", sev,
                            f"{why_de}: {txt}. Was genau ist geschuldet? Ein falsch geschriebener Begriff kann eine andere Leistung "
                            f"bezeichnen oder unverständlich sein ({de(it.total)} €).", oz=it.oz, reference="VOB/A § 7 Abs. 1 Nr. 1",
                            exposure_eur=(0.05 if sev == "high" else 0.0) * it.total,
                            suggestion="Schreibweise klären – bei Material-/Klassenbegriffen als Bieterfrage.",
                            en=dict(title="Typo in text", message=f"{why_en.capitalize()}: {txt}. What exactly is owed? A misspelt term "
                                                                  f"can denote different work or be unintelligible (€{E(it.total)}).",
                                    suggestion="Clarify the spelling – for material/class terms as a bidder question.")))
    return out


# ---------------------------------------------------------------- item numbers (OZ)

def check_numbering(boq: BoQ) -> list[Flag]:
    """Letters inside item numbers (2.1.3O), numbers out of order, and gaps in an otherwise regular numbering –
    a gap often means items were deleted."""
    out = []
    groups: dict[str, list[Item]] = defaultdict(list)
    for it in boq.items:
        if re.search(r"\d[OolI]|[OolI]\d|[OolI]$", it.oz.split(".")[-1]) or re.search(r"\d[Oo]\b", it.oz):
            out.append(Flag("R30", "Ordnungszahl fehlerhaft", "medium",
                            f"Ordnungszahl „{it.oz}“ enthält Buchstaben (z. B. O statt 0) – Zuordnung und Abrechnung werden fehleranfällig.",
                            oz=it.oz, reference="GAEB / Gliederung des LV", suggestion="Ordnungszahl korrigieren.",
                            en=dict(title="Faulty item number", message=f"Item number '{it.oz}' contains letters (e.g. O instead of 0).",
                                    suggestion="Correct the item number.")))
            continue
        parent, _, last = it.oz.rpartition(".")
        if last.isdigit():
            groups[parent].append(it)
    depth = Counter(i.oz.count(".") for i in boq.items if not re.search(r"[A-Za-z]", i.oz)).most_common(1)
    if depth and len(boq.items) >= 10:
        d0, n0 = depth[0]
        if n0 >= 0.8 * len(boq.items):
            for it in boq.items:
                if it.oz.count(".") < d0 and not re.search(r"[A-Za-z]", it.oz):   # a level missing; deeper = sub-item
                    out.append(Flag("R30", "Ordnungszahl passt nicht zur Gliederung", "medium",
                                    f"Pos. {it.oz} hat {it.oz.count('.') + 1} Stufen, das übrige LV {d0 + 1} – Tippfehler oder fehlender Abschnitt?",
                                    oz=it.oz, reference="Gliederung des LV (GAEB-OZ-Maske)", suggestion="Ordnungszahl prüfen.",
                                    en=dict(title="Item number does not fit the structure",
                                            message=f"Item {it.oz} has {it.oz.count('.') + 1} levels, the rest of the BoQ {d0 + 1} – typo or missing section?",
                                            suggestion="Check the item number.")))
    for parent, its in groups.items():
        nums = [int(i.oz.rpartition(".")[2]) for i in its]
        for a, b, ia, ib in zip(nums, nums[1:], its, its[1:]):
            if b < a:
                for x in (ia, ib):                         # the swapped pair: both items
                    out.append(Flag("R30", "Ordnungszahl außer Reihenfolge", "low",
                                    f"Pos. {ia.oz} und {ib.oz} stehen in falscher Reihenfolge (eingeschoben oder vertauscht?).",
                                    oz=x.oz, reference="Gliederung des LV", suggestion="Reihenfolge prüfen.",
                                    en=dict(title="Item number out of order",
                                            message=f"Items {ia.oz} and {ib.oz} are in the wrong order (inserted or swapped?).",
                                            suggestion="Check the order.")))
        steps = [b - a for a, b in zip(nums, nums[1:]) if b > a]
        if len(steps) >= 4:
            step = Counter(steps).most_common(1)[0][0]
            if step > 0 and steps.count(step) >= 0.6 * len(steps):
                for a, b, ib in zip(nums, nums[1:], its[1:]):
                    if b - a >= 3 * step:
                        missing = (b - a) // step - 1
                        out.append(Flag("R30", "Lücke in der Nummerierung", "low",
                                        f"Zwischen {parent}.{a} und {ib.oz} fehlen rund {missing} Ordnungszahlen – wurden Positionen gelöscht?",
                                        oz=ib.oz, reference="Gliederung des LV", suggestion="Mit dem Original-LV abgleichen.",
                                        en=dict(title="Gap in the numbering",
                                                message=f"About {missing} item numbers are missing between {parent}.{a} and {ib.oz} – were items deleted?",
                                                suggestion="Compare with the original BoQ.")))
    return out


ITEM_RULES = [check_arithmetic, check_units, check_quantities, check_special_items, check_duplicates,
              check_prices, check_vague, check_parameters, check_outdated, check_long_text,
              check_parse_issues, check_value_format, check_currency, check_cent_prices, check_short_text, check_identical,
              check_contradictions, check_spelling, check_numbering, check_peer_prices, check_site_setup_share]
LV_RULES = [check_completeness, check_clauses, check_penalties, check_totals, check_injection, check_quantity_relations]

# contractor's view: what kind of finding is it?
CATEGORY = {"R01": "error", "R04": "error", "R06": "error", "R12": "error", "R13": "error", "R21": "error", "R22": "error",
            "R23": "error", "R02": "error", "R05": "error", "R24": "risk", "R25": "error",
            "R03": "risk", "R09": "risk", "R11": "risk", "R20": "risk", "R07": "risk",
            "R08": "opportunity", "R10": "opportunity", "R14": "opportunity", "R15": "opportunity", "R16": "risk",
            "R26": "error", "R27": "opportunity", "R28": "error", "R29": "error", "R30": "error", "R31": "error", "R32": "risk", "R33": "opportunity", "R34": "risk", "R35": "error", "M01": "risk", "M02": "risk", "S01": "security", "S02": "security"}


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
