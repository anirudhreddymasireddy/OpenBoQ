"""Layout-independent BoQ reader.

Works on a stream of rows (table rows, or text lines as one-cell rows) from any source: PDF tables, PDF text,
Word tables and paragraphs. No fixed template:

 1. Number format (German 1.234,56 or English 1,234.56) is detected from the whole document.
 2. Table rows with a recognised header are read by column (Pos / Menge / Einheit / EP / GP, Item / Qty / Unit / Rate / Amount …).
 3. Everything else is read as blocks that start with an item number (OZ, optionally "Pos." / "Item"):
    numbers are assigned by labels ("Menge:", "EP:", "à", "=", "€/m") or by position around the unit
    (quantity before the unit, then unit price, then total). Arithmetic (qty × EP ≈ GP) decides when the order is unclear,
    but never "repairs" a wrong total – calculation errors must stay visible.
 4. Lines between items without an OZ become notes (so contract clauses are still checked); total lines are kept.

`score()` rates a parse so the best of several readers can be chosen (see load_boq).
"""
from __future__ import annotations

import re
from pathlib import Path

from .model import BoQ, Item

# "2.1.3O" (letter O typed for zero) still opens an item – R30 reports the letter
OZ_START = re.compile(r"^(?:pos(?:ition)?\.?|oz|item|nr\.?|no\.?)?\s*(\d{1,4}(?:\.(?=[\dOo]*\d)[\dOo]{1,5}){1,5})\.?(?=\s|$|[–\-:|])\s*[–\-:|]?\s*(.*)$", re.I)
NUM_TOKEN = re.compile(r"(?<![\w/])-?\d{1,3}(?:[.,   ]\d{3})+(?:[.,]\d+)?(?![\d])|(?<![\w/.,])-?\d+(?:[.,]\d+)?(?![\d])")
UNIT_WORDS = {"m", "m2", "m²", "qm", "m3", "m³", "cbm", "st", "stk", "stck", "stück", "psch", "pauschal", "pa", "t", "kg", "h", "std",
              "d", "tag", "tage", "wo", "woche", "mt", "monat", "lfm", "l", "km", "ha", "mwo", "stwo", "m2wo", "m²wo", "satz", "le",
              "pcs", "pc", "no", "nr", "item", "ls", "lump", "hr", "hrs", "day", "days", "week", "wk", "month", "mo", "sqm", "lm",
              "m3wo", "ltr", "liter", "tonne", "tonnes"}
HEAD_KEYS = {
    "oz": r"^(?:pos(?:ition)?\.?(?:-?nr\.?)?|oz|ordnungszahl|nr\.?|item(?:\s*no\.?)?|no\.?|ref\.?)$",
    "lt": r"^(?:langtext|long\s*text|ausf[üu]hrungsbeschreibung|langbeschreibung|detail)",
    "text": r"beschreibung|leistung|kurztext|text|bezeichnung|description|work|scope",
    "qty": r"^(?:menge|qty|quantity|anzahl|vordersatz|mng\.?)$",
    "unit": r"^(?:einheit|eh|me|unit|einh\.?|uom)$",
    "up": r"einheitspreis|^ep\b|^ep\s*[€(]|rate|unit\s*price|e-?preis|preis\s*/\s*einheit",
    "it": r"gesamtpreis|^gp\b|^gp\s*[€(]|gesamtbetrag|amount|total|^betrag|summe|line\s*total",
}
LABELS = {"qty": r"(?:menge|qty|quantity|anzahl)\s*[:=]?", "up": r"(?:ep|einheitspreis|rate|unit\s*price|e-?preis)\s*[:=]?",
          "it": r"(?:gp|gesamtpreis|gesamt|amount|total|betrag)\s*[:=]?"}
VAT_RX = re.compile(r"(?:mehrwertsteuer|mwst\.?|umsatzsteuer|ust\.?|vat)\s*(\d{1,2}(?:[.,]\d+)?)\s*%", re.I)
GROSS_RX = re.compile(r"^(?:gesamtsumme|angebotssumme|endsumme|bruttosumme|grand\s+total|total\s+(?:incl|gross)\w*)(\s+brutto)?\b", re.I)
NET_RX = re.compile(r"^(?:netto(?:summe|betrag)?|summe\s+netto|nettoangebotssumme|(?:gesamt|angebots)summe\s+netto|net\s+total|subtotal\s+net)\b", re.I)
SECTION_SUM_RX = re.compile(r"^(?:summe|zusammenstellung|total|subtotal)\s+(?:bereich|abschnitt|titel|los|gewerk|section)?\s*(\d+(?:\.\d+)*)\.?\s", re.I)


# ---------------------------------------------------------------- numbers

def detect_format(text: str) -> str:
    de = len(re.findall(r"\d,\d{2}(?!\d)", text)) + 2 * len(re.findall(r"\d\.\d{3},\d", text))
    en = len(re.findall(r"\d\.\d{2}(?!\d)", text)) + 2 * len(re.findall(r"\d,\d{3}\.\d", text))
    return "en" if en > de else "de"


def to_num(tok: str, fmt: str):
    t = tok.replace(" ", "").replace(" ", "").replace(" ", "").strip()
    if fmt == "de":
        if re.fullmatch(r"-?\d+\.\d{2}", t):         # "5.00" in a German document: a typo, read as decimal
            return float(t), True
        t = t.replace(".", "").replace(",", ".")
    else:
        if re.fullmatch(r"-?\d+,\d{2}", t):
            return float(t.replace(",", ".")), True
        t = t.replace(",", "")
    try:
        return float(t), False
    except ValueError:
        return None, False


def numbers(s: str, fmt: str) -> list[tuple[float, int, int, str, bool]]:
    out = []
    for m in NUM_TOKEN.finditer(s):
        v, odd = to_num(m.group(0), fmt)
        if v is not None:
            out.append((v, m.start(), m.end(), m.group(0), odd))
    return out


def _unit_at(s: str, pos: int) -> str | None:
    m = re.match(r"\s*([A-Za-zÄÖÜäöü][A-Za-zÄÖÜäöü²³0-9]{0,5})\b\.?", s[pos:])
    if m and m.group(1).lower() in UNIT_WORDS:
        return m.group(1)
    return None


def _close(a, b):
    return b is not None and a is not None and abs(a - b) <= max(0.011, 0.0005 * abs(b))


# ---------------------------------------------------------------- reading a numeric line / cell set

def read_values(line: str, fmt: str) -> dict:
    """qty, unit, up, it from one line of numbers, by labels first, then by position around the unit."""
    low = line.lower()
    res: dict = {"odd": []}
    nums = numbers(line, fmt)
    if not nums:
        return res
    used = set()
    for key, lab in LABELS.items():                       # "Menge: 2.380,000 m  EP: 3,40 €  GP: 8.092,00 €"
        m = re.search(lab + r"\s*(?:€|eur)?\s*", low)
        if m:
            nxt = [n for n in nums if n[1] >= m.end() - 1 and n[1] - m.end() < 6 and n[1] not in used]
            if nxt:
                res[key] = nxt[0][0]; used.add(nxt[0][1])
                if nxt[0][4]: res["odd"].append(f"{key.upper()}: '{nxt[0][3]}'")
                if key == "qty":
                    res["unit"] = _unit_at(line, nxt[0][2])
    # "2.380,000 m à 3,40 €/m = 8.092,00 €"
    if "qty" not in res:
        cands = [n for n in nums if n[1] not in used and _unit_at(line, n[2]) and not re.match(r"\s*€", line[n[2]:])
                 and any(x[1] > n[2] for x in nums)]
        if not cands:
            cands = [n for n in nums if n[1] not in used and _unit_at(line, n[2]) and not re.match(r"\s*€", line[n[2]:])]
        if cands:
            n = cands[-1]
            res["qty"], res["unit"] = n[0], _unit_at(line, n[2]); used.add(n[1])
            if n[4]: res["odd"].append(f"Menge: '{n[3]}'")
    rest = [n for n in nums if n[1] not in used and n[1] > (min(u for u in used) if used else -1)]
    if "qty" in res:
        rest = [n for n in nums if n[1] not in used and n[1] > _pos_of(nums, res["qty"], used)]
    tags = []
    for n in rest:
        ctx = low[max(0, n[1] - 4):n[1]]
        tail = low[n[2]:n[2] + 6]
        if re.search(r"(à|@|ep)\s*$", ctx) or re.match(r"\s*€?\s*/", tail):
            tags.append(("up", n))
        elif re.search(r"=\s*$", ctx):
            tags.append(("it", n))
        else:
            tags.append((None, n))
    for want in ("up", "it"):
        if want in res:
            continue
        hit = next((n for t, n in tags if t == want), None)
        if hit is None:
            hit = next((n for t, n in tags if t is None), None)
            if hit is not None:
                tags = [(t, n) for t, n in tags if n is not hit]
        else:
            tags = [(t, n) for t, n in tags if n is not hit]
        if hit is not None:
            res[want] = hit[0]
            if hit[4]: res["odd"].append(f"{'EP' if want == 'up' else 'GP'}: '{hit[3]}'")
    # order unclear (no labels): if qty × it ≈ up, the two were swapped
    if "qty" in res and "up" in res and "it" in res and not _close(res["qty"] * res["up"], res["it"]) \
            and _close(res["qty"] * res["it"], res["up"]):
        res["up"], res["it"] = res["it"], res["up"]
    return res


def _pos_of(nums, value, used):
    for n in nums:
        if n[1] in used and n[0] == value:
            return n[1]
    return -1


def _is_numeric_line(s: str, fmt: str) -> bool:
    nums = numbers(s, fmt)
    if not nums:
        return False
    low = s.lower()
    if re.search(r"menge|qty|\bep\b|\bgp\b|einheitspreis|gesamtpreis|€|eur\b|amount|rate", low) and len(nums) >= 1:
        return True
    digits = sum(len(n[3]) for n in nums)
    letters = len(re.findall(r"[A-Za-zÄÖÜäöüß]", s))
    return len(nums) >= 2 and digits >= letters * 0.5


# ---------------------------------------------------------------- main reader

def read_rows(rows: list[list[str]], name: str = "") -> BoQ:
    boq = BoQ(name=name)
    alltext = "\n".join(" ".join(r) for r in rows)
    fmt = detect_format(alltext)
    boq.parse_info = {"reader": "generic", "number_format": fmt}
    colmap = None
    cur = None              # open text block: {"oz", "text": [], "num": []}
    blocks = []
    note: list[str] = []

    def flush_note():
        nonlocal note
        txt = "\n".join(note).strip()
        if len(txt.split()) >= 6:
            boq.notes.append({"ref": f"Hinweis nach Pos. {blocks[-1]['oz']}" if blocks else "Vorbemerkungen", "text": txt})
        note = []

    for row in rows:
        cells = [re.sub(r"[ \t]+", " ", (c or "")).strip() for c in row]
        cells = [c for c in cells] if len(cells) > 1 else cells
        joined = " ".join(c for c in cells if c)
        if not joined:
            # print layout "5.1.20  936,00 m2 …" followed by an indented but empty line: the short text is empty
            if (cur is not None and not cur["text"] and cur["num"] and len(row) == 1 and row[0]
                    and not row[0].strip()):
                cur["blank_st"] = True
            continue
        if _take_total(boq, joined, fmt):
            continue
        # header row of a table
        if len(cells) >= 3:
            cm = _header(cells)
            if cm:
                colmap = cm
                continue
        if colmap and len(cells) >= len(colmap) and len(cells) >= 3:
            it = _from_columns(cells, colmap, fmt)
            if it:
                flush_note()
                blocks.append({"oz": it.oz, "item": it})
                cur = None
                continue
            if not cells[colmap.get("oz", 0)] and cur is None and blocks and "item" in blocks[-1]:
                tcol = colmap.get("text")
                if tcol is not None and tcol < len(cells) and cells[tcol]:   # continuation row of the previous item
                    blocks[-1]["item"].long_text = (blocks[-1]["item"].long_text + "\n" + cells[tcol]).strip()
                    continue
        # text-like: a row whose first cell starts with an OZ opens a block
        first = cells[0] if cells else ""
        m = OZ_START.match(first) if first else None
        if m and not _looks_like_quantity(first, m.group(1), fmt):
            flush_note()
            rest = " ".join([m.group(2)] + cells[1:]).strip()
            cur = {"oz": m.group(1), "text": [], "num": []}
            blocks.append(cur)
            _feed(cur, rest, fmt)
            continue
        if cur is not None:
            if _is_numeric_line(joined, fmt) or len(cur["text"]) < 6:
                _feed(cur, joined, fmt)
                continue
        if cur is not None and len(cur["text"]) >= 6:
            cur = None
        note.append(joined)
    flush_note()

    for b in blocks:
        if "item" in b:
            _add(boq, b["item"])
            continue
        # several number lines (e.g. "DN 100 bis DN 300" in the text): the line with the most values wins
        allc = [(read_values(line, fmt), k, line) for k, line in enumerate(b["num"])]
        cand = [c for c in allc if c[0].get("qty") is not None] or allc
        vals = {"odd": []}
        demoted = []
        if cand:
            best = max(cand, key=lambda c: (sum(c[0].get(k) is not None for k in ("qty", "up", "it")), c[1]))
            vals = dict(best[0])
            for v, k, line in allc:              # labelled values on other lines ("EP: 3,40 €") may complete it
                if v is best[0]:
                    continue
                if re.search(r"menge|qty|\bep\b|\bgp\b|€|eur\b", line.lower()):
                    for key in ("qty", "unit", "up", "it"):
                        if vals.get(key) is None and v.get(key) is not None:
                            vals[key] = v[key]
                else:
                    demoted.append((k, line))    # a number-heavy text line ("cm bis 100 cm"), not values
        text = [t for t in b["text"] if t] + [l for k, l in demoted if k < best[1]] if cand else [t for t in b["text"] if t]
        if vals.get("qty") is None:
            if text:                                         # heading
                boq.sections.setdefault(b["oz"], text[0][:120])
            continue
        if b.get("blank_st"):
            text = [""] + text
        it = Item(oz=b["oz"].strip("."), short_text=text[0] if text else "", long_text="\n".join(text[1:]),
                  qty=vals.get("qty"), unit=vals.get("unit") or "", up=vals.get("up"), it=vals.get("it"))
        it.issues += [f"fmt:{o}" for o in vals["odd"]]
        for line in b["num"]:                              # "EP: 12,5O €" – a letter inside a number
            for m in re.finditer(r"\d[\d.,]*[Oo]\d*\b|\b[Oo]\d[\d.,]*", line):
                it.issues.append(f"Wert: '{m.group(0)}'")
            m = CUR_RX.search(line)                        # "EP: 607,60 USD" – price in another currency
            if m:
                it.issues.append(f"Währung: '{m.group(0)}'")
        _add(boq, it)
    return boq


def _feed(cur, text: str, fmt: str):
    if not text:
        return
    nums = numbers(text, fmt)
    if _is_numeric_line(text, fmt) and nums:
        # split "Kurztext ... 2.380,000 m 3,40 8.092,00": text part before the first value with a unit/label
        cut = _value_start(text, fmt)
        if cut > 0 and text[:cut].strip():
            cur["text"].append(text[:cut].strip(" -–:|"))
        vals, tail = _split_tail(text[cut:])
        cur["num"].append(vals)
        if tail:
            cur["text"].append(tail)
    else:
        cur["text"].append(text)


CUR_RX = re.compile(r"\d[\d.,]*\s*(?:DM|USD|CHF|GBP|US\$|\$|£)(?=\W|$)|(?:DM|USD|CHF|GBP)\s*\d[\d.,]*")
_AMOUNT = re.compile(r"\d[\d.,]*\s*(?:€|eur\b)(?:\s*/\s*[\w²³]+)?", re.I)


def _split_tail(vals: str) -> tuple[str, str]:
    """'… = 9.480,24 € (Wasserhaltung wird nicht gesondert vergütet.)' – words after the last amount are
    long text, not values; without this a clause written there is never checked."""
    ms = list(_AMOUNT.finditer(vals))
    if not ms:
        return vals, ""
    tail = vals[ms[-1].end():].strip()
    words = re.findall(r"[A-Za-zÄÖÜäöüß]{3,}", tail)
    if len(words) < 2:
        return vals, ""
    return vals[:ms[-1].end()], tail.strip(" ()[]-–:;|").strip()


def _value_start(text: str, fmt: str) -> int:
    low = text.lower()
    m = re.search(r"(?:menge|qty|quantity)\s*[:=]", low)
    if m:
        return m.start()
    nums = numbers(text, fmt)
    best = 0
    for n in nums:
        # "Geotextil (b = 12 m): 3.600,000 m² à 0,05 €" – the quantity is the LAST number+unit that is still
        # followed by price numbers; numbers+units inside the description come earlier
        if _unit_at(text, n[2]) and not re.match(r"\s*€", text[n[2]:]):
            later = [x for x in nums if x[1] > n[2]]
            if later or re.search(r"€|eur", low[n[2]:]):
                best = n[1]
    return best


def _looks_like_quantity(cell: str, oz: str, fmt: str) -> bool:
    """'2.380,000 m' at a line start is a quantity, not item 2.380."""
    after = cell[cell.find(oz) + len(oz):]
    return bool(re.match(r"[,]\d", after) or (fmt == "en" and re.match(r"\s*(?:" + "|".join(UNIT_WORDS) + r")\b", after, re.I)
                                             and oz.count(".") == 1))


def _header(cells) -> dict | None:
    cm = {}
    for k, c in enumerate(cells):
        low = c.lower().strip()
        if not low or len(low) > 30:
            continue
        for key, rx in HEAD_KEYS.items():
            if key not in cm and re.search(rx, low):
                cm[key] = k
                break
    return cm if {"qty"} <= cm.keys() and ({"up"} <= cm.keys() or {"it"} <= cm.keys()) and len(cm) >= 3 else None


def _from_columns(cells, cm, fmt) -> Item | None:
    def cell(k):
        i = cm.get(k)
        return cells[i] if i is not None and i < len(cells) else ""
    oz_cell = cell("oz") if "oz" in cm else cells[0]
    m = OZ_START.match(oz_cell)
    if not m:
        return None
    odd = []

    def val(k):
        ns = numbers(cell(k), fmt)
        if not ns:
            return None
        if ns[0][4]:
            odd.append(f"{ {'qty': 'Menge', 'up': 'EP', 'it': 'GP'}[k] }: '{ns[0][3]}'")
        return ns[0][0]
    qty = val("qty")
    if qty is None:
        return None
    unit = cell("unit")
    if not unit:                                    # unit inside the quantity cell: "2.380,000 m"
        ns = numbers(cell("qty"), fmt)
        unit = _unit_at(cell("qty"), ns[0][2]) or "" if ns else ""
    text = cell("text") if "text" in cm else " ".join(c for i, c in enumerate(cells) if i not in cm.values())
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) == 1 and re.search(r"\S\s\((?=.{25,}\)\s*$)", lines[0][10:]):   # "Kurztext (Langtext …)" in one cell
        par = re.search(r"\s\((?=.{25,}\)\s*$)", lines[0][10:])
        cut = par.start() + 10
        lines = [lines[0][:cut].strip(), lines[0][cut:].strip(" ()")]
    if len(lines) == 1 and len(lines[0]) > 140:     # wrapped cell (PDF): short text = first sentence / 140 chars
        t0 = lines[0]
        dash = t0.find(" - ", 10, 160)              # "Kurztext - Langtext" in one cell
        par = re.search(r"\s\((?=.{25,}\)\s*$)", t0[10:])   # "Kurztext (Langtext …)" in one cell
        cut = dash if dash > 0 else (par.start() + 10 if par else t0.find(". ", 20, 140))
        cut = cut + 1 if cut > 0 else (t0.rfind(" ", 0, 140) if " " in t0[:140] else 140)
        lines = [t0[:cut].strip(), t0[cut:].strip(" -–").strip("()").strip()]
    if "lt" in cm and cell("lt").strip():              # separate long-text column
        lines = (lines[:1] or [""]) + [cell("lt").strip()] + lines[1:]
    it = Item(oz=m.group(1).strip("."), short_text=lines[0] if lines else "", long_text="\n".join(lines[1:]),
              qty=qty, unit=unit.strip(), up=val("up"), it=val("it"))
    it.issues += [f"fmt:{o}" for o in odd]
    return it


def _take_total(boq: BoQ, line: str, fmt: str) -> bool:
    nums = numbers(line, fmt)
    if not nums:
        return False
    low = line.lower().strip()
    t = boq.totals
    m = VAT_RX.search(low)
    if m and len(nums) >= 2:
        t["vat_rate"] = float(m.group(1).replace(",", ".")) / 100
        t["vat"] = nums[-1][0]
        return True
    if NET_RX.match(low):
        t["net"] = nums[-1][0]
        return True
    g = GROSS_RX.match(low)
    if g:
        t["gross" if (g.group(1) or "vat" in t or "brutto" in low or "incl" in low) else "total"] = nums[-1][0]
        return True
    s = SECTION_SUM_RX.match(low)
    if s and len(nums) >= 2:
        t.setdefault("sections", {}).setdefault(s.group(1).strip("."), nums[-1][0])
        return True
    return False


def _add(boq: BoQ, it: Item):
    top = it.oz.split(".")[0]
    it.section_oz = top
    it.section = f"{top} {boq.sections.get(top, '')}".strip()
    it.lump_sum = it.unit.lower() in ("psch", "pa", "pauschal", "ls", "lump")
    low = (it.short_text + " " + it.long_text).lower()
    it.provisional = "bedarfsposition" in low or "eventualposition" in low
    it.alternative = "wahlposition" in low or "alternativposition" in low
    boq.items.append(it)


# ---------------------------------------------------------------- sources

def rows_from_pdf(path) -> list[list[str]]:
    """Tables where the PDF has ruled tables, text lines everywhere else – in reading order per page."""
    import pdfplumber
    rows = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            tables = page.find_tables() if (len(page.rects) + len(page.lines)) >= 4 else []
            boxes = [t.bbox for t in tables]
            words_lines = []
            # place tables at their vertical position
            items = []
            tl = page.extract_text_lines() if hasattr(page, "extract_text_lines") else []
            for ln in tl:
                if not any(b[1] <= ln["top"] <= b[3] and b[0] <= ln["x0"] <= b[2] for b in boxes):
                    items.append((ln["top"], [ln["text"]]))
            for t in tables:
                for k, r in enumerate(t.extract()):
                    items.append((t.bbox[1] + k * 0.01, [re.sub(r"\s*\n\s*", " ", c or "") for c in r]))
            if not tl and not tables:
                items = [(i, [line]) for i, line in enumerate((page.extract_text() or "").split("\n"))]
            rows += [r for _, r in sorted(items, key=lambda x: x[0])]
    return rows


def rows_from_docx(path) -> list[list[str]]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = Document(str(path))
    rows = []
    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            t = Paragraph(child, d).text
            for line in t.split("\n"):
                rows.append([line])
        elif tag == "tbl":
            for r in Table(child, d).rows:
                cells, last = [], None
                for c in r.cells:                          # merged cells repeat – keep once
                    if c._tc is last:
                        continue
                    last = c._tc
                    cells.append(c.text)
                rows.append(cells)
    return rows


# ---------------------------------------------------------------- quality score

def score(boq: BoQ) -> dict:
    items = boq.items
    n = len(items)
    full = [i for i in items if i.qty is not None and i.up is not None and i.it is not None]
    consistent = sum(1 for i in full if _close(i.qty * i.up, i.it))
    texted = sum(1 for i in items if len(i.short_text.strip()) >= 3)
    total_ok = None
    t = boq.totals or {}
    net = t.get("net") or ((t["vat"] / t["vat_rate"]) if t.get("vat") and t.get("vat_rate") else None) or \
        ((t["gross"] / (1 + (t.get("vat_rate") or 0.19))) if t.get("gross") else None)
    if net and n:
        s = sum(i.total for i in items)
        total_ok = abs(s - net) <= max(1.0, 0.0005 * net)
    value = n * (0.4 + 0.4 * (texted / n if n else 0) + 0.2 * (consistent / len(full) if full else 0.5)) + (5 if total_ok else 0)
    return {"items": n, "with_text": texted, "arith_ok": consistent, "priced": len(full), "totals_match": total_ok, "value": value}
