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


# Hardened parser: no external entities, no DTD loading, no network (XXE protection for untrusted files).
def _xml_parser():
    return etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False, no_network=True, load_dtd=False)


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

    issues = []

    def num(name):
        c = _child(el, name)
        if c is None or not (c.text or "").strip():
            return None
        v = parse_number(c.text)
        if v is None:
            issues.append(f"{name}: '{c.text.strip()}'")
        return v

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
        issues=issues,
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
            add = _child(node, "AddText")
            if add is not None and _rich_text(add):
                boq.notes.append({"ref": oz, "text": _rich_text(add)})
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
                tag = _local(it.tag)
                if tag == "Item":
                    boq.items.append(_parse_item(it, prefix, section_oz, section_label))
                elif tag == "Remark":            # Hinweistext / Vorbemerkung inside the item list
                    txt = _rich_text(_first(_find_desc(it, "DetailTxt"), it))
                    if txt:
                        boq.notes.append({"ref": ".".join(prefix), "text": txt})
        elif name == "Item":
            boq.items.append(_parse_item(node, prefix, section_oz, section_label))


def parse_gaeb_xml(path_or_bytes) -> BoQ:
    if isinstance(path_or_bytes, (bytes, bytearray)):
        root = etree.fromstring(bytes(path_or_bytes), parser=_xml_parser())
        fname = ""
    else:
        p = Path(path_or_bytes)
        root = etree.parse(str(p), parser=_xml_parser()).getroot()
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

    own = _find_desc(root, "OWN")
    if own is not None:
        boq.client = " ".join(t.strip() for t in own.itertext() if t.strip())[:160]
    boq_el = _find_desc(root, "BoQ")
    if boq_el is None:
        raise ValueError("No <BoQ> element found – is this a GAEB DA XML file?")
    info = _child(boq_el, "BoQInfo")
    if info is not None:
        boq.name = _rich_text(_child(info, "Name")) or _rich_text(_child(info, "LblTx"))
        add = _child(info, "AddText")
        if add is not None and _rich_text(add):
            boq.notes.append({"ref": "LV", "text": _rich_text(add)})
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
    "up": ["ep", "einheitspreis", "unit price", "up", "rate", "ep (€)", "ep €"],
    "it": ["gp", "gesamtpreis", "gesamtbetrag", "total", "it", "amount", "gp (€)", "gp €"],
}


def parse_table(path) -> BoQ:
    import pandas as pd

    p = Path(path)
    if p.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(p)
    else:
        df = None
        for enc in ("utf-8-sig", "cp1252", "latin-1"):     # Excel writes a BOM; older tools write Windows-1252
            try:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    df = pd.read_csv(p, sep=None, engine="python", encoding=enc, dtype=str, on_bad_lines="skip",
                                     index_col=False)   # extra ";" in one row must not shift every column
                break
            except UnicodeDecodeError:
                continue
        if df is None:
            raise ValueError("unreadable text encoding")
    lower = {str(c).strip().lstrip("\ufeff").lower(): c for c in df.columns}
    colmap = {}
    for key, names in _COLS.items():
        for n in names:
            if n in lower:
                colmap[key] = lower[n]
                break
    if "oz" not in colmap or "short_text" not in colmap:
        raise ValueError(f"Could not find OZ/Kurztext columns in {list(df.columns)}")
    boq = BoQ(name=p.stem)
    sample = " ".join(str(v) for v in df.astype(str).values.ravel()[:2000])
    german = len(re.findall(r"\d,\d{2}\b", sample)) >= len(re.findall(r"\d\.\d{2}\b", sample))
    if re.search(r"Ã[¤¶¼Ÿ„–œ]|Ã\x9f", sample):
        boq.parse_info["encoding_broken"] = True        # UTF-8 read as Windows-1252: "GrÃ¼ndung"
    if p.suffix.lower() == ".csv":
        raw_txt = p.read_bytes()
        last = raw_txt.rstrip(b"\r\n").split(b"\n")[-1] if raw_txt.strip() else b""
        sep = b";" if raw_txt.count(b";") > raw_txt.count(b",") else b","
        head_n = raw_txt.split(b"\n")[0].count(sep)
        if raw_txt and not raw_txt.endswith((b"\n", b"\r")) and last.count(sep) <= head_n and \
                (last.rstrip().endswith((b",", b";")) or last.count(sep) < head_n):
            boq.parse_info["truncated"] = True          # file ends in the middle of a row
    for _, row in df.iterrows():
        oz = str(row[colmap["oz"]]).strip()
        if not oz or oz.lower() == "nan":
            txt = " ".join(str(v) for v in row.values if str(v).strip() and str(v) != "nan").strip()
            low = txt.lower()
            if any(w in low for w in ("mehrwertsteuer", "mwst", "gesamtsumme", "netto", "summe", "vat", "total")):
                from .generic_reader import _take_total, detect_format
                _take_total(boq, txt, detect_format(txt))
            elif len(txt.split()) >= 4:              # a note / preliminary remark row (contract clauses!)
                boq.notes.append({"ref": "Hinweis" if boq.items else "Vorbemerkungen", "text": txt})
            continue
        def get(k):
            if k not in colmap:
                return None
            v = row[colmap[k]]
            return None if v is None or (isinstance(v, float) and v != v) or str(v).strip() in ("", "nan", "None") else v
        unit = get("unit")
        issues = []
        for k in ("qty", "up", "it"):
            raw = get(k)
            r = str(raw).strip() if raw is not None else ""
            if r in ("", "nan", "None"):
                continue
            if re.search(r"\d[Oo]|[Oo]\d|\d[lI]\b", r):          # letter O / l instead of a digit
                issues.append(f"{k}: '{r}'")
            elif german and re.fullmatch(r"-?\d+\.\d{2}", r):        # "5.00" in a German document
                issues.append(f"fmt:{ {'qty': 'Menge', 'up': 'EP', 'it': 'GP'}[k] }: '{r}'")
            elif parse_number(raw) is None:
                issues.append(f"{k}: '{r}'")
        it = Item(
            oz=oz,
            short_text=str(get("short_text") or "").strip(),
            long_text=str(get("long_text") or "").strip() if get("long_text") is not None else "",
            qty=parse_number(get("qty")),
            unit=str(unit).strip() if unit is not None and str(unit) != "nan" else "",
            up=parse_number(get("up")),
            it=parse_number(get("it")),
            issues=issues,
        )
        it.section_oz = oz.split(".")[0]
        it.lump_sum = it.unit.lower() in ("psch", "pa", "pauschal")
        low = (it.short_text + " " + it.long_text).lower()
        it.provisional = "bedarfsposition" in low or "eventualposition" in low
        it.alternative = "wahlposition" in low or "alternativposition" in low
        boq.items.append(it)
    if boq.parse_info.get("truncated") and boq.items:
        boq.items[-1].issues.append("Zeile unvollständig (Datei abgeschnitten)")
    return boq


def load_boq(path) -> BoQ:
    p = Path(path)
    suf = p.suffix.lower()
    if suf in (".csv", ".xlsx", ".xls", ".tsv"):
        try:
            return parse_table(p)
        except ValueError:
            if suf in (".xlsx", ".xls"):
                raise
            # a title line above the header ("[Tabellenblatt: LV]"), free layout in a .csv – the layout-independent reader copes
            from .smart_reader import read_document
            b = read_document(p)
            if not b.items:
                raise
            return b
    if suf in (".pdf", ".docx", ".txt"):
        from .smart_reader import read_document
        return read_document(p)
    head = p.read_bytes()[:200].lstrip()
    if head.startswith(b"<") or head.startswith(b"\xef\xbb\xbf<"):
        return parse_gaeb_xml(p)
    from .gaeb90 import parse_gaeb90          # .D81/.D83/.D84/.D86 fixed-width
    return parse_gaeb90(p)
