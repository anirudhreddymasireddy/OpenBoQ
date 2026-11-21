"""Layout-tolerant BoQ reader for text PDFs (AVA print-outs, tender documents, bids).

Strategy (no fixed template):
 1. Extract lines per page, drop running headers/footers (lines repeated on many pages, column headers, carry-overs).
 2. A line starting with an OZ ("1.8.20.", "01.0001", "2.1.150") opens a block.
 3. A block that contains a quantity line ("6.800,000 m³ ....", "1 psch ....", or "OZ qty unit EP GP") is an item;
    a block without one is a heading / note.
 4. Prices are taken when printed (bids, priced LVs); dotted placeholders mean an unpriced tender.
Validation: parsed totals can be compared with GAEB versions of the same LV (see tests / cli 'pdfcheck').
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .gaeb_parser import parse_number as _pn


def parse_number(s):
    """German print format: '1.300' (no comma) is one thousand three hundred."""
    if isinstance(s, str) and "," not in s and re.fullmatch(r"\d{1,3}(\.\d{3})+", s.strip()):
        s = s.replace(".", "")
    return _pn(s)
from .model import BoQ, Item

NUM = r"\d{1,3}(?:\.\d{3})*(?:,\d{1,4})?|\d+(?:,\d{1,4})?"
UNIT = r"[A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü²³0-9/\.\-]{0,9}"
OZ_RX = re.compile(r"^(\d{1,4}(?:\s?\.\s?\d{1,5}){1,5})\s?\.?(?=\s|$)\s*(.*)$")
QTY_LINE = re.compile(rf"^(?:ca\.\s*)?({NUM})\s+({UNIT})\s*(.*)$")
INLINE_ITEM = re.compile(rf"^(\d{{1,4}}(?:\.\d{{1,5}}){{1,5}})\.?\s+({NUM})\s+({UNIT})\s+({NUM}|\.{{3,}}[\. ]*)\s+({NUM}|\.{{3,}}[\. ]*)\s*$")
PRICES = re.compile(rf"({NUM})\s+({NUM})\s*$")
UNITS_OK = {"m", "m2", "m²", "qm", "m3", "m³", "cbm", "st", "stk", "stck", "stück", "psch", "pa", "pauschal", "t", "kg", "h", "std",
            "d", "tag", "tage", "wo", "woche", "wochen", "mt", "mon", "monat", "monate", "lfm", "l", "km", "ha", "mwo", "stwo",
            "m2wo", "m²wo", "stck.", "st.", "psch.", "jahr", "a", "satz", "lst", "le", "vb", "mh", "ltr", "liter", "m3wo"}
SKIP = re.compile(r"^(übertrag|seite\s*\d|summe|zwischensumme|ordnungszahl|oz\s|pos-?nr|pos\s|in eur|i n eur|leistungsverzeichnis|"
                  r"projekt:|lv:|datum|lv-datum|bauvorhaben|übertrag:|nr\.\)|menge\s|einheitspreis|gesamtbetrag)", re.I)


_CTRL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")   # control chars some PDF engines emit


def _clean(line: str) -> str:
    line = _CTRL.sub("", line).replace("\u00a0", " ").replace("\u017e", " ")
    line = re.sub(r"\s+", " ", line).strip()
    return line


def _unit_ok(u: str) -> bool:
    return u.lower().rstrip(".") in UNITS_OK or u.lower() in UNITS_OK


def _norm_oz(oz: str) -> str:
    return re.sub(r"\s", "", oz).strip(".")


def oz_key(oz: str) -> tuple:
    """Canonical OZ for matching across formats: '01.01.0010' == '1.1.10'."""
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"[.\s]+", oz.strip(".")) if p)


def _pages_pdfium(path) -> list[str]:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(path))
    try:
        return [doc[i].get_textpage().get_text_range() or "" for i in range(len(doc))]
    finally:
        doc.close()


def _pages_plumber(path) -> list[str]:
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        return [page.extract_text(x_tolerance=1.5) or "" for page in pdf.pages]


def _pages_plumber_subset(path, idx: list[int]) -> list[str]:
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        return [pdf.pages[i].extract_text(x_tolerance=1.5) or "" for i in idx]


def _sample_agrees(path, fast_texts: list[str]) -> bool:
    """Cross-check the fast engine on a few sample pages against pdfplumber."""
    n = len(fast_texts)
    idx = sorted({int(k * (n - 1) / 4) for k in range(5)}) if n > 5 else list(range(n))
    slow = _pages_plumber_subset(path, idx)
    a = {(i.oz, i.qty) for i in _parse_lines(_lines_from_texts(slow, filter_headers=False), "x").items}
    b = {(i.oz, i.qty) for i in _parse_lines(_lines_from_texts([fast_texts[i] for i in idx], filter_headers=False), "x").items}
    if len(a) < 3 or len(a & b) >= 0.9 * len(a):
        return True                       # engines agree -> keep the fast one
    if len(b) >= 1.15 * len(a):
        return True                       # fast engine clearly reads more items (pdfplumber splits words here)
    return False                          # they disagree and it's close -> accuracy over speed


def extract_lines(path, engine: str | None = None) -> list[str]:
    """Fast engine (pypdfium2, ~30x faster) with a sample cross-check; falls back to pdfplumber for layouts
    where the fast engine reads columns in a different order. NR_PDF=plumber forces pdfplumber."""
    import os
    engine = engine or os.environ.get("NR_PDF", "auto")
    texts = []
    if engine in ("auto", "pdfium"):
        try:
            texts = _pages_pdfium(path)
        except Exception:
            texts = []
        if texts and engine == "auto" and not _sample_agrees(path, texts):
            texts = []
    if not texts or sum(len(t) for t in texts) < 50:
        texts = _pages_plumber(path)
    return _lines_from_texts(texts)


def _lines_from_texts(texts: list[str], filter_headers: bool = True) -> list[str]:
    pages = [[_clean(l) for l in t.splitlines() if _clean(l)] for t in texts]
    # running headers/footers: identical lines on > 40 % of pages. Digits are normalised only for lines that look
    # like page furniture (page numbers, dates); item / quantity lines are never dropped, however often they repeat.
    def norm(s):
        return re.sub(r"\d+", "#", s) if re.search(r"seite|page|datum|stand|druck", s, re.I) else s
    def protected(s):
        return bool(OZ_RX.match(s) or QTY_LINE.match(s) or INLINE_ITEM.match(s))
    cnt = Counter(n for p in pages for n in {norm(l) for l in p})
    thresh = max(3, 0.4 * len(pages))
    out = []
    for p in pages:
        for l in p:
            if filter_headers and len(pages) > 2 and cnt[norm(l)] >= thresh and not protected(l):
                continue
            if SKIP.match(l):
                continue
            out.append(l)
    return out


def parse_pdf(path) -> BoQ:
    return _parse_lines(extract_lines(path), Path(path).stem)


def _parse_lines(lines: list[str], name: str) -> BoQ:
    boq = BoQ(name=name)
    blocks: list[tuple[str, list[str]]] = []
    cur = None
    preamble: list[str] = []
    for l in lines:
        m_inline = INLINE_ITEM.match(l)
        m = OZ_RX.match(l)
        if m_inline or (m and not QTY_LINE.match(l[len(m.group(1)):].strip() or "x") is None and _looks_like_oz(m.group(1))):
            pass
        if not m_inline and _is_qty_line(l):
            if cur is not None:
                cur[1].append(l)
            continue
        if m_inline or (m and _looks_like_oz(m.group(1))):
            cur = (l, [])
            blocks.append(cur)
        elif cur is not None:
            cur[1].append(l)
        else:
            preamble.append(l)
    if len(preamble) > 3:
        boq.notes.append({"ref": "Vorbemerkungen", "text": "\n".join(preamble)})

    section_oz, section_label = "", ""
    for head, body in blocks:
        mi = INLINE_ITEM.match(head)
        if mi:   # bid layout: "2.1.150 50,000 m³ 32,00 1.600,00" + short text on next line(s)
            oz = _norm_oz(mi.group(1))
            it = Item(oz=oz, short_text=body[0] if body else "", long_text="\n".join(body[1:]),
                      qty=parse_number(mi.group(2)), unit=mi.group(3),
                      up=parse_number(mi.group(4)) if mi.group(4)[0].isdigit() else None,
                      it=parse_number(mi.group(5)) if mi.group(5)[0].isdigit() else None)
            _add(boq, it, section_oz, section_label)
            continue
        m = OZ_RX.match(head)
        oz, first = _norm_oz(m.group(1)), m.group(2).strip()
        qty_idx = None
        for k in range(len(body) - 1, -1, -1):          # strong evidence: dotted price columns or printed prices
            if _is_qty_line(body[k]):
                qty_idx = k
                break
        if qty_idx is None and body:                     # weak: bare "1,000 St" as the block's last line
            q = QTY_LINE.match(body[-1])
            if q and _unit_ok(q.group(2)) and not q.group(3):
                qty_idx = len(body) - 1
        if qty_idx is None:
            # heading / note
            if len(body) >= 2:                   # heading with explanatory text = preliminary note
                boq.notes.append({"ref": oz, "text": "\n".join([first] + body)})
            if first and len(first) < 120:
                boq.sections[oz] = first
                if oz.count(".") <= 1 or not section_oz:
                    section_oz, section_label = oz.split(".")[0], f"{oz} {first}"
            continue
        q = QTY_LINE.match(body[qty_idx])
        text_lines = body[:qty_idx]
        short = first or (text_lines[0] if text_lines else "")
        if text_lines and first and text_lines[0].replace(" ", "") == first.replace(" ", ""):
            text_lines = text_lines[1:]          # short text repeated as first long-text line
        rest = q.group(3)
        up = it_ = None
        pm = PRICES.search(rest)
        if pm:
            up, it_ = parse_number(pm.group(1)), parse_number(pm.group(2))
        it = Item(oz=oz, short_text=short, long_text="\n".join(text_lines),
                  qty=parse_number(q.group(1)), unit=q.group(2), up=up, it=it_)
        _add(boq, it, section_oz, section_label)
    _dedupe(boq)
    return boq


def _is_qty_line(l: str) -> bool:
    q = QTY_LINE.match(l)
    if not q or not _unit_ok(q.group(2)):
        return False
    rest = q.group(3)
    if not rest.strip() and re.search(r",\d{3}$", q.group(1)):   # GAEB prints quantities with 3 decimals: "2,000 St"
        return True
    return bool(re.search(r"\.{3,}", rest) or PRICES.fullmatch(rest.strip()) or re.fullmatch(r"[\d\.,]+", rest.strip() or "x"))


def _looks_like_oz(s: str) -> bool:
    parts = [p for p in re.split(r"\s?\.\s?", s.strip()) if p]
    if len(parts) < 2:
        return False
    if re.fullmatch(r"\d{1,2}", parts[0]) and re.fullmatch(r"\d{1,2}", parts[1]) and len(parts) == 3 and len(parts[2]) == 4 \
            and parts[2].startswith(("19", "20")):
        return False   # a date 01.02.2024
    return True


def _add(boq: BoQ, it: Item, section_oz: str, section_label: str):
    top = it.oz.split(".")[0]
    it.section_oz = top
    it.section = boq.sections.get(top, section_label or top)
    if it.section and not it.section.startswith(top):
        it.section = f"{top} {it.section}"
    it.lump_sum = it.unit.lower() in ("psch", "pa", "pauschal")
    low = (it.short_text + " " + it.long_text).lower()
    it.provisional = "bedarfsposition" in low or "eventualposition" in low or "nur auf anordnung" in low[:200]
    it.alternative = "wahlposition" in low or "alternativposition" in low
    boq.items.append(it)


def _dedupe(boq: BoQ):
    seen, out = set(), []
    for it in boq.items:
        key = (it.oz, it.qty, it.unit)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    boq.items = out
