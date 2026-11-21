"""Layout-invariance test: re-typeset a BoQ in very different layouts and check that OpenBoQ reads the same
items and raises the same findings.

    python tools/layout_test.py "Angebot AN24-0305-2 errors .pdf" --out layout_out

Writes DOCX variants (table, reordered columns, free text, English number format, one sentence per item) and,
if LibreOffice is installed (soffice), converts each to PDF. Then reads every file and compares with the original.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openboq.gaeb_parser import load_boq  # noqa: E402
from openboq.pipeline import analyze  # noqa: E402

deu = lambda v, nd=2: "" if v is None else f"{v:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
eng = lambda v, nd=2: "" if v is None else f"{v:,.{nd}f}"  # noqa: E731


def write_variants(boq, out: Path) -> list[Path]:
    from docx import Document
    from docx.shared import Pt
    out.mkdir(parents=True, exist_ok=True)
    t = boq.totals or {}
    notes = [n["text"] for n in boq.notes if n["ref"].startswith("Hinweis")]
    paths = []
    layouts = {
        "table": (["Pos.", "Beschreibung", "Menge", "Einheit", "EP €", "GP €"], deu,
                  lambda i, f: [i.oz, i.short_text + ("\n" + i.long_text if i.long_text else ""), f(i.qty, 3), i.unit, f(i.up), f(i.it)]),
        "reordered": (["OZ", "Menge", "ME", "Leistung", "Einheitspreis", "Gesamtpreis"], deu,
                      lambda i, f: [i.oz, f(i.qty, 3), i.unit, i.short_text, f(i.up) + " €", f(i.it) + " €"]),
        "english": (["Item", "Description", "Qty", "Unit", "Rate", "Amount"], eng,
                    lambda i, f: [i.oz, i.short_text, f(i.qty, 2), i.unit, f(i.up), f(i.it)]),
        "freetext": (None, deu, None),
        "sentences": (None, deu, None),
    }
    for name, (hdr, f, row) in layouts.items():
        d = Document()
        d.styles["Normal"].font.size = Pt(9)
        d.add_heading(boq.name or "BoQ", 1)
        if hdr:
            tbl = d.add_table(rows=1, cols=len(hdr))
            tbl.style = "Table Grid"
            for c, h in zip(tbl.rows[0].cells, hdr):
                c.text = h
            for i in boq.items:
                for c, v in zip(tbl.add_row().cells, row(i, f)):
                    c.text = v
        else:
            for i in boq.items:
                if name == "freetext":
                    d.add_paragraph(f"Pos. {i.oz}   {i.short_text}")
                    if i.long_text:
                        d.add_paragraph(i.long_text)
                    d.add_paragraph(f"Menge: {f(i.qty, 3)} {i.unit}     EP: {f(i.up)} €     GP: {f(i.it)} €")
                else:
                    d.add_paragraph(f"{i.oz} – {i.short_text}: {f(i.qty, 3)} {i.unit} à {f(i.up)} €/{i.unit} = {f(i.it)} €")
        for n in notes:
            d.add_paragraph(n.replace("Hinweistext ", "Hinweis: "))
        for oz, v in (t.get("sections") or {}).items():
            if "." not in oz:
                d.add_paragraph(("Subtotal section " if f is eng else "Summe Bereich ") + f"{oz}. {f(v)}")
        if t.get("vat"):
            d.add_paragraph((f"plus VAT 19 % {f(t['vat'])}" if f is eng else f"zzgl. Mehrwertsteuer 19,00 % {f(t['vat'])} €"))
        if t.get("gross"):
            d.add_paragraph((f"Grand total {f(t['gross'])}" if f is eng else f"Gesamtsumme: {f(t['gross'])} €"))
        p = out / f"{name}.docx"
        d.save(p)
        paths.append(p)
        if shutil.which("soffice"):
            subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(out), str(p)],
                           capture_output=True, timeout=300)
            if (out / f"{name}.pdf").exists():
                paths.append(out / f"{name}.pdf")
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--out", default="out/layout_test")
    a = ap.parse_args()
    ref = load_boq(a.file)
    ref_res = analyze(ref, prices=None, feedback=None, rules=None)
    ref_items = {i.oz: (i.qty, i.up, i.it) for i in ref.items}
    ref_flags = {(f.rule_id, f.oz) for f in ref_res.counted}
    print(f"original: {len(ref.items)} items, {len(ref_flags)} findings ({ref.parse_info.get('reader')})")
    for p in write_variants(ref, Path(a.out)):
        b = load_boq(p)
        r = analyze(b, prices=None, feedback=None, rules=None)
        got = {i.oz: (i.qty, i.up, i.it) for i in b.items}
        same = sum(1 for oz, v in ref_items.items() if got.get(oz) == v)
        flags = {(f.rule_id, f.oz) for f in r.counted}
        print(f"{p.name:18} items {same:4}/{len(ref_items)} identical · findings {len(flags & ref_flags)}/{len(ref_flags)} same, "
              f"{len(flags - ref_flags)} extra · {b.parse_info.get('reader')}")


if __name__ == "__main__":
    main()
