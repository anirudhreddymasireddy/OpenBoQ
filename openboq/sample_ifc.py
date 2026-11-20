"""Generate a small IFC4 model matching the sample LV – with a few deliberate deviations
(the kind that cause change orders): more footing/slab/masonry quantity than tendered,
and concrete beams (Unterzüge) that have no LV item at all."""
from __future__ import annotations

from pathlib import Path

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.material
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit

QTO_SET = {
    "IfcFooting": "Qto_FootingBaseQuantities",
    "IfcSlab": "Qto_SlabBaseQuantities",
    "IfcWall": "Qto_WallBaseQuantities",
    "IfcColumn": "Qto_ColumnBaseQuantities",
    "IfcBeam": "Qto_BeamBaseQuantities",
    "IfcStairFlight": "Qto_StairFlightBaseQuantities",
}


def make_sample_ifc(path) -> Path:
    m = ifcopenshell.api.project.create_file(version="IFC4")
    project = ifcopenshell.api.root.create_entity(m, ifc_class="IfcProject", name="Neubau MFH Am Lindenpark")
    ifcopenshell.api.unit.assign_unit(m)
    ifcopenshell.api.context.add_context(m, context_type="Model")
    site = ifcopenshell.api.root.create_entity(m, ifc_class="IfcSite", name="Grundstück")
    building = ifcopenshell.api.root.create_entity(m, ifc_class="IfcBuilding", name="Haus A")
    ifcopenshell.api.aggregate.assign_object(m, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(m, products=[building], relating_object=site)
    storeys = {}
    for i, name in enumerate(["UG", "EG", "OG1", "OG2", "DG"]):
        st = ifcopenshell.api.root.create_entity(m, ifc_class="IfcBuildingStorey", name=name)
        ifcopenshell.api.aggregate.assign_object(m, products=[st], relating_object=building)
        storeys[name] = st

    mats = {}

    def mat(name):
        if name not in mats:
            mats[name] = ifcopenshell.api.material.add_material(m, name=name)
        return mats[name]

    def element(cls, name, storey, material, qtos, predefined=None, pset=None):
        el = ifcopenshell.api.root.create_entity(m, ifc_class=cls, name=name, predefined_type=predefined)
        ifcopenshell.api.spatial.assign_container(m, products=[el], relating_structure=storeys[storey])
        ifcopenshell.api.material.assign_material(m, products=[el], type="IfcMaterial", material=mat(material))
        q = ifcopenshell.api.pset.add_qto(m, product=el, name=QTO_SET[cls])
        ifcopenshell.api.pset.edit_qto(m, qto=q, properties=qtos)
        if pset:
            ps = ifcopenshell.api.pset.add_pset(m, product=el, name=pset[0])
            ifcopenshell.api.pset.edit_pset(m, pset=ps, properties=pset[1])
        return el

    # Footings: 96 m³ in the model vs 85 m³ tendered (+13 %)
    for k in range(8):
        element("IfcFooting", f"Streifenfundament {k+1}", "UG", "Stahlbeton C25/30", {"NetVolume": 12.0}, "STRIP_FOOTING")
    # Base slab: 131 m³ vs 130 (ok)
    element("IfcSlab", "Bodenplatte", "UG", "Stahlbeton C30/37 WU", {"NetVolume": 131.0, "NetArea": 524.0}, "BASESLAB")
    # Basement walls: 96.5 m³ vs 96 (ok); side area 402 m² -> formwork 804 m² vs 800 (ok)
    for k in range(8):
        element("IfcWall", f"UG Außenwand {k+1}", "UG", "Stahlbeton C30/37 WU",
                {"NetVolume": 96.5 / 8, "NetSideArea": 402.0 / 8}, "SOLIDWALL",
                ("Pset_WallCommon", {"IsExternal": True, "LoadBearing": True}))
    # Floor slabs: 238 m³ vs 210 (+13 %); soffit 1190 m² vs 1050 m² formwork (+13 %)
    for st in ["EG", "OG1", "OG2", "DG"]:
        element("IfcSlab", f"Decke über {st}", st, "Stahlbeton C25/30", {"NetVolume": 59.5, "NetArea": 297.5}, "FLOOR")
    # Columns: 6.4 m³ vs 6.5 (ok)
    for k in range(27):
        element("IfcColumn", f"Stütze {k+1}", "UG" if k < 9 else "EG", "Stahlbeton C30/37", {"NetVolume": 6.4 / 27})
    # Beams (Unterzüge): 14.4 m³ – NOT in the LV  -> missing item
    for k in range(6):
        element("IfcBeam", f"Unterzug {k+1}", "EG", "Stahlbeton C30/37", {"NetVolume": 2.4})
    # External masonry: 1180 m² vs 1250 (-5.6 %, within tolerance)
    for st in ["EG", "OG1", "OG2", "DG"]:
        element("IfcWall", f"Außenwand KS {st}", st, "Kalksandstein KS 20-2,0", {"NetSideArea": 295.0, "NetVolume": 295.0 * 0.175},
                "SOLIDWALL", ("Pset_WallCommon", {"IsExternal": True, "LoadBearing": True}))
    # Internal load-bearing masonry: 1120 m² vs 980 (+14 %)
    for st in ["EG", "OG1", "OG2", "DG"]:
        element("IfcWall", f"Innenwand tragend KS {st}", st, "Kalksandstein KS 20-2,0", {"NetSideArea": 280.0, "NetVolume": 280.0 * 0.175},
                "SOLIDWALL", ("Pset_WallCommon", {"IsExternal": False, "LoadBearing": True}))
    # Non-load-bearing: 655 m² vs 640 (ok)
    for st in ["EG", "OG1", "OG2", "DG"]:
        element("IfcWall", f"Innenwand nichttragend {st}", st, "Porenbeton PP2-0,40", {"NetSideArea": 655.0 / 4, "NetVolume": 655.0 / 4 * 0.115},
                "PARTITIONING", ("Pset_WallCommon", {"IsExternal": False, "LoadBearing": False}))
    # Stair flights: 4 vs 4
    for st in ["EG", "OG1", "OG2", "DG"]:
        element("IfcStairFlight", f"Treppenlauf {st}", st, "Stahlbeton C30/37 Fertigteil", {"NetVolume": 1.1}, "STRAIGHT")

    out = Path(path)
    m.write(str(out))
    return out
