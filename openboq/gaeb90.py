"""GAEB 90 reader (fixed-width 80-column records: .D81/.D83/.D84/.D86, also .P8x-style text).

Record types used:
  00 header (data phase at cols 11-12, OZ mask e.g. "1122PPPPI" at cols 63-71)
  01/02/03 LV / project / client names
  11 section (Bereich) start, OZ in cols 3-11      12 section label
  21 item: OZ cols 3-11, item-type flags cols 13-15, quantity cols 24-34 (3 decimals), unit cols 35-38
  23 prices: unit price + total (2 decimals)       25 short text      26 long text
  31 section end                                   99 end of file
Lines starting with T0/T1 (preamble text in some exports) are skipped.
"""
from __future__ import annotations

import re
from pathlib import Path

from .model import BoQ, Item


def _decode(raw: bytes) -> str:
    best, score = None, -1
    for enc in ("cp850", "cp437", "latin-1"):
        try:
            txt = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        s = sum(txt.count(c) for c in "äöüÄÖÜß") - 5 * sum(txt.count(c) for c in "├┤╝╗║═")
        if s > score:
            best, score = txt, s
    return best or raw.decode("latin-1", errors="replace")


def _split_oz(field: str, mask: str) -> str:
    """Apply the OZ mask ('1122PPPPI') to the 9-char OZ field -> '01.01.1'."""
    field = field.ljust(len(mask))
    parts, cur, cur_key = [], "", None
    for ch, m in zip(field, mask):
        key = "I" if m == "I" else m
        if key != cur_key and cur_key is not None:
            parts.append((cur_key, cur))
            cur = ""
        cur_key = key
        cur += ch
    parts.append((cur_key, cur))
    out = []
    for key, val in parts:
        if key == "I":
            continue                      # index digit – rarely used
        v = val.strip()
        if v:
            out.append(v.lstrip("0").rjust(1, "0") if key == "P" and v.isdigit() and len(v) > 4 else v)
    return ".".join(out)


def _num(s: str, dec: int):
    s = s.strip()
    if not s or not re.fullmatch(r"-?\d+", s):
        return None
    return int(s) / (10 ** dec)


def parse_gaeb90(path) -> BoQ:
    p = Path(path)
    text = _decode(p.read_bytes())
    lines = [l.rstrip("\r\n").ljust(80) for l in text.splitlines()]
    boq = BoQ(name=p.stem)
    mask = "1122PPPPI"
    section_oz, section_label, pending_section = "", "", None
    cur: Item | None = None
    long_buf: list[str] = []
    preamble: list[str] = []

    def flush():
        nonlocal cur, long_buf
        if cur is not None:
            cur.long_text = re.sub(r"[ \t]+", " ", "\n".join(l.strip() for l in long_buf)).strip()
            boq.items.append(cur)
        cur, long_buf = None, []

    for l in lines:
        rt = l[:2]
        body = l[2:72]
        if rt in ("T0", "T1", "T9"):
            if rt == "T1":
                preamble.append(body.strip())
            continue
        if rt == "00":
            dp = l[10:12].strip()
            if dp.isdigit():
                boq.phase = dp
            m = re.search(r"([12345P]{2,}[PI]+)\s*90", l)
            if m:
                mask = m.group(1)
        elif rt == "01":
            boq.name = body[:40].strip() or boq.name
        elif rt == "02":
            boq.project = body[:60].strip()
        elif rt == "03":
            boq.client = body[:60].strip()
        elif rt == "11":
            flush()
            oz = _split_oz(l[2:11], mask[: len(l[2:11].rstrip())] if l[2:11].rstrip() else mask)
            pending_section = oz.strip(".")
        elif rt == "12" and pending_section is not None:
            label = body.strip()
            boq.sections[pending_section] = label
            if pending_section.count(".") == 0:
                section_oz, section_label = pending_section, f"{pending_section} {label}"
            pending_section = None
        elif rt == "21":
            flush()
            oz = _split_oz(l[2:11], mask)
            flags = l[12:15]
            qty = _num(l[23:34], 3)
            bad_qty = l[23:34].strip() and qty is None
            unit = l[34:38].strip()
            top = oz.split(".")[0]
            cur = Item(oz=oz, short_text="", qty=qty, unit=unit,
                       section=section_label or boq.sections.get(top, top), section_oz=section_oz or top,
                       provisional=any(c in flags for c in "EB"), alternative="A" in flags,
                       lump_sum=unit.lower() in ("psch", "pa"),
                       issues=[f"Qty: '{l[23:34].strip()}'"] if bad_qty else [])
        elif rt == "23":
            oz23 = _split_oz(l[2:11], mask)
            if cur is None or cur.oz != oz23:      # bid files (D84) may carry prices only, no item records
                flush()
                top = oz23.split(".")[0]
                cur = Item(oz=oz23, short_text="", section=section_label or top, section_oz=section_oz or top)
            nums = re.findall(r"\d+", l[11:60])
            if len(nums) >= 2:
                cur.up, cur.it = int(nums[0]) / 100, int(nums[1]) / 100
                if cur.up == 0 and cur.it == 0:
                    cur.up = cur.it = None
        elif rt == "25" and cur is not None:
            cur.short_text = (cur.short_text + " " + body.strip()).strip()
        elif rt == "26" and cur is not None:
            long_buf.append(body)
        elif rt in ("31", "99"):
            flush()
    flush()
    if any(preamble):
        boq.notes.append({"ref": "Vorbemerkungen", "text": "\n".join(preamble).strip()})
    _fix_price_decimals(boq)
    return boq


def _fix_price_decimals(boq: BoQ) -> None:
    """Unit prices may carry 2 or 3 decimals depending on the exporting software: pick what makes qty × EP = GP."""
    priced = [i for i in boq.items if i.up and i.it and i.qty]
    if not priced:
        for i in boq.items:                       # price-only bid: derive quantity
            if i.up and i.it and i.qty is None:
                i.qty = round(i.it / i.up, 3)
        return
    def bad(div):
        return sum(1 for i in priced if abs(i.qty * i.up / div - i.it) > max(0.05, 0.001 * i.it))
    if bad(10) < bad(1):
        for i in boq.items:
            if i.up:
                i.up = i.up / 10
