"""Score OpenBoQ on synthetic test files made by another AI.

    python tools/score_synthetic.py <folder>            # rules only
    python tools/score_synthetic.py <folder> --llm      # with the AI layer (uses your provider keys)

The folder holds the generated BoQ files plus expected.json (the answer key):

{
  "files": [
    {"file": "A1_bid.csv", "group": "A",
     "planted": [{"type": "calc_error", "item": "2.1.30", "note": "50 x 4.00 printed as 20.00"}, ...],
     "clean_items": ["1.1.10", "1.1.20"]},
    ...
  ]
}

Optional, for milestones 4/5: a top-level "history": "history.csv" (past projects: planned vs actual quantity/cost,
change orders) is used for every file; per file "expect_escalation": true/false (price escalation clause present?)
and "expect_alternatives": ["4.1.20", ...] (items where a spec alternative should be offered).

"item" is "" for BoQ-wide errors (clauses, totals). Files with the same "group" are versions of one project
(cross-file checks). "clean_items" are items with no error – any finding there counts as a false alarm.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openboq import crossfile as X  # noqa: E402
from openboq.gaeb_parser import load_boq  # noqa: E402
from openboq.pipeline import analyze  # noqa: E402

# planted error type -> finding rules that count as "caught"
TYPE_RULES = {
    "calc_error": {"R01"}, "wrong_unit": {"R02", "R22"}, "unknown_unit": {"R22"}, "fractional_count": {"R22"},
    "dot_decimal": {"R22"}, "lump_sum_qty": {"R22", "R03"}, "cent_price": {"R25", "R05", "R31"}, "price_outlier": {"R05", "R24", "R25", "R31"},
    "duplicate_item": {"R04"}, "duplicate_oz": {"R12"}, "missing_text": {"R27"}, "truncated_text": {"R27"},
    "vague_text": {"R08", "AI"}, "missing_parameters": {"R09", "AI"}, "outdated_norm": {"R11"},
    "missing_companion": {"R10"}, "lump_sum_hiding": {"R03"}, "unreadable_number": {"R21"}, "currency": {"R23"},
    "totals_mismatch": {"R26", "X01"}, "deleted_items": {"R26", "X01"}, "changed_price": {"X02", "R01"},
    "changed_quantity": {"X02"}, "changed_text": {"X02"}, "inserted_clause": {"R20"},
    "penalty_clause": {"R20"}, "risk_shift": {"R20"}, "no_claims": {"R20"}, "price_lock": {"R20"},
    "work_not_paid": {"R20"}, "ground_risk": {"R20"}, "one_sided_order": {"R20"}, "liability": {"R20"},
    "prompt_injection": {"S01"}, "invisible_chars": {"S02"},
    # addendum types – some are not checked by rules yet (only the AI may catch them): they show up honestly as misses
    "text_typo": {"R29", "AI"}, "text_contradiction": {"R28", "AI"}, "oz_typo": {"R30", "R21", "R12"}, "oz_gap": {"R30"},
    "oz_order": {"R30"},
    "vat_rate": {"R26"}, "gross_mismatch": {"R26"}, "section_total": {"R26"}, "provisional_in_total": {"R26"},
    # milestone 4 (need a history file) and quantity relations (no model needed)
    "hist_qty_over": {"R32"}, "hist_qty_under": {"R32"}, "hist_change_orders": {"R33"}, "hist_cost_overrun": {"R34"},
    "qty_relation": {"R35"}, "rebar_ratio": {"R35"}, "disposal_vs_excavation": {"R35"}, "layer_mismatch": {"R35"},
    "topsoil_balance": {"R35"},
}


LV_TYPES = {"penalty_clause", "risk_shift", "no_claims", "price_lock", "work_not_paid", "ground_risk", "one_sided_order",
            "liability", "inserted_clause", "prompt_injection", "totals_mismatch", "deleted_items", "vat_rate",
            "gross_mismatch", "price_lock", "qty_relation", "rebar_ratio", "disposal_vs_excavation", "layer_mismatch", "topsoil_balance"}


ALIASES = [  # other generators invent their own type names – map them by keywords (first match wins)
    (("injection",), "prompt_injection"), (("invisible", "zero_width"), "invisible_chars"),
    (("typo", "spelling", "rechtschreib", "tippfehler"), "text_typo"), (("contradict", "widerspruch"), "text_contradiction"),
    (("companion", "begleit", "missing_work", "fehlende_leistung"), "missing_companion"),
    (("penalty", "strafe"), "penalty_clause"), (("escalation", "price_lock", "festpreis", "gleit"), "price_lock"),
    (("claim", "ground", "baugrund", "risk_shift", "liability", "haftung", "clause", "one_sided", "anordnung"), "risk_shift"),
    (("rebar", "bewehrung"), "rebar_ratio"), (("disposal", "entsorg"), "disposal_vs_excavation"),
    (("layer",), "layer_mismatch"), (("topsoil", "oberboden"), "topsoil_balance"),
    (("quantity_mismatch", "qty_mismatch", "mengen", "quantity_relation"), "qty_relation"),
    (("hist",), "hist_change_orders"), (("outlier", "überhöht", "too_high"), "price_outlier"),
    (("cent", "too_low"), "cent_price"), (("calc", "rechen", "arith"), "calc_error"), (("unit", "einheit"), "wrong_unit"),
    (("fraction",), "fractional_count"), (("total", "summe"), "totals_mismatch"), (("oz_", "ordnungszahl"), "oz_typo"),
    (("duplicate", "doppelt"), "duplicate_item"), (("currency", "währung"), "currency"), (("vague", "unklar"), "vague_text"),
    (("unreadable", "unlesbar"), "unreadable_number"), (("truncat", "abgeschnitten"), "truncated_text"),
    (("changed_price",), "changed_price"), (("changed_q",), "changed_quantity"), (("changed_text",), "changed_text"),
    (("delet", "missing_item"), "deleted_items"), (("param", "pflichtangabe"), "missing_parameters"),
]


def canon(t: str) -> str:
    if t in TYPE_RULES:
        return t
    low = t.lower()
    for words, target in ALIASES:
        if any(w in low for w in words):
            return target
    return t


def caught(p, flags):
    p = {**p, "type": canon(p["type"])}
    rules = TYPE_RULES.get(p["type"], set())
    if p["type"] == "hist_change_orders":
        rules = {"R32", "R33", "R34"}
    item = (p.get("item") or "").strip(".")
    if p["type"] in LV_TYPES:
        item = ""                                   # clauses live in notes; any matching finding counts
    for f in flags:
        rid = "AI" if f.source == "llm" else f.rule_id
        if rid not in rules and not (f.source == "llm" and "AI" in rules):
            continue
        if not item or f.oz == item or (f.oz and item.startswith(f.oz + ".")) or (not f.oz and p["type"] in
                                                                                  ("totals_mismatch", "deleted_items")):
            return f
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--only", default="", help="comma-separated name parts, e.g. E1,E2,K1,T1 (others are skipped)")
    a = ap.parse_args()
    folder = Path(a.folder)
    key = json.loads((folder / "expected.json").read_text(encoding="utf-8"))
    if a.only:
        parts = [x.strip().lower() for x in a.only.split(",") if x.strip()]
        key["files"] = [e for e in key["files"] if any(pt in e["file"].lower() for pt in parts)]
    import time
    boqs, results, errors = {}, {}, {}
    for e in key["files"]:
        if not (folder / e["file"]).exists():
            errors[e["file"]] = "file not found"
            continue
        try:
            boqs[e["file"]] = load_boq(folder / e["file"])
        except Exception as ex:
            errors[e["file"]] = f"{type(ex).__name__}: {ex}"
    expect_err = {e["file"] for e in key["files"] if e.get("expect_error")}
    hist = None
    if key.get("history"):
        from openboq.history import HistoryModel
        hist = HistoryModel.load(folder / key["history"])
        print(f"History: {key['history']} – {len(hist.rows)} items from {len(hist.projects)} projects" if hist else
              f"History file {key['history']} not found")
    for k, (n, b) in enumerate(boqs.items(), 1):
        t0 = time.time()
        llm = a.llm and n not in expect_err and len(b.items) <= 400       # no AI for broken files / the 2,000-item file
        print(f"[{k}/{len(boqs)}] {n} ({len(b.items)} items{', AI' if llm else ''}) …", end=" ", flush=True)
        results[n] = analyze(b, use_llm=llm, lang=a.lang, prices=None, feedback=None, rules=None, history=hist).flags
        print(f"{time.time() - t0:.0f} s", flush=True)
    print()
    groups = defaultdict(list)
    for e in key["files"]:
        if e.get("group") and e["file"] in boqs:
            groups[e["group"]].append(e["file"])
    found_groups = X.group_projects({n: boqs[n] for n in boqs})
    for g, names in groups.items():
        if len(names) > 1:
            diffs = X.compare(boqs, names)
            for n in names:                               # a difference counts for the file whose content deviates
                import re as _re
                mine = []
                for f in diffs:
                    m = f.en.get("message", "")
                    if f.rule_id == "X01":              # "… is in A but missing in B" -> counts for B
                        miss = _re.search(r"missing in (.+?) –", m)
                        if miss and n in miss.group(1):
                            mine.append(f)
                    else:                     # "Item X: A, B vs. C: …" – which side changed cannot be told from content
                        seg = m.split(": ")[1] if m.count(": ") >= 2 else ""
                        if " vs. " in seg and n in [x.strip() for x in _re.split(r", | vs\. ", seg)]:
                            mine.append(f)
                results[n] = results[n] + mine

    tot = hit = fa = 0
    by_type = defaultdict(lambda: [0, 0])
    fa_rules = defaultdict(int)
    print(f"{'file':34} {'read':>5} {'caught':>8} {'false alarms':>13}  missed")
    for e in key["files"]:
        n = e["file"]
        if e.get("expect_error"):                       # broken / non-BoQ file: must not crash, must not invent items
            ok = n in errors or len(boqs[n].items) == 0 or any(
                f.rule_id == "R21" and not f.oz for f in results.get(n, []))   # read, but flagged as broken
            print(f"{n:34} {'OK' if ok else 'NOT OK'}  (expected: unreadable / no items; got "
                  f"{'error: ' + errors[n][:40] if n in errors else str(len(boqs[n].items)) + ' items'})")
            continue
        if n in errors:
            print(f"{n:34} ERROR {errors[n][:60]}")
            tot += len(e.get("planted", []))
            continue
        flags = [f for f in results[n] if f.severity in ("high", "medium")]
        missed = []
        c = 0
        for p in e.get("planted", []):
            ok = caught(p, results[n]) is not None
            by_type[p["type"]][0] += 1
            by_type[p["type"]][1] += ok
            c += ok
            if not ok:
                missed.append(f"{p['type']}@{p.get('item') or 'LV'}")
        clean = set(e.get("clean_items", []))
        # a version difference on an item planted in another file of the same group is that planted change seen from
        # this side – with two files disagreeing, which one "changed" cannot be told from content
        planted_elsewhere = {(p.get("item") or "").strip(".") for o in key["files"]
                             if o.get("group") and o.get("group") == e.get("group") and o["file"] != n
                             for p in o.get("planted", [])}
        false = [f for f in flags if f.oz in clean and not (f.rule_id in ("X01", "X02") and f.oz in planted_elsewhere)]
        for f in false:
            fa_rules[f.rule_id] += 1
        tot += len(e.get("planted", [])); hit += c; fa += len(false)
        print(f"{n:34} {len(boqs[n].items):5} {c:4}/{len(e.get('planted', [])):<3} {len(false):13}  {', '.join(missed)}")
        for f in false[:5]:
            print(f"{'':42}false alarm: {f.oz} {f.rule_id} {f.title}")
    print(f"\nCaught {hit}/{tot} planted errors ({100 * hit / max(1, tot):.0f} %), {fa} false alarms on clean items.")
    if fa_rules:
        print("False alarms by rule: " + ", ".join(f"{r} {n}" for r, n in sorted(fa_rules.items(), key=lambda kv: -kv[1]))
              + ("  (R32–R34 = history findings: correct if the history shows that pattern and the key plants none)"
                 if any(r in fa_rules for r in ("R32", "R33", "R34")) else ""))
    # what-if expectations (milestone 5)
    from openboq import whatif as W
    wi_tot = wi_ok = 0
    wi_lines = []
    for e in key["files"]:
        n = e["file"]
        if n not in boqs:
            continue
        if "expect_escalation" in e:
            got = W.contract_context(boqs[n])["escalation"]
            wi_tot += 1; wi_ok += got == bool(e["expect_escalation"])
            if got != bool(e["expect_escalation"]):
                wi_lines.append(f"  {n}: escalation clause expected {e['expect_escalation']}, found {got}")
        if e.get("expect_alternatives"):
            alts = {a["oz"] for a in W.alternatives(boqs[n])}
            for oz in e["expect_alternatives"]:
                wi_tot += 1; wi_ok += oz.strip(".") in alts
                if oz.strip(".") not in alts:
                    wi_lines.append(f"  {n}: no alternative offered for {oz}")
    if wi_tot:
        print(f"What-if checks: {wi_ok}/{wi_tot} correct")
        print("\n".join(wi_lines))
    print("\nBy error type:")
    for t, (n, k) in sorted(by_type.items()):
        print(f"  {t:22} {k}/{n}")
    exp = sorted(sorted(v) for v in groups.values() if len(v) > 1)
    got = sorted(sorted(g) for g in found_groups)
    print(f"\nProject groups expected: {exp}\nProject groups found:    {got}")


if __name__ == "__main__":
    main()
