"""Minimal GAEB DA XML 3.3 writer (X83 tender / X84 bid). Used for sample data and corrected exports."""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from lxml import etree

from .model import BoQ, Item


def _ns(phase: str) -> str:
    return f"http://www.gaeb.de/GAEB_DA_XML/DA{phase}/3.3"


def _txt(parent, tag, text, ns):
    el = etree.SubElement(parent, f"{{{ns}}}{tag}")
    el.text = text
    return el


def _rich(parent, tag, text, ns):
    el = etree.SubElement(parent, f"{{{ns}}}{tag}")
    for line in (text or "").split("\n"):
        p = etree.SubElement(el, f"{{{ns}}}p")
        s = etree.SubElement(p, f"{{{ns}}}span")
        s.text = line
    return el


def _fmt(v, nd=3):
    return f"{v:.{nd}f}"


def write_gaeb(boq: BoQ, path, phase: str = "84") -> Path:
    ns = _ns(phase)
    root = etree.Element(f"{{{ns}}}GAEB", nsmap={None: ns})
    info = etree.SubElement(root, f"{{{ns}}}GAEBInfo")
    _txt(info, "Version", "3.3", ns)
    _txt(info, "VersDate", "2021-05", ns)
    _txt(info, "Date", _dt.date.today().isoformat(), ns)
    _txt(info, "ProgSystem", "OpenBoQ", ns)

    prj = etree.SubElement(root, f"{{{ns}}}PrjInfo")
    _txt(prj, "NamePrj", boq.project or "Projekt", ns)
    _txt(prj, "LblPrj", boq.project or "Projekt", ns)
    _txt(prj, "Cur", boq.currency, ns)
    _txt(prj, "CurLbl", "Euro", ns)

    award = etree.SubElement(root, f"{{{ns}}}Award")
    _txt(award, "DP", phase, ns)
    boq_el = etree.SubElement(award, f"{{{ns}}}BoQ", ID="BoQ1")
    binfo = etree.SubElement(boq_el, f"{{{ns}}}BoQInfo")
    _txt(binfo, "Name", boq.name or "LV", ns)
    _rich(binfo, "LblTx", boq.name or "LV", ns)
    for t, length in (("BoQLevel", 2), ("BoQLevel", 2), ("Item", 4)):
        bk = etree.SubElement(binfo, f"{{{ns}}}BoQBkdn")
        _txt(bk, "Type", t, ns)
        _txt(bk, "Length", str(length), ns)
        _txt(bk, "Num", "Yes", ns)
    body = etree.SubElement(boq_el, f"{{{ns}}}BoQBody")

    # group items by OZ prefix (all but last part)
    ctgy_bodies: dict[str, etree._Element] = {"": body}

    def get_body(prefix_parts: list[str]):
        key = ".".join(prefix_parts)
        if key in ctgy_bodies:
            return ctgy_bodies[key]
        parent = get_body(prefix_parts[:-1])
        ctgy = etree.SubElement(parent, f"{{{ns}}}BoQCtgy", ID=f"C{key.replace('.', '_')}", RNoPart=prefix_parts[-1])
        _rich(ctgy, "LblTx", boq.sections.get(key, key), ns)
        sub = etree.SubElement(ctgy, f"{{{ns}}}BoQBody")
        ctgy_bodies[key] = sub
        return sub

    itemlists: dict[str, etree._Element] = {}
    for n, it in enumerate(boq.items):
        parts = it.oz.split(".")
        prefix, rno = parts[:-1], parts[-1]
        key = ".".join(prefix)
        if key not in itemlists:
            itemlists[key] = etree.SubElement(get_body(prefix), f"{{{ns}}}Itemlist")
        item_el = etree.SubElement(itemlists[key], f"{{{ns}}}Item", ID=it.raw_id or f"I{n+1}", RNoPart=rno)
        if it.provisional:
            _txt(item_el, "Provis", "WithoutTotal", ns)
        if it.alternative:
            _txt(item_el, "ALNGroupNo", "1", ns)
            _txt(item_el, "ALNSerNo", "1", ns)
        if it.lump_sum:
            _txt(item_el, "LumpSumItem", "Yes", ns)
        if it.qty_tbd:
            _txt(item_el, "QtyTBD", "Yes", ns)
        if it.qty is not None:
            _txt(item_el, "Qty", _fmt(it.qty), ns)
        _txt(item_el, "QU", it.unit, ns)
        if phase in ("84", "86") and it.up is not None:
            _txt(item_el, "UP", _fmt(it.up, 2), ns)
            _txt(item_el, "IT", _fmt(it.it if it.it is not None else it.qty * it.up, 2), ns)
        desc = etree.SubElement(item_el, f"{{{ns}}}Description")
        ct = etree.SubElement(desc, f"{{{ns}}}CompleteText")
        dt = etree.SubElement(ct, f"{{{ns}}}DetailTxt")
        _rich(dt, "Text", it.long_text, ns)
        ot = etree.SubElement(ct, f"{{{ns}}}OutlineText")
        ol = etree.SubElement(ot, f"{{{ns}}}OutlTxt")
        _rich(ol, "TextOutlTxt", it.short_text, ns)

    out = Path(path)
    out.write_bytes(etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True))
    return out
