"""Tolerant GAEB DA XML reader (X81, X83, X84, X86 ... versions 3.x) plus CSV/XLSX loader.

Design goal: the hackathon data format is unknown in advance, so the parser ignores XML
namespaces and versions and walks the structure by local element names.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

from lxml import etree

from .model import BoQ, Item


def _local(tag) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.split("}", 1)[-1]


def _child(el, name: str):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _children(el, name: str) -> Iterable:
    return (c for c in el if _local(c.tag) == name)


def _find_desc(el, name: str):
    for c in el.iter():
        if _local(c.tag) == name:
            return c
    return None


def _first(*els):
    """lxml elements are falsy when they have no children, so never use `a or b` on them."""
    for e in els:
        if e is not None:
            return e
    return None


def _rich_text(el) -> str:
    """Flatten GAEB formatted text (<p><span>...) into plain text, one line per paragraph."""
    if el is None:
        return ""
    for br in el.iter():
        if _local(br.tag) == "br":
            br.tail = "\n" + (br.tail or "")
    paras = [p for p in el.iter() if _local(p.tag) == "p"]
    if paras:
        lines = ["".join(p.itertext()).strip() for p in paras]
    else:
        lines = ["".join(el.itertext()).strip()]
    text = "\n".join(l for l in lines if l)
    return re.sub(r"[ \t]+", " ", text).strip()


def parse_number(val) -> Optional[float]:
    """Parse '1234.5', '1.234,50', '1 234,5' -> float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(" ", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _flag(el, name: str) -> bool:
    c = _child(el, name)
    if c is None:
        return False
    v = (c.text or "").strip().lower()
    return v in ("", "yes", "true", "1", "withtotal", "withouttotal")


def _parse_item(el, prefix: list[str], section_oz: str, section_label: str) -> Item:
    rno = el.get("RNoPart", "") or ""
    oz = ".".join([p for p in prefix + [rno] if p])

    desc = _child(el, "Description")
    short_text, long_text = "", ""
    if desc is not None:
        outl = _first(_find_desc(desc, "TextOutlTxt"), _find_desc(desc, "OutlTxt"), _find_desc(desc, "OutlineText"))
        short_text = _rich_text(outl)
        detail = _find_desc(desc, "DetailTxt")
        if detail is not None:
            long_text = _rich_text(_first(_find_desc(detail, "Text"), detail))
    if not short_text and long_text:
        short_text = long_text.split("\n", 1)[0][:120]

    def num(name):
        c = _child(el, name)
        return parse_number(c.text) if c is not None else None

    provis = _child(el, "Provis")
    item = Item(
        oz=oz,
        short_text=short_text,
        long_text=long_text,
        qty=num("Qty"),
        unit=((_child(el, "QU").text or "").strip() if _child(el, "QU") is not None else ""),
        up=num("UP"),
        it=num("IT"),
        section=section_label,
        section_oz=section_oz,
        provisional=provis is not None,
        alternative=_child(el, "ALNGroupNo") is not None or _child(el, "ALNSerNo") is not None,
        lump_sum=_flag(el, "LumpSumItem"),
        qty_tbd=_flag(el, "QtyTBD"),
        hourly=_flag(el, "HourIt"),
        stlb=any("STLB" in _local(c.tag).upper() for c in el.iter()),
        raw_id=el.get("ID", ""),
    )
    return item


def _walk_body(body, prefix: list[str], boq: BoQ, section_oz: str, section_label: str) -> None:
    for node in body:
        name = _local(node.tag)
        if name == "BoQCtgy":
            rno = node.get("RNoPart", "") or ""
            label = _rich_text(_child(node, "LblTx"))
            new_prefix = prefix + [rno] if rno else prefix
            oz = ".".join(new_prefix)
            boq.sections[oz] = label
            # Items inherit the *top-level* Titel as their section.
            if not section_oz:
                s_oz, s_label = oz, f"{oz} {label}".strip()
            else:
                s_oz, s_label = section_oz, section_label
            sub = _child(node, "BoQBody")
            if sub is not None:
                _walk_body(sub, new_prefix, boq, s_oz, s_label)
        elif name == "Itemlist":
            for it in node:
                if _local(it.tag) == "Item":
                    boq.items.append(_parse_item(it, prefix, section_oz, section_label))
        elif name == "Item":
            boq.items.append(_parse_item(node, prefix, section_oz, section_label))


def parse_gaeb_xml(path_or_bytes) -> BoQ:
    if isinstance(path_or_bytes, (bytes, bytearray)):
        root = etree.fromstring(bytes(path_or_bytes), parser=etree.XMLParser(recover=True, huge_tree=True))
        fname = ""
    else:
        p = Path(path_or_bytes)
        root = etree.parse(str(p), parser=etree.XMLParser(recover=True, huge_tree=True)).getroot()
        fname = p.name

    boq = BoQ()
    ns = root.tag.split("}", 1)[0].strip("{") if "}" in root.tag else ""
    m = re.search(r"DA(\d{2})", ns) or re.search(r"[XxDd](8\d)$", Path(fname).suffix if fname else "")
    if m:
        boq.phase = m.group(1)

    prj = _find_desc(root, "PrjInfo")
    if prj is not None:
        boq.project = _rich_text(_child(prj, "NamePrj")) or _rich_text(_child(prj, "LblPrj"))
        cur = _child(prj, "Cur")
        if cur is not None and cur.text:
            boq.currency = cur.text.strip()
    dp = _find_desc(root, "DP")
    if dp is not None and dp.text:
        boq.phase = dp.text.strip()

    boq_el = _find_desc(root, "BoQ")
    if boq_el is None:
        raise ValueError("No <BoQ> element found – is this a GAEB DA XML file?")
    info = _child(boq_el, "BoQInfo")
    if info is not None:
        boq.name = _rich_text(_child(info, "Name")) or _rich_text(_child(info, "LblTx"))
    body = _child(boq_el, "BoQBody")
    if body is not None:
        _walk_body(body, [], boq, "", "")
    return boq


# ---------------------------------------------------------------- CSV / Excel

_COLS = {
    "oz": ["oz", "pos", "position", "pos.", "ordnungszahl", "item", "nr"],
    "short_text": ["kurztext", "bezeichnung", "short text", "description", "text", "leistung"],
    "long_text": ["langtext", "long text", "beschreibung"],
    "qty": ["menge", "qty", "quantity"],
    "unit": ["einheit", "me", "unit", "eh"],
    "up": ["ep", "einheitspreis", "unit price", "up"],
    "it": ["gp", "gesamtpreis", "gesamtbetrag", "total", "it"],
}


def parse_table(path) -> BoQ:
    import pandas as pd

    p = Path(path)
    df = pd.read_excel(p) if p.suffix.lower() in (".xlsx", ".xls") else pd.read_csv(p, sep=None, engine="python")
    lower = {str(c).strip().lower(): c for c in df.columns}
    colmap = {}
    for key, names in _COLS.items():
        for n in names:
            if n in lower:
                colmap[key] = lower[n]
                break
    if "oz" not in colmap or "short_text" not in colmap:
        raise ValueError(f"Could not find OZ/Kurztext columns in {list(df.columns)}")
    boq = BoQ(name=p.stem)
    for _, row in df.iterrows():
        oz = str(row[colmap["oz"]]).strip()
        if not oz or oz.lower() == "nan":
            continue
        get = lambda k: row[colmap[k]] if k in colmap else None
        unit = get("unit")
        it = Item(
            oz=oz,
            short_text=str(get("short_text") or "").strip(),
            long_text=str(get("long_text") or "").strip() if get("long_text") is not None else "",
            qty=parse_number(get("qty")),
            unit=str(unit).strip() if unit is not None and str(unit) != "nan" else "",
            up=parse_number(get("up")),
            it=parse_number(get("it")),
        )
        it.section_oz = oz.split(".")[0]
        it.lump_sum = it.unit.lower() in ("psch", "pa", "pauschal")
        boq.items.append(it)
    return boq


def load_boq(path) -> BoQ:
    p = Path(path)
    suf = p.suffix.lower()
    if suf in (".csv", ".xlsx", ".xls", ".tsv"):
        return parse_table(p)
    if suf == ".pdf":
        from .pdf_parser import parse_pdf
        return parse_pdf(p)
    head = p.read_bytes()[:200].lstrip()
    if head.startswith(b"<") or head.startswith(b"\xef\xbb\xbf<"):
        return parse_gaeb_xml(p)
    from .gaeb90 import parse_gaeb90          # .D81/.D83/.D84/.D86 fixed-width
    return parse_gaeb90(p)
