"""Cross-check LV quantities against an IFC model.

- Quantity deviation > 10 %  -> VOB/B § 2 Abs. 3 (new unit price can be demanded)
- Model element without LV item -> additional work, VOB/B § 2 Abs. 6
- LV item without model element -> check model completeness / possible overtendering

Mappings are plain data (MAPPINGS below) so the team can extend them on site in minutes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import ifcopenshell
import ifcopenshell.util.element as ue

from . import knowledge as K
from .fmt import de, dep, en
from .model import BoQ, Flag
from .units import norm_unit

THRESHOLD = 0.10   # VOB/B § 2 Abs. 3
WATCH = 0.05


@dataclass
class Mapping:
    name: str
    ifc_class: str
    lv_rx: str                     # regex on LV short text
    lv_type: str                   # knowledge.WorkType key
    unit: str                      # m3 | m2 | m | St
    qto: Optional[str] = None      # quantity name, None = count
    factor: float = 1.0            # e.g. 2.0 = formwork on both wall faces
    predefined: Optional[str] = None
    material_rx: Optional[str] = None
    pset: dict = field(default_factory=dict)   # {"IsExternal": True}
    lv_exclude: Optional[str] = None
    ref_eur: float = 0.0           # fallback unit price for missing items

    @property
    def name_en(self) -> str:
        return MAPPING_EN.get(self.name, self.name)


CONCRETE = r"(?<!poren)beton|ortbeton|stahlbeton"
MASONRY = r"kalksandstein|\bks\b|ziegel|mauerwerk|hlz"

MAPPINGS: list[Mapping] = [
    Mapping("Fundamente – Beton", "IfcFooting", r"fundament", "beton", "m3", "NetVolume", ref_eur=200),
    Mapping("Bodenplatte – Beton", "IfcSlab", r"bodenplatte", "beton", "m3", "NetVolume", predefined="BASESLAB", ref_eur=190),
    Mapping("Stahlbetonwände – Beton", "IfcWall", r"w[äa]nd", "beton", "m3", "NetVolume", material_rx=CONCRETE, ref_eur=260),
    Mapping("Stahlbetonwände – Schalung", "IfcWall", r"w[äa]nd", "schalung", "m2", "NetSideArea", factor=2.0, material_rx=CONCRETE, ref_eur=40),
    Mapping("Decken – Beton", "IfcSlab", r"decke", "beton", "m3", "NetVolume", predefined="FLOOR", ref_eur=235),
    Mapping("Decken – Schalung", "IfcSlab", r"decke", "schalung", "m2", "NetArea", predefined="FLOOR", ref_eur=36),
    Mapping("Stützen – Beton", "IfcColumn", r"st[üu]tze", "beton", "m3", "NetVolume", material_rx=CONCRETE, ref_eur=420),
    Mapping("Unterzüge – Beton", "IfcBeam", r"unterz[üu]g|balken|träger", "beton", "m3", "NetVolume", material_rx=CONCRETE, ref_eur=320),
    Mapping("Unterzüge – Schalung", "IfcBeam", r"unterz[üu]g|balken|träger", "schalung", "m2", "NetVolume", factor=9.0, material_rx=CONCRETE, ref_eur=48),
    Mapping("Mauerwerk Außenwand", "IfcWall", r"au[ßs]enwand", "mauerwerk", "m2", "NetSideArea", material_rx=MASONRY,
            pset={"IsExternal": True}, ref_eur=62),
    Mapping("Mauerwerk Innenwand tragend", "IfcWall", r"innenwand", "mauerwerk", "m2", "NetSideArea", material_rx=MASONRY,
            pset={"IsExternal": False, "LoadBearing": True}, lv_exclude=r"nichttragend", ref_eur=58),
    Mapping("Mauerwerk nichttragend", "IfcWall", r"nichttragend", "mauerwerk", "m2", "NetSideArea", material_rx=r"porenbeton|gips|leicht",
            ref_eur=44),
    Mapping("Treppenläufe", "IfcStairFlight", r"treppe", "fertigteil", "St", None, ref_eur=2900),
]

_COVERED_CLASSES = {m.ifc_class for m in MAPPINGS}

MAPPING_EN = {
    "Fundamente – Beton": "Foundations – concrete", "Bodenplatte – Beton": "Ground slab – concrete",
    "Stahlbetonwände – Beton": "RC walls – concrete", "Stahlbetonwände – Schalung": "RC walls – formwork",
    "Decken – Beton": "Slabs – concrete", "Decken – Schalung": "Slabs – formwork", "Stützen – Beton": "Columns – concrete",
    "Unterzüge – Beton": "Beams – concrete", "Unterzüge – Schalung": "Beams – formwork",
    "Mauerwerk Außenwand": "Masonry external walls", "Mauerwerk Innenwand tragend": "Masonry internal load-bearing",
    "Mauerwerk nichttragend": "Masonry non-load-bearing", "Treppenläufe": "Stair flights",
}


def _qty(el, name: str) -> Optional[float]:
    for set_name, props in ue.get_psets(el, qtos_only=True).items():
        if name in props and isinstance(props[name], (int, float)):
            return float(props[name])
    return None


def _geom_qty(el, name: str) -> Optional[float]:
    """Fallback when the model carries no quantity sets: compute from geometry."""
    try:
        import ifcopenshell.geom
        import ifcopenshell.util.shape as us
        settings = ifcopenshell.geom.settings()
        shape = ifcopenshell.geom.create_shape(settings, el)
        if "Volume" in name:
            return float(us.get_volume(shape.geometry))
        if name in ("NetSideArea", "GrossSideArea"):
            return float(us.get_side_area(shape.geometry))
        if "Area" in name:
            return float(us.get_footprint_area(shape.geometry))
    except Exception:
        return None
    return None


def _pset_ok(el, wanted: dict) -> bool:
    if not wanted:
        return True
    psets = ue.get_psets(el, psets_only=True)
    merged = {}
    for p in psets.values():
        merged.update(p)
    return all(merged.get(k) == v for k, v in wanted.items())


def _material(el) -> str:
    try:
        mat = ue.get_material(el, should_skip_usage=True)
    except TypeError:
        mat = ue.get_material(el)
    if mat is None:
        return ""
    names = []
    for attr in ("Name",):
        if hasattr(mat, attr) and getattr(mat, attr):
            names.append(getattr(mat, attr))
    for m in ue.get_materials(el) if hasattr(ue, "get_materials") else []:
        if getattr(m, "Name", None):
            names.append(m.Name)
    return " ".join(names)


def model_quantities(model) -> list[dict]:
    rows = []
    for mp in MAPPINGS:
        els = []
        for el in model.by_type(mp.ifc_class):
            if mp.predefined and (ue.get_predefined_type(el) or "").upper() != mp.predefined:
                continue
            if mp.material_rx and not re.search(mp.material_rx, _material(el), re.IGNORECASE):
                continue
            if not _pset_ok(el, mp.pset):
                continue
            els.append(el)
        if mp.qto is None:
            total, missing = float(len(els)), 0
        else:
            total, missing = 0.0, 0
            for el in els:
                v = _qty(el, mp.qto)
                if v is None:
                    v = _geom_qty(el, mp.qto)
                if v is None:
                    missing += 1
                    continue
                total += v * mp.factor
        rows.append({"mapping": mp, "elements": len(els), "model_qty": total, "no_qty": missing})
    return rows


def _lv_items(boq: BoQ, mp: Mapping):
    out = []
    for it in boq.items:
        if it.provisional or it.alternative:
            continue
        wt = K.classify(it.short_text, it.long_text)
        if not wt or wt.key != mp.lv_type:
            continue
        if norm_unit(it.unit) != mp.unit:
            continue
        st = it.short_text.lower()
        if not re.search(mp.lv_rx, st):
            continue
        if mp.lv_exclude and re.search(mp.lv_exclude, st):
            continue
        out.append(it)
    return out


def check_ifc(boq: BoQ, ifc_path_or_model) -> tuple[list[Flag], list[dict]]:
    model = ifc_path_or_model if isinstance(ifc_path_or_model, ifcopenshell.file) else ifcopenshell.open(str(ifc_path_or_model))
    flags: list[Flag] = []
    table: list[dict] = []
    for row in model_quantities(model):
        mp: Mapping = row["mapping"]
        items = _lv_items(boq, mp)
        lv_qty = sum((i.qty or 0) for i in items)
        model_qty = row["model_qty"]
        ozs = ", ".join(i.oz for i in items)
        ups = [i.up for i in items if i.up]
        up = sum(ups) / len(ups) if ups else mp.ref_eur
        status = "ok"
        dev = None
        if row["elements"] == 0 and not items:
            continue
        if items and lv_qty > 0 and model_qty > 0:
            dev = (model_qty - lv_qty) / lv_qty
            if abs(dev) > THRESHOLD:
                status = "deviation"
                direction = "Mehrmenge" if dev > 0 else "Mindermenge"
                flags.append(Flag(
                    "R14", f"Mengenabweichung Modell ↔ LV: {mp.name}", "high",
                    f"Modell: {de(model_qty, 1)} {mp.unit} ({row['elements']} Bauteile) – LV: {de(lv_qty, 1)} {mp.unit} (OZ {ozs}). "
                    f"{direction} {dep(dev, 1)}. Über 10 % kann ein neuer Einheitspreis verlangt werden.",
                    oz=items[0].oz, reference="VOB/B § 2 Abs. 3 (Mengenabweichung > 10 %)",
                    exposure_eur=abs(model_qty - lv_qty) * up,
                    suggestion=f"Vordersatz auf {de(model_qty, 1)} {mp.unit} anpassen oder Abweichung im Modell klären.",
                    source="ifc", en=dict(title=f"Quantity deviation model ↔ BoQ: {mp.name_en}", message=f"Model: {en(model_qty, 1)} {mp.unit} ({row['elements']} elements) – BoQ: {en(lv_qty, 1)} {mp.unit} (items {ozs}). {'Extra' if dev > 0 else 'Reduced'} quantity {dev:+.1%}. Above 10 % a new unit price can be demanded.", suggestion=f"Change the quantity to {en(model_qty, 1)} {mp.unit} or resolve the deviation in the model.")))
            elif abs(dev) > WATCH:
                status = "watch"
        elif not items and model_qty > 0:
            status = "missing_in_lv"
            flags.append(Flag(
                "R15", f"Im Modell, aber nicht im LV: {mp.name}", "high",
                f"{row['elements']} Bauteile ({de(model_qty, 1)} {mp.unit}) im IFC-Modell, aber keine passende LV-Position. "
                "Wird gebaut, aber nicht ausgeschrieben → zusätzliche Leistung.",
                reference="VOB/B § 2 Abs. 6 (zusätzliche Leistung); VOB/B § 1 Abs. 4",
                exposure_eur=model_qty * up,
                suggestion=f"Position „{mp.name}“ ({mp.unit}) ergänzen, Menge {de(model_qty, 1)} {mp.unit}.",
                source="ifc", en=dict(title=f"In the model but not in the BoQ: {mp.name_en}", message=f"{row['elements']} elements ({en(model_qty, 1)} {mp.unit}) in the IFC model, but no matching BoQ item. It will be built but is not tendered → additional work.", suggestion=f"Add an item '{mp.name_en}' ({mp.unit}), quantity {en(model_qty, 1)} {mp.unit}.")))
        elif items and model_qty == 0:
            status = "missing_in_model"
            flags.append(Flag(
                "R16", f"Im LV, aber nicht im Modell: {mp.name}", "low",
                f"LV-Positionen {ozs} ({de(lv_qty, 1)} {mp.unit}) haben kein Gegenstück im Modell – Modellstand oder Mengenansatz prüfen.",
                oz=items[0].oz, reference="Mengenermittlung (VOB/A § 7 Abs. 1)", source="ifc", en=dict(title=f"In the BoQ but not in the model: {mp.name_en}", message=f"BoQ items {ozs} ({en(lv_qty, 1)} {mp.unit}) have no counterpart in the model – check the model status or the quantity.")))
        if row["no_qty"]:
            flags.append(Flag("R17", f"Bauteile ohne Mengenangabe: {mp.name}", "low",
                              f"{row['no_qty']} Bauteile ohne {mp.qto} und ohne auswertbare Geometrie.", source="ifc", en=dict(title=f"Elements without quantities: {mp.name_en}", message=f"{row['no_qty']} elements without {mp.qto} and without usable geometry.")))
        table.append({"Prüfgruppe": mp.name, "Bauteile": row["elements"], "Modell": round(model_qty, 2),
                      "LV": round(lv_qty, 2), "Einheit": mp.unit, "Abweichung": None if dev is None else round(dev, 4),
                      "OZ": ozs, "Status": status})

    # transparency: element classes in the model that no rule covers yet
    uncovered = {}
    for el in model.by_type("IfcBuiltElement") if model.schema != "IFC2X3" and _has(model, "IfcBuiltElement") else model.by_type("IfcBuildingElement"):
        if el.is_a() not in _COVERED_CLASSES:
            uncovered[el.is_a()] = uncovered.get(el.is_a(), 0) + 1
    if uncovered:
        flags.append(Flag("R18", "Bauteilklassen ohne Prüfregel", "info",
                          ", ".join(f"{k} ({v})" for k, v in sorted(uncovered.items())), source="ifc", en=dict(title="Element classes without a check rule", message=", ".join(f"{k} ({v})" for k, v in sorted(uncovered.items())))))
    return flags, table


def _has(model, cls):
    try:
        model.by_type(cls)
        return True
    except Exception:
        return False
