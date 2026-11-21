"""Simulated test set for milestones 4/5 with a known answer key.

    python tools/make_history_test.py <folder>
    python tools/score_synthetic.py <folder>

history.csv: 5 finished projects. Four kinds of work carry a planted pattern, the rest behave normally:
  excavation      billed quantity +30 %            -> hist_qty_over      (R32)
  gravel backfill billed quantity −30 %            -> hist_qty_under     (R32)
  soil disposal   change orders in 4 of 5 projects -> hist_change_orders (R33)
  waterproofing   unit cost +25 % over calculation -> hist_cost_overrun  (R34)
Past projects word the items differently from the new BoQ, so matching has to work on similar texts, not copies.

H1 (new BoQ with all four kinds + normal work), H2 (normal work only – any history finding is a false alarm),
Q1 (quantities that do not fit together), Q0 (consistent quantities), W1/W2 (escalation clause yes/no + alternatives).
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

NORMAL = [  # (text variants in past projects, unit, unit price)
    (["Kalksandstein-Mauerwerk 17,5 cm, KS 12-1,8, Normalmörtel", "Mauerwerk KS 17,5 cm herstellen, MG IIa"], "m2", 62),
    (["Wandschalung glatt, beidseitig, h bis 3 m", "Schalung Stahlbetonwand, Systemschalung, beidseitig"], "m2", 38),
    (["Betonstahl B500B liefern, schneiden, biegen, verlegen", "Bewehrung B500B Stabstahl und Matten verlegen"], "t", 1480),
    (["Stahlbetonwand C30/37 XC4 XF1, d = 25 cm", "Ortbeton Wand C30/37, XC4, XF1, Dicke 25 cm"], "m3", 245),
    (["Frostschutzschicht 0/45, d = 30 cm, Ev2 >= 120", "Frostschutzschicht aus Schotter 0/45, 30 cm"], "m2", 11),
    (["Asphaltdeckschicht AC 11 D S, d = 4 cm", "Deckschicht Asphaltbeton AC 11 D S, 4 cm"], "m2", 17),
]
PATTERNS = {   # kind -> (variants, unit, price, qty factor, change-order probability, unit-cost factor, reason)
    "exc": (["Baugrubenaushub Homogenbereich B, bis 3 m Tiefe, seitlich lagern",
             "Aushub Baugrube Homogenbereich B, Tiefe bis 3 m, Lagerung auf Baustelle"], "m3", 21, 1.30, 0.1, 1.0, ""),
    "backfill": (["Arbeitsraumverfüllung mit Kies 0/32, lagenweise verdichten",
                  "Verfüllung Arbeitsraum Kies 0/32, lagenweise verdichtet"], "m3", 34, 0.70, 0.1, 1.0, ""),
    "disposal": (["Boden Homogenbereich B laden, abfahren und entsorgen, Z 1.1",
                  "Aushubboden laden, abtransportieren und entsorgen, Z 1.1"], "t", 19, 1.0, 0.8, 1.0,
                 "belastetes Material Z2 angetroffen"),
    "waterproof": (["Abdichtung Bodenplatte mit Bitumenbahnen nach DIN 18533, W2.1-E",
                    "Bodenplattenabdichtung Bitumen-Schweißbahn DIN 18533 W2.1-E"], "m2", 48, 1.0, 0.1, 1.25, ""),
}


def history(folder: Path, rnd: random.Random):
    rows = []
    for p in range(1, 6):
        proj = f"SIM-Projekt {p}"
        for variants, unit, up in NORMAL:
            qp = rnd.choice([80, 150, 300, 600])
            qa = qp * rnd.gauss(1.0, 0.03)
            rows.append([proj, variants[p % 2], unit, qp, qa, up, qp * up * 0.88, qa * up * 0.88 * rnd.gauss(1.0, 0.02), "", "", ""])
        for kind, (variants, unit, up, qf, pco, cf, reason) in PATTERNS.items():
            qp = rnd.choice([200, 400, 800])
            qa = qp * rnd.gauss(qf, 0.03)
            co = (p <= 4) if kind == "disposal" else rnd.random() < pco
            rows.append([proj, variants[p % 2], unit, qp, qa, up, qp * up * 0.88, qa * up * 0.88 * rnd.gauss(cf, 0.02),
                         "ja" if co else "nein", round(qp * up * 0.2, 2) if co else "", reason if co else ""])
    with open(folder / "history.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["Projekt", "Kurztext", "Einheit", "Menge_LV", "Menge_Ist", "EP", "Kosten_Soll", "Kosten_Ist",
                    "Nachtrag", "Nachtrag_EUR", "Nachtrag_Grund"])
        for r in rows:
            w.writerow([r[0], r[1], r[2]] + [f"{v:.2f}".replace(".", ",") if isinstance(v, float) else v for v in r[3:]])


def boq_csv(path: Path, items: list[tuple]):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["OZ", "Kurztext", "Langtext", "Menge", "Einheit", "EP", "GP"])
        for oz, st, lt, q, u, up in items:
            w.writerow([oz, st, lt, f"{q:.2f}".replace(".", ","), u, f"{up:.2f}".replace(".", ","),
                        f"{q * up:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")])


def main():
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "histtest")
    folder.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(11)
    history(folder, rnd)
    LT = "Ausführung nach Plan und den einschlägigen Normen."
    normal = [("1.1.10", "Mauerwerk aus Kalksandstein 17,5 cm, KS 12-1,8, Normalmörtel MG IIa", LT, 420, "m2", 64),
              ("1.1.20", "Schalung Stahlbetonwand glatt, beidseitig, bis 3 m Höhe", LT, 640, "m2", 39),
              ("1.1.30", "Betonstahl B500B als Stabstahl und Matten liefern und verlegen", LT, 14, "t", 1495),
              ("1.1.40", "Stahlbetonwand aus Ortbeton C30/37 XC4 XF1, Dicke 25 cm", LT, 118, "m3", 248)]
    planted = [("2.1.10", "Baugrubenaushub Homogenbereich B bis 3 m Tiefe, Boden seitlich lagern", LT, 900, "m3", 22),
               ("2.1.20", "Verfüllung der Arbeitsräume mit Kies 0/32, lagenweise verdichten", LT, 310, "m3", 35),
               ("2.1.30", "Boden Homogenbereich B laden, abfahren, entsorgen, Z 1.1", LT, 950, "t", 20),
               ("2.1.40", "Abdichtung der Bodenplatte mit Bitumenbahnen, DIN 18533, W2.1-E", LT, 520, "m2", 49)]
    boq_csv(folder / "H1_neubau_historie.csv", normal + planted)
    boq_csv(folder / "H2_nur_normal.csv", normal + [("3.1.10", "Frostschutzschicht aus Schotter 0/45, Dicke 30 cm", LT, 800, "m2", 11.5),
                                                      ("3.1.20", "Asphaltdeckschicht AC 11 D S, Dicke 4 cm", LT, 780, "m2", 17.5)])
    # quantities that do not fit together (no model needed) – and a consistent twin
    q_bad = [("1.1.10", "Stahlbetonwand aus Ortbeton C30/37 XC4 XF1, Dicke 25 cm", LT, 300, "m3", 248),
             ("1.1.20", "Betonstahl B500B als Stabstahl und Matten liefern und verlegen", LT, 3.0, "t", 1495),
             ("2.1.10", "Baugrubenaushub Homogenbereich B bis 3 m Tiefe, Boden seitlich lagern", LT, 600, "m3", 22),
             ("2.1.20", "Boden Homogenbereich B laden, abfahren, entsorgen, Z 1.1", LT, 2400, "t", 20),
             ("3.1.10", "Frostschutzschicht aus Schotter 0/45, Dicke 30 cm", LT, 800, "m2", 11.5),
             ("3.1.20", "Asphaltdeckschicht AC 11 D S, Dicke 4 cm", LT, 1150, "m2", 17.5),
             ("4.1.10", "Oberboden abtragen, Dicke 30 cm, seitlich lagern", LT, 500, "m2", 4.5),
             ("4.1.20", "Oberboden andecken, Dicke 30 cm", LT, 950, "m2", 5.5)]
    q_ok = [list(r) for r in q_bad]
    q_ok[1][3], q_ok[3][3], q_ok[5][3], q_ok[7][3] = 33.0, 1100, 790, 480
    boq_csv(folder / "Q1_mengen_falsch.csv", q_bad)
    boq_csv(folder / "Q0_mengen_stimmig.csv", [tuple(r) for r in q_ok])
    # contract context + alternatives
    w_items = [("1.1.10", "Stahlbetonwand aus Ortbeton C30/37 XC4 XF1, Dicke 25 cm", LT, 118, "m3", 248),
               ("1.1.20", "PE-HD Druckrohr DN 150 SDR 11 liefern und verlegen", LT, 420, "m", 58),
               ("1.1.30", "Mauerwerk aus Kalksandstein 17,5 cm, KS 12-1,8, Normalmörtel MG IIa", LT, 300, "m2", 64)]
    for name, note in (("W1_gleitklausel.txt", "Für Betonstahl und Kunststoffrohre gilt die Stoffpreisgleitklausel nach Formblatt 225."),
                       ("W2_festpreis.txt", "Die Einheitspreise sind Festpreise bis Bauende, ohne Preisgleitung.")):
        lines = ["Leistungsverzeichnis", "", "Vorbemerkungen", note, ""]
        for oz, st, lt, q, u, up in w_items:
            g = lambda v, nd: f"{v:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")
            lines.append(f"{oz} – {st}: {g(q, 3)} {u} à {g(up, 2)} €/{u} = {g(q * up, 2)} €")
        (folder / name).write_text("\n".join(lines), encoding="utf-8")
    all_items = lambda its: [i[0] for i in its]
    key = {"history": "history.csv", "files": [
        {"file": "H1_neubau_historie.csv", "group": "", "clean_items": all_items(normal), "planted": [
            {"type": "hist_qty_over", "item": "2.1.10", "note": "excavation billed +30 % in past projects"},
            {"type": "hist_qty_under", "item": "2.1.20", "note": "backfill billed −30 %"},
            {"type": "hist_change_orders", "item": "2.1.30", "note": "disposal: change orders in 4 of 5 projects"},
            {"type": "hist_cost_overrun", "item": "2.1.40", "note": "waterproofing unit cost +25 %"}]},
        {"file": "H2_nur_normal.csv", "group": "", "clean_items": ["1.1.10", "1.1.20", "1.1.30", "1.1.40", "3.1.10", "3.1.20"],
         "planted": []},
        {"file": "Q1_mengen_falsch.csv", "group": "", "clean_items": [], "planted": [
            {"type": "rebar_ratio", "item": "", "note": "3 t rebar on 300 m3 concrete = 10 kg/m3"},
            {"type": "disposal_vs_excavation", "item": "", "note": "2,400 t disposal vs 600 m3 excavation"},
            {"type": "layer_mismatch", "item": "", "note": "asphalt 1,150 m2 on 800 m2 frost layer"},
            {"type": "topsoil_balance", "item": "", "note": "950 m2 spread vs 500 m2 stripped, no supply item"}]},
        # excavation / disposal (2.1.x) match the history patterns, so their history findings are correct – not "clean"
        {"file": "Q0_mengen_stimmig.csv", "group": "", "clean_items": [i[0] for i in q_bad if not i[0].startswith("2.")],
         "planted": []},
        {"file": "W1_gleitklausel.txt", "group": "", "planted": [], "clean_items": [], "expect_escalation": True,
         "expect_alternatives": ["1.1.10", "1.1.20"]},
        {"file": "W2_festpreis.txt", "group": "", "planted": [], "clean_items": [], "expect_escalation": False,
         "expect_alternatives": ["1.1.10"]},
    ]}
    (folder / "expected.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written to {folder}")


if __name__ == "__main__":
    main()
