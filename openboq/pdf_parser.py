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
NUMP = rf"{NUM}|\d+\.\d{{2}}(?!\d)"          # price that may use a dot as decimal separator ("5.00" – a typo)
UNIT = r"[A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü²³0-9/\.\-]{0,9}"
OZ_RX = re.compile(r"^(\d{1,4}(?:\s?\.\s?\d{1,5}){1,5})\s?\.?(?=\s|$)\s*(.*)$")
QTY_LINE = re.compile(rf"^(?:ca\.\s*)?({NUM})\s+({UNIT})\s*(.*)$")
INLINE_ITEM = re.compile(rf"^(\d{{1,4}}(?:\.\d{{1,5}}){{1,5}})\.?\s+({NUM})\s+({UNIT})\s+({NUMP}|\.{{3,}}[\. ]*)\s+({NUMP}|\.{{3,}}[\. ]*)\s*$")
PRICES = re.compile(rf"({NUMP})\s+({NUMP})\s*$")
_EUR = r"\s*(?:€|eur(?:o)?)?"
VAT_RX = re.compile(rf"^(?:zzgl\.?|zuzüglich|\+)?\s*(?:mehrwertsteuer|mwst\.?|umsatzsteuer|ust\.?)\s*(\d{{1,2}}(?:[,.]\d+)?)\s*%.*?({NUM}){_EUR}$", re.I)
NET_RX = re.compile(rf"^(?:netto(?:summe|betrag)?|summe\s+netto|(?:gesamt|angebots|end)summe\s+netto|nettoangebotssumme)\s*:?{_EUR}\s*({NUM}){_EUR}$", re.I)
GROSS_RX = re.compile(rf"^(?:gesamtsumme|angebotssumme|endsumme|bruttosumme)(\s+brutto)?\s*(?:inkl\.?[^:\d]*)?:?{_EUR}\s*({NUM}){_EUR}$", re.I)
SECTION_SUM_RX = re.compile(rf"^(?:summe|zusammenstellung)\s+(?:bereich|abschnitt|titel|los|gewerk|hauptabschnitt)?\s*(\d+(?:\.\d+)*)\.?\s+(?:.*?\s)?({NUM}){_EUR}$", re.I)
NOTE_RX = re.compile(r"^hinweistext\b", re.I)    # AVA print label for a note between items ("Hinweis:" inside a long text is not)
NOTE_HEAD = "__note__"
HEADING_RX = re.compile(r"^(?:bereich|abschnitt|titel|los|gewerk|hauptabschnitt)\s+\d+(?:\.\d+)*\.?(?:\s|$)", re.I)
SUMMARY_RX = re.compile(r"^(?:gesamt)?zusammenstellung\b", re.I)


def _is_total_line(l: str) -> bool:
    return bool(VAT_RX.match(l) or NET_RX.match(l) or GROSS_RX.match(l) or SECTION_SUM_RX.match(l))


def _price(tok: str, issues: list, field: str):
    """Parse a printed price; a dot used as decimal separator is read correctly but reported."""
    if re.fullmatch(r"\d+\.\d{2}", tok):
        issues.append(f"fmt:{field}: '{tok}'")
        return float(tok)
    return parse_number(tok)
UNITS_OK = {"m", "m2", "m²", "qm", "m3", "m³", "cbm", "st", "stk", "stck", "stück", "psch", "pa", "pauschal", "t", "kg", "h", "std",
            "d", "tag", "tage", "wo", "woche", "wochen", "mt", "mon", "monat", "monate", "lfm", "l", "km", "ha", "mwo", "stwo",
            "m2wo", "m²wo", "stck.", "st.", "psch.", "jahr", "a", "satz", "lst", "le", "vb", "mh", "ltr", "liter", "m3wo",
            "to", "tn", "pau", "set", "sat"}
SKIP = re.compile(r"^(übertrag|seite\s*\d|summe|zwischensumme|ordnungszahl|oz\s|pos-?nr|pos\s|in eur|i n eur|leistungsverzeichnis|"
                  r"projekt:|lv:|datum|lv-datum|bauvorhaben|übertrag:|nr\.\)|menge\s|einheitspreis|gesamtbetrag)", re.I)


_CTRL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")   # control chars some PDF engines emit


def _clean(line: str) -> str:
    line = _CTRL.sub("", line).replace("\u00a0", " ").replace("\u017e", " ")
    line = re.sub(r"\s+", " ", line).strip()
    # pdfium sometimes splits a number with a space: "1 0,000 St" -> "10,000 St"
    line = re.sub(r"^(\d{1,2}) (\d{1,3}(?:\.\d{3})*,\d{3}\s+[A-Za-zÄÖÜäöü])", r"\1\2", line)
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
    ia = _parse_lines(_lines_from_texts(slow, filter_headers=False), "x").items
    ib = _parse_lines(_lines_from_texts([fast_texts[i] for i in idx], filter_headers=False), "x").items
    a, b = {(i.oz, i.qty) for i in ia}, {(i.oz, i.qty) for i in ib}
    # texts must survive too: the fast engine sometimes reorders text and quantity lines -> items lose their short text
    sa = {(i.oz, i.short_text.strip()[:30]) for i in ia}
    sb = {(i.oz, i.short_text.strip()[:30]) for i in ib}
    if len(a) >= 3 and len(sa & sb) < 0.9 * len(sa):
        return False
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
        return bool(OZ_RX.match(s) or QTY_LINE.match(s) or INLINE_ITEM.match(s) or _is_total_line(s))
    cnt = Counter(n for p in pages for n in {norm(l) for l in p})
    thresh = max(3, 0.4 * len(pages))
    out = []
    for p in pages:
        for l in p:
            if filter_headers and len(pages) > 2 and cnt[norm(l)] >= thresh and not protected(l):
                continue
            if SKIP.match(l) and not _is_total_line(l):
                continue
            out.append(l)
    return out


def parse_pdf(path) -> BoQ:
    import os
    boq = _parse_lines(extract_lines(path), Path(path).stem)
    empty = sum(1 for i in boq.items if not i.short_text.strip())
    if os.environ.get("NR_PDF", "auto") == "auto" and empty >= max(3, 0.03 * len(boq.items)):
        # items without text: maybe the fast engine mixed up the line order -> compare with pdfplumber once
        alt = _parse_lines(_lines_from_texts(_pages_plumber(path)), Path(path).stem)
        alt_empty = sum(1 for i in alt.items if not i.short_text.strip())
        if alt_empty < empty and len(alt.items) >= 0.98 * len(boq.items):
            boq = alt
    return boq


REL_OZ = re.compile(r"^\.(\d{1,4})\s+(\S.*)$")


def _absolute_oz(lines: list[str]) -> list[str]:
    """Some AVA prints number items relative to their title: ".1", ".2" … – make them absolute ("1.1", "1.2", then
    "2.1" when the count restarts) so they can be read and referenced like any other item number."""
    if sum(1 for l in lines if REL_OZ.match(l)) < 3:
        return lines
    out, group, last = [], 1, 0
    for l in lines:
        m = REL_OZ.match(l)
        if m:
            n = int(m.group(1))
            if n <= last:
                group += 1
            last = n
            l = f"{group}.{n} {m.group(2)}"
        out.append(l)
    return out


def _parse_lines(lines: list[str], name: str) -> BoQ:
    boq = BoQ(name=name)
    lines = _absolute_oz(lines)
    blocks: list[tuple[str, list[str]]] = []
    cur = None
    preamble: list[str] = []
    for l in lines:
        if _take_total(boq, l):
            continue
        hm = HEADING_RX.match(l)
        if hm:
            num, _, label = l.partition(" ")[2].partition(" ")
            boq.sections.setdefault(num.strip("."), label.strip())
        if SUMMARY_RX.match(l) or (blocks and hm):
            cur = ("", [])                       # summary page / "Bereich 4." heading: following lines are not item text
            continue
        if blocks and NOTE_RX.match(l):          # "Hinweistext …" between items: a note, not the previous item's long text
            prev = next((b[0] for b in reversed(blocks) if b[0] != NOTE_HEAD), "")
            cur = (NOTE_HEAD, [l], prev)
            blocks.append(cur)
            continue
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
    for blk in blocks:
        head, body = blk[0], blk[1]
        if head == NOTE_HEAD:
            m_prev = OZ_RX.match(blk[2]) if blk[2] else None
            ref = f"Hinweis nach Pos. {_norm_oz(m_prev.group(1))}" if m_prev else "Hinweistext"
            if len(" ".join(body).split()) > 1:  # a bare "Hinweistext" label carries nothing
                boq.notes.append({"ref": ref, "text": "\n".join(body)})
            continue
        mi = INLINE_ITEM.match(head)
        if mi:   # bid layout: "2.1.150 50,000 m³ 32,00 1.600,00" + short text on next line(s)
            oz = _norm_oz(mi.group(1))
            iss: list = []
            it = Item(oz=oz, short_text=body[0] if body else "", long_text="\n".join(body[1:]),
                      qty=parse_number(mi.group(2)), unit=mi.group(3),
                      up=_price(mi.group(4), iss, "EP") if mi.group(4)[0].isdigit() else None,
                      it=_price(mi.group(5), iss, "GP") if mi.group(5)[0].isdigit() else None)
            it.issues += iss
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
        iss: list = []
        pm = PRICES.search(rest)
        if pm:
            up, it_ = _price(pm.group(1), iss, "EP"), _price(pm.group(2), iss, "GP")
        it = Item(oz=oz, short_text=short, long_text="\n".join(text_lines),
                  qty=parse_number(q.group(1)), unit=q.group(2), up=up, it=it_)
        it.issues += iss
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


def _take_total(boq: BoQ, l: str) -> bool:
    t = boq.totals
    m = VAT_RX.match(l)
    if m:
        t["vat_rate"] = float(m.group(1).replace(",", ".")) / 100
        t["vat"] = parse_number(m.group(2))
        return True
    m = NET_RX.match(l)
    if m:
        t["net"] = parse_number(m.group(1))
        return True
    m = GROSS_RX.match(l)
    if m:
        t["gross" if (m.group(1) or "vat" in t) else "total"] = parse_number(m.group(2))
        return True
    m = SECTION_SUM_RX.match(l)
    if m:
        t.setdefault("sections", {}).setdefault(m.group(1).strip("."), parse_number(m.group(2)))   # first print wins
        return True
    return False


def _dedupe(boq: BoQ):
    """Drop only true repeats (same OZ, quantity, unit AND text – e.g. a carry-over printed twice).
    Two different items sharing an OZ are kept so the duplicate-OZ check can report them."""
    seen, out = set(), []
    for it in boq.items:
        key = (it.oz, it.qty, it.unit, it.short_text.strip(), it.up)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    boq.items = out
