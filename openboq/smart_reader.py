"""Pick the best reader for documents with unknown layout (PDF, Word, text).

 1. Specialised AVA-print reader (fast, very accurate on GAEB-style prints) – PDF only.
 2. Layout-independent reader (tables + text blocks, any number format) – PDF, DOCX, TXT.
 3. AI reader (only if 1+2 look weak and an AI provider is configured): the model returns the items as JSON;
    every value it returns must literally appear in the source text, otherwise it is dropped (no invented prices).
Each result gets a quality score (items found, texts, qty × EP = GP, printed totals); the best one wins and the
choice is stored in boq.parse_info so the UI can show how the file was read.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import generic_reader as G
from .model import BoQ


def _good(sc: dict, totals: bool = True) -> bool:
    n = sc["items"]
    if n < 3:
        return False
    text_ok = sc["with_text"] >= 0.8 * n
    arith_ok = sc["priced"] == 0 or sc["arith_ok"] >= 0.85 * sc["priced"]
    return text_ok and arith_ok and (not totals or sc["totals_match"] is not False)


def _weak(sc: dict) -> bool:
    """Bad enough to ask the AI to read the document: almost nothing read, texts missing, or numbers that don't add up
    on most items. A printed total that doesn't match is NOT a reason – that is a finding (deleted/changed items)."""
    n = sc["items"]
    if n < 3:
        return True
    if sc["with_text"] < 0.5 * n:
        return True
    return sc["priced"] > 0 and sc["arith_ok"] < 0.5 * sc["priced"]


def _covers(p: Path, boq: BoQ) -> bool:
    """Did the reader catch (nearly) every line that looks like an item number followed by values?"""
    import re
    from .pdf_parser import _lines_from_texts, _pages_pdfium
    try:
        lines = _lines_from_texts(_pages_pdfium(p), filter_headers=False)
    except Exception:
        return True
    rx = re.compile(r"^(?:pos\.?\s*|oz\s*|item\s*)?(\d{1,4}(?:\.\d{1,5}){1,5})\.?(?:\s|$)", re.I)
    oz = {m.group(1).strip(".") for l in lines if (m := rx.match(l))}
    found = {i.oz for i in boq.items}
    from collections import Counter
    depth = Counter(o.count(".") for o in found).most_common(1)
    d = depth[0][0] if depth else 99
    expected = {o for o in oz if o.count(".") >= d}      # item-level numbers only (headings are shallower)
    return len(expected) < 5 or len(found & expected) >= 0.9 * len(expected)


def read_document(path, use_ai: bool | None = None) -> BoQ:
    p = Path(path)
    suf = p.suffix.lower()
    results: list[tuple[str, BoQ, dict]] = []
    if suf == ".pdf":
        from .pdf_parser import parse_pdf
        try:
            b = parse_pdf(p)
            results.append(("ava-print", b, G.score(b)))
        except Exception:
            pass
        # every item number on the page was read and the numbers add up: done. A total that doesn't match is a
        # finding about the document (deleted/changed items), not a reading problem.
        if results and _good(results[0][2], totals=False) and _covers(p, results[0][1]):
            return _finish(*results[0])
    try:
        if suf == ".pdf":
            rows = G.rows_from_pdf(p)
        elif suf == ".docx":
            rows = G.rows_from_docx(p)
        else:
            raw = p.read_bytes()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp1252", errors="replace")
            rows = []
            for l in text.splitlines():
                # "2.1.10 | Text | 1.00 | m" or tab-separated lines are table rows
                if l.count("|") >= 2:
                    rows.append([c.strip() for c in l.strip().strip("|").split("|")])
                elif l.count("\t") >= 2:
                    rows.append([c.strip() for c in l.split("\t")])
                else:
                    rows.append([l])
        b = G.read_rows(rows, p.stem)
        results.append(("layout-independent", b, G.score(b)))
    except Exception:
        rows = []
    best = max(results, key=lambda r: r[2]["value"]) if results else None
    if use_ai is None:
        use_ai = os.environ.get("NR_AI_READER", "auto") != "off"
    if use_ai and (best is None or _weak(best[2])) and rows:
        try:
            from .llm_checks import available, llm_extract_items
            if available():
                b = llm_extract_items(rows, p.stem)
                sc = G.score(b)
                results.append(("ai", b, sc))
                best = max(results, key=lambda r: r[2]["value"])
        except Exception as e:                      # AI down / no credits: keep the best deterministic result
            if best is not None:
                best[1].parse_info["ai_error"] = f"{type(e).__name__}: {str(e)[:120]}"
    if best is None:
        return BoQ(name=p.stem)
    return _finish(*best, tried=[r[0] for r in results])


def _finish(reader: str, boq: BoQ, sc: dict, tried=None) -> BoQ:
    boq.parse_info = {**(boq.parse_info or {}), "reader": reader, "score": {k: v for k, v in sc.items() if k != "value"},
                      "tried": tried or [reader]}
    return boq
