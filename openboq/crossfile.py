"""Files that belong together: the same BoQ in several formats or versions (tender X83 + bid D84 + bid PDF, an original
and a revised copy …).

 * group_projects(): finds files of the same project by their item numbers and quantities, not by file name.
 * merge(): one combined BoQ per project – texts from the file that has texts (PDF/X83), prices from the priced file,
   all preliminary notes (clauses!) from every file, printed totals from whichever file carries them.
 * compare(): every difference between the versions is a finding – an item missing in one file (deleted/added),
   a different quantity, unit price, total or unit (changed after the tender), a changed short text.
"""
from __future__ import annotations

import re

from .model import BoQ, Flag, Item


def _key(oz: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"[.\s\-/_]+", oz.strip(".")) if p)   # 001-01-0010 = 1.1.10


def _order(k: tuple) -> tuple:
    """Sort key for item keys that mix numbers and text ("2.1.3O" → (2, 1, "3O"))."""
    return tuple((0, p, "") if isinstance(p, int) else (1, 0, str(p)) for p in k)


def _sig(b: BoQ) -> set:
    return {(_key(i.oz), round(i.qty, 3) if i.qty is not None else None) for i in b.items}


def _texted(b: BoQ) -> int:
    return sum(1 for i in b.items if len(i.short_text.strip()) >= 3)


def _norm_text(t: str) -> str:
    return re.sub(r"[^a-zäöüß0-9]+", "", t.lower())[:30]


def similarity(a: BoQ, b: BoQ, detail: bool = False):
    """How likely two files are the same BoQ – judged by content only (file names are ignored).
    Item numbers and quantities must overlap; where both files carry texts, the texts must agree too, so two different
    projects with the same standard numbering (1.1.10, 1.1.20 …) are not mixed up. Files of very different size are
    only grouped if the smaller one is clearly a cut-down version of the larger (texts agree)."""
    res = {"score": 0.0, "items": 0.0, "quantities": 0.0, "texts": None}
    ka, kb = {_key(i.oz) for i in a.items}, {_key(i.oz) for i in b.items}
    if ka and kb:
        oz = len(ka & kb) / min(len(ka), len(kb))
        sa, sb = _sig(a), _sig(b)
        qty = len(sa & sb) / max(1, min(len(sa), len(sb)))
        res.update(items=oz, quantities=qty)
        ma, mb = {_key(i.oz): i for i in a.items}, {_key(i.oz): i for i in b.items}
        both = [(ma[k], mb[k]) for k in ka & kb if len(ma[k].short_text.strip()) >= 3 and len(mb[k].short_text.strip()) >= 3]
        size = min(len(ka), len(kb)) / max(len(ka), len(kb))
        if len(both) >= 5:
            from rapidfuzz import fuzz
            agree = sum(1 for x, y in both if _norm_text(x.short_text) == _norm_text(y.short_text)
                        or fuzz.partial_ratio(x.short_text.lower(), y.short_text.lower()) >= 85) / len(both)
            res["texts"] = agree
            res["score"] = 0.0 if agree < 0.5 else (0.35 * oz + 0.35 * qty + 0.3 * agree)
        else:
            # no texts to compare: a small file sharing a few standard item numbers is not enough
            res["score"] = (0.5 * oz + 0.5 * qty) if size >= 0.5 else 0.0
    return res if detail else res["score"]


def fingerprint(b: BoQ) -> str:
    """Content hash: identical BoQs give the same fingerprint whatever the file is called."""
    import hashlib
    rows = sorted((_key(i.oz), round(i.qty or 0, 3), (i.unit or "").lower().rstrip("."), round(i.up or 0, 2),
                   round(i.it or 0, 2), _norm_text(i.short_text)) for i in b.items)
    return hashlib.sha1(repr(rows).encode()).hexdigest()


def duplicates(boqs: dict[str, BoQ]) -> dict[str, str]:
    """{copy: original} for files whose content is identical to an earlier file (renamed copies)."""
    seen, dup = {}, {}
    for n, b in boqs.items():
        if b is None or not b.items:
            continue
        fp = fingerprint(b)
        if fp in seen:
            dup[n] = seen[fp]
        else:
            seen[fp] = n
    return dup


def group_projects(boqs: dict[str, BoQ], threshold: float = 0.7) -> list[list[str]]:
    """Connected groups of files whose item numbers + quantities overlap ≥ threshold."""
    names = [n for n, b in boqs.items() if b is not None and len(b.items) >= 3]
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if similarity(boqs[a], boqs[b]) >= threshold:
                parent[find(a)] = find(b)
    groups: dict[str, list[str]] = {}
    for n in names:
        groups.setdefault(find(n), []).append(n)
    return [sorted(g) for g in groups.values() if len(g) > 1]


def merge(boqs: dict[str, BoQ], names: list[str]) -> BoQ:
    """Combined BoQ: the file with the most texts is the base; gaps are filled from the others."""
    files = [(n, boqs[n]) for n in names]
    base_name, base = max(files, key=lambda f: (_texted(f[1]), len(f[1].items)))
    priced = max(files, key=lambda f: sum(1 for i in f[1].items if i.up is not None))
    out = BoQ(project=base.project or next((b.project for _, b in files if b.project), ""),
              name="🔗 " + " + ".join(n for n, _ in files), currency=base.currency, phase=base.phase,
              client=base.client or next((b.client for _, b in files if b.client), ""))
    by_key = {n: {_key(i.oz): i for i in b.items} for n, b in files}
    order = [i.oz for i in base.items] + [i.oz for n, b in files if n != base_name for i in b.items]
    seen = set()
    for oz in order:
        k = _key(oz)
        if k in seen:
            continue
        seen.add(k)
        src = [by_key[n][k] for n, _ in files if k in by_key[n]]
        it0 = by_key[base_name].get(k) or src[0]
        it = Item(**{f: getattr(it0, f) for f in it0.__dataclass_fields__ if f != "issues"})
        it.issues = list(it0.issues)
        for other in src:
            if not it.short_text.strip() and other.short_text.strip():
                it.short_text = other.short_text
            if len(it.long_text) < len(other.long_text):
                it.long_text = other.long_text
            if not it.unit and other.unit:
                it.unit = other.unit
        pr = by_key[priced[0]].get(k)
        if pr is not None and it.up is None and pr.up is not None:
            it.up, it.it = pr.up, pr.it
        out.items.append(it)
    for n, b in files:                                    # notes and clauses from every file, de-duplicated
        for note in b.notes:
            sig = re.sub(r"\W+", "", note["text"].lower())[:200]
            if sig and not any(re.sub(r"\W+", "", x["text"].lower())[:200] == sig for x in out.notes):
                out.notes.append({"ref": f"{note['ref']} ({n})", "text": note["text"]})
        for oz, label in b.sections.items():
            out.sections.setdefault(oz, label)
    for _, b in sorted(files, key=lambda f: -len(f[1].totals or {})):
        for k, v in (b.totals or {}).items():
            out.totals.setdefault(k, v)
    out.parse_info = {"reader": "merged", "files": [n for n, _ in files], "base": base_name, "prices_from": priced[0]}
    return out


def compare(boqs: dict[str, BoQ], names: list[str]) -> list[Flag]:
    """Differences between versions of the same BoQ – each one is something that changed after the tender."""
    out: list[Flag] = []
    names = sorted(names, key=lambda n: -_texted(boqs[n]))      # the file with texts is the reference
    files = [(n, boqs[n]) for n in names]
    maps = {n: {_key(i.oz): i for i in b.items} for n, b in files}
    all_keys = sorted(set().union(*[set(m) for m in maps.values()]), key=_order)
    excerpts = {n for n in names if len(maps[n]) < 0.5 * len(all_keys)}   # trade package / extract of the full BoQ

    def near(a, b, rel=0.0005, abs_=0.011):
        # no value on one side (an unpriced tender vs. the priced bid) is not a difference
        if a is None or b is None or a != a or b != b:
            return True
        return abs(a - b) <= max(abs_, rel * abs(b))

    for k in all_keys:
        present = [n for n in names if k in maps[n]]
        oz = next(maps[n][k].oz for n in present)
        missing = [n for n in names if k not in maps[n] and n not in excerpts]
        if missing:
            ref = maps[present[0]][k]
            txt = next((maps[n][k].short_text for n in present if maps[n][k].short_text.strip()), "")
            out.append(Flag("X01", "Position fehlt in einer Fassung", "high",
                            f"Pos. {oz} „{txt[:60]}“ ({ref.total:,.2f} €) steht in {', '.join(present)}, "
                            f"fehlt aber in {', '.join(missing)} – gelöscht oder nachträglich eingefügt?",
                            oz=oz, reference="Abgleich der Fassungen (VOB/A § 13 Abs. 1 Nr. 5: keine Änderungen an den Vergabeunterlagen)",
                            exposure_eur=ref.total, suggestion="Klären, welche Fassung gilt; fehlende Position ergänzen.",
                            en=dict(title="Item missing in one version",
                                    message=f"Item {oz} '{txt[:60]}' (€{ref.total:,.2f}) is in {', '.join(present)} "
                                            f"but missing in {', '.join(missing)} – deleted or added later?",
                                    suggestion="Clarify which version applies; add the missing item.")))
        if len(present) < 2:
            continue
        # compare every file that has the item (an extract still counts where it overlaps). Per attribute the files
        # with the same value form groups; the largest group is the reference, so the odd one out is named after "vs."
        pairs: dict[tuple, list] = {}

        def note(a_n, b_n, de_, en_, e):
            d = pairs.setdefault((a_n, b_n), [[], [], 0.0])
            d[0].append(de_); d[1].append(en_); d[2] = max(d[2], e)

        def groups(files, same):
            gs: list[list[str]] = []
            for n in files:
                g = next((g for g in gs if same(maps[g[0]][k], maps[n][k])), None)
                (g.append(n) if g is not None else gs.append([n]))
            return sorted(gs, key=lambda g: (-len(g), names.index(g[0])))

        def report(files, same, de_fn, en_fn, exp_fn):
            gs = groups(files, same)
            if len(gs) < 2:
                return
            ref = maps[gs[0][0]][k]
            for g in gs[1:]:
                b = maps[g[0]][k]
                note(", ".join(gs[0]), ", ".join(g), de_fn(ref, b), en_fn(ref, b), exp_fn(ref, b))

        report([n for n in present if maps[n][k].qty is not None], lambda a, b: near(a.qty, b.qty, 1e-6, 1e-6),
               lambda a, b: f"Menge {a.qty:g} ≠ {b.qty:g}", lambda a, b: f"quantity {a.qty:g} ≠ {b.qty:g}",
               lambda a, b: abs((a.qty or 0) - (b.qty or 0)) * (a.up or b.up or 0))
        unit_eq = lambda a, b: a.unit.lower().rstrip(".") == b.unit.lower().rstrip(".") or \
            {a.unit.lower(), b.unit.lower()} in ({"m3", "m³"}, {"m2", "m²"})
        report([n for n in present if maps[n][k].unit], unit_eq,
               lambda a, b: f"Einheit {a.unit} ≠ {b.unit}", lambda a, b: f"unit {a.unit} ≠ {b.unit}", lambda a, b: 0.0)
        texted = [n for n in present if _texted(boqs[n]) >= 0.5 * len(boqs[n].items) and maps[n][k].short_text.strip()]
        t40 = lambda it: re.sub(r"\W+", "", it.short_text.lower())[:40]
        report(texted, lambda a, b: t40(a) == t40(b),
               lambda a, b: f"Kurztext „{a.short_text[:40]}“ ≠ „{b.short_text[:40]}“",
               lambda a, b: f"short text '{a.short_text[:40]}' ≠ '{b.short_text[:40]}'", lambda a, b: 0.0)
        priced = [n for n in present if maps[n][k].up is not None]     # an unpriced tender has no price to compare
        report(priced, lambda a, b: near(a.up, b.up) and near(a.it, b.it),
               lambda a, b: f"EP {a.up:,.2f} ≠ {b.up:,.2f} €" if not near(a.up, b.up) else f"GP {a.it:,.2f} ≠ {b.it:,.2f} €",
               lambda a, b: f"unit price €{a.up:,.2f} ≠ €{b.up:,.2f}" if not near(a.up, b.up) else f"total €{a.it:,.2f} ≠ €{b.it:,.2f}",
               lambda a, b: abs((a.up or 0) - (b.up or 0)) * (a.qty or b.qty or 0) if not near(a.up, b.up)
               else abs((a.it or 0) - (b.it or 0)))
        for (a_n, b_n), (dd, de_en, e) in pairs.items():
            out.append(Flag("X02", "Fassungen weichen ab", "high",
                            f"Pos. {oz}: {a_n} vs. {b_n}: " + "; ".join(dd) + ".",
                            oz=oz, reference="Abgleich der Fassungen", exposure_eur=e,
                            suggestion="Prüfen, welche Fassung gilt (Tippfehler oder nachträgliche Änderung).",
                            en=dict(title="Versions differ",
                                    message=f"Item {oz}: {a_n} vs. {b_n}: " + "; ".join(de_en) + ".",
                                    suggestion="Check which version applies (typo or later change).")))
    for f in out:
        f.category = "error"
    return out



# ---------------------------------------------------------------- project notes (what only shows across files)

def _scope_after(merged: BoQ, ref: str) -> str:
    """'Hinweis nach Pos. 2.1.480' -> the section the note stands in front of (e.g. '2.2'); '' = whole BoQ."""
    m = re.search(r"Pos\. ([\d.]+)", ref)
    if not m:
        return ""
    keys = [_key(i.oz) for i in merged.items]
    k = _key(m.group(1))
    if k not in keys:
        return ""
    nxt = merged.items[min(keys.index(k) + 1, len(keys) - 1)]
    return ".".join(nxt.oz.split(".")[:-1]) or nxt.oz


def project_notes(boqs: dict[str, BoQ], names: list[str], merged: BoQ, merged_flags: list[Flag],
                  diffs: list[Flag]) -> list[dict]:
    """Concrete observations that need more than one file. Every note names the files and item numbers it rests on;
    nothing is inferred beyond what the documents show."""
    notes: list[dict] = []
    fmt = lambda v: f"{v:,.2f}"

    def add(sev, de, en, items=(), eur=0.0, kind=""):
        notes.append({"kind": kind, "severity": sev, "de": de, "en": en, "items": list(items)[:40], "eur": round(eur, 2)})

    # 1 · same project, recognised on content
    sims = [similarity(boqs[a], boqs[b], detail=True) for i, a in enumerate(names) for b in names[i + 1:]]
    s = min(sims, key=lambda d: d["score"])
    add("info", f"Dieselbe Maßnahme in {len(names)} Dateien erkannt ({', '.join(names)}) – am Inhalt, nicht am Dateinamen: "
                f"{s['items']:.0%} gleiche Positionsnummern, {s['quantities']:.0%} gleiche Mengen"
                + (f", {s['texts']:.0%} gleiche Kurztexte." if s["texts"] is not None else "."),
        f"Same project found in {len(names)} files ({', '.join(names)}) – by content, not file name: "
        f"{s['items']:.0%} same item numbers, {s['quantities']:.0%} same quantities"
        + (f", {s['texts']:.0%} same short texts." if s["texts"] is not None else "."), kind="match")

    # 1b · extracts (trade packages) of the full BoQ
    keys = {n: {_key(i.oz) for i in boqs[n].items} for n in names}
    full = max(names, key=lambda n: len(keys[n]))
    for n in names:
        if n != full and len(keys[n]) < 0.5 * len(keys[full]) and keys[n] <= keys[full] | keys[n]:
            inside = len(keys[n] & keys[full])
            add("info", f"{n} ist ein Auszug aus {full}: {inside} von {len(keys[n])} Positionen sind dort enthalten "
                        f"({len(keys[full])} Positionen gesamt). Fehlende Positionen im Auszug sind daher kein Befund.",
                f"{n} is an extract of {full}: {inside} of its {len(keys[n])} items are contained there "
                f"({len(keys[full])} items in total). Items absent from the extract are therefore not a finding.",
                kind="excerpt")

    # 2 · items deleted / added between versions
    miss = [f for f in diffs if f.rule_id == "X01"]
    if miss:
        by_file: dict[str, list[Flag]] = {}
        for f in miss:
            m = re.search(r"fehlt aber in (.+?) –", f.message)
            by_file.setdefault(m.group(1) if m else "?", []).append(f)
        for fname, fl in by_file.items():
            tot = sum(f.exposure_eur for f in fl)
            ozs = [f.oz for f in fl]
            add("high", f"{len(fl)} Positionen fehlen in {fname} gegenüber den anderen Fassungen ({fmt(tot)} €): "
                        f"{', '.join(ozs[:12])}{' …' if len(ozs) > 12 else ''}. Wer nach dieser Datei kalkuliert oder "
                        "beauftragt, lässt diese Leistungen weg – sie kämen später als Nachtrag.",
                f"{len(fl)} items are missing in {fname} compared with the other versions (€{fmt(tot)}): "
                f"{', '.join(ozs[:12])}{' …' if len(ozs) > 12 else ''}. Anyone pricing or ordering from this file leaves "
                "this work out – it would come back as a change order.", ozs, tot, "missing")

    # 3 · changed prices / quantities / texts
    chg = [f for f in diffs if f.rule_id == "X02"]
    if chg:
        money = [f for f in chg if re.search(r"Menge|EP|GP", f.message)]
        texts = [f for f in chg if "Kurztext" in f.message and f not in money]
        if money:
            tot = sum(f.exposure_eur for f in money)
            add("high", f"{len(money)} Positionen haben in den Fassungen unterschiedliche Mengen/Preise (Wirkung bis {fmt(tot)} €): "
                        + "; ".join(f.message.split(": ", 2)[-1].rstrip(".") + f" ({f.oz})" for f in money[:6])
                        + ". Vor Abgabe klären, welche Zahl gilt.",
                f"{len(money)} items have different quantities/prices in the versions (effect up to €{fmt(tot)}): "
                + "; ".join(f.en.get("message", "").split(": ", 2)[-1].rstrip(".") + f" ({f.oz})" for f in money[:6])
                + ". Clarify which figure applies before submitting.", [f.oz for f in money], tot, "changed")
        if texts:
            add("medium", f"{len(texts)} Positionen haben in den Fassungen unterschiedliche Kurztexte: "
                          f"{', '.join(f.oz for f in texts[:15])}. Gekürzte oder geänderte Texte verändern, was geschuldet ist.",
                f"{len(texts)} items have different short texts in the versions: {', '.join(f.oz for f in texts[:15])}. "
                "Shortened or changed texts change what is owed.", [f.oz for f in texts], 0.0, "text")

    # 4 · a clause that only one file contains, and the prices it affects in another file
    priced_low = {f.oz: f for f in merged_flags if f.rule_id in ("R25", "R05") and f.oz}
    clause_only: dict[tuple, list] = {}
    text_sig = lambda t: re.sub(r"\W+", "", t.lower())[:200]
    for f in merged_flags:
        if f.rule_id != "R20" or f.oz:
            continue
        mref = re.search(r"Vorbemerkung (.+?): ", f.message)
        ref = mref.group(1) if mref else ""
        note = next((n for n in merged.notes if n["ref"] == ref), None)
        if note is None:
            continue
        holders = [n for n in names if any(text_sig(x["text"]) == text_sig(note["text"]) for x in boqs[n].notes)]
        if not holders or len(holders) == len(names):
            continue                                  # clause visible in every file: nothing cross-file about it
        others = [n for n in names if n not in holders]
        scope = _scope_after(merged, ref)
        hit = [o for o in priced_low if not scope or o == scope or o.startswith(scope + ".")]
        snippet = re.search(r"„(.+?)“", f.message)
        snip = (snippet.group(1) if snippet else "")[:140]
        t_de, t_en = f.title.replace("Vertragsrisiko: ", ""), f.en.get("title", "").replace("Contract risk: ", "")
        where_de = f"vor Abschnitt {scope}" if scope else "für das gesamte LV"
        where_en = f"before section {scope}" if scope else "for the whole BoQ"
        base_de = (f"Klausel nur in {', '.join(holders)} ({where_de}), nicht in {', '.join(others)}: „{snip}“ – {t_de}.")
        base_en = (f"Clause only in {', '.join(holders)} ({where_en}), not in {', '.join(others)}: '{snip}' – {t_en}.")
        if hit:
            ex = ", ".join(f"{o} ({priced_low[o].message.split('–')[0].strip()[:40]})" for o in hit[:5])
            add("high", base_de + f" Gleichzeitig sind {len(hit)} betroffene Positionen auffällig niedrig bepreist: {ex}. "
                                  "Was laut Klausel einzurechnen ist, steckt in diesen Preisen offensichtlich nicht.",
                base_en + f" At the same time {len(hit)} affected items are priced suspiciously low: {ex}. What the clause "
                          "says must be included is evidently not in these prices.", hit, 0.0, "clause_price")
        else:
            clause_only.setdefault((tuple(holders), tuple(others)), []).append((f.severity, where_de, where_en, snip, t_de, t_en))

    for (holders, others), cl in clause_only.items():
        sev = "high" if any(c[0] == "high" for c in cl) else "medium"
        add(sev, f"{len(cl)} Vertragsklausel(n) stehen nur in {', '.join(holders)}, nicht in {', '.join(others)} – wer nur "
                 f"diese Datei(en) liest, übersieht sie: " + " | ".join(f"{c[4]} ({c[1]}): „{c[3][:90]}“" for c in cl[:6]),
            f"{len(cl)} contract clause(s) appear only in {', '.join(holders)}, not in {', '.join(others)} – anyone reading only "
            f"those file(s) misses them: " + " | ".join(f"{c[5]} ({c[2]}): '{c[3][:90]}'" for c in cl[:6]),
            [], 0.0, "clause_only")

    # 5 · a printed total in one file that matches another file, not its own items
    for n in names:
        b = boqs[n]
        t = b.totals or {}
        net = t.get("net") or ((t["vat"] / t["vat_rate"]) if t.get("vat") and t.get("vat_rate") else None) or \
            ((t["gross"] / (1 + (t.get("vat_rate") or 0.19))) if t.get("gross") else None)
        own = sum(i.total for i in b.items)
        if not net or abs(net - own) <= max(1.0, 0.0005 * net):
            continue
        twin = next((o for o in names if o != n and abs(sum(i.total for i in boqs[o].items) - net) <= max(1.0, 0.0005 * net)), None)
        if twin:
            add("high", f"Die Summe auf {n} ({fmt(net)} € netto) entspricht genau den Positionen von {twin}, nicht den eigenen "
                        f"Positionen ({fmt(own)} €). In {n} wurden also nach der Summenbildung Positionen geändert oder entfernt "
                        f"(Differenz {fmt(net - own)} €).",
                f"The total printed on {n} (€{fmt(net)} net) equals the items of {twin}, not its own items (€{fmt(own)}). "
                f"So items in {n} were changed or removed after the total was calculated (difference €{fmt(net - own)}).",
                [], abs(net - own), "total_twin")
    return notes
