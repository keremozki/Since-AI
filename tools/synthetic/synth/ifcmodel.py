"""IFC4 model of deck 5: 12 doors and 3 stair flights with the yard property sets (project unit: mm)."""
import contextlib
import random

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import ifcopenshell.guid

from . import data as D

DECK_Z = 15000.0  # deck 5 elevation, mm
FRAME_ORIGIN_MM = D.FR0 * D.FSP * 1000  # FR 100 measured from the aft perpendicular


@contextlib.contextmanager
def fixed_guids(seed):
    """Make GUIDs reproducible."""
    rng = random.Random(seed)
    orig = ifcopenshell.guid.new
    ifcopenshell.guid.new = lambda: ifcopenshell.guid.compress(f"{rng.getrandbits(128):032x}")
    try:
        yield
    finally:
        ifcopenshell.guid.new = orig


def place(m, product, x_mm, y_mm):
    """Place a product at a point on the deck (project units, mm)."""
    axis = m.createIfcAxis2Placement3D(m.createIfcCartesianPoint((float(x_mm), float(y_mm), DECK_Z)))
    product.ObjectPlacement = m.createIfcLocalPlacement(None, axis)


def length(m, v):
    return m.create_entity("IfcLengthMeasure", float(v))


def build(path):
    with fixed_guids(D.SEED):
        m = ifcopenshell.api.project.create_file(version="IFC4")
        m.header.file_description.description = (D.SYNTH,)
        m.header.file_name.name = "model.ifc"
        m.header.file_name.time_stamp = "2026-10-01T00:00:00"
        m.header.file_name.author = ("synthetic generator",)
        m.header.file_name.organization = (D.YARD,)
        project = ifcopenshell.api.root.create_entity(m, ifc_class="IfcProject", name=f"{D.SHIP_NAME} hull {D.HULL}")
        project.Description = D.SYNTH
        ifcopenshell.api.unit.assign_unit(m, length={"is_metric": True, "raw": "MILLIMETERS"})
        units = m.by_type("IfcUnitAssignment")[0]
        units.Units = sorted(units.Units, key=lambda u: u.id())  # the API leaves the order to a set
        model_ctx = ifcopenshell.api.context.add_context(m, context_type="Model")
        body = ifcopenshell.api.context.add_context(m, context_type="Model", context_identifier="Body",
                                                    target_view="MODEL_VIEW", parent=model_ctx)
        site = ifcopenshell.api.root.create_entity(m, ifc_class="IfcSite", name="SYN SHIPYARD SITE")
        building = ifcopenshell.api.root.create_entity(m, ifc_class="IfcBuilding", name="SYN-1")
        building.Description = D.SYNTH
        storey = ifcopenshell.api.root.create_entity(m, ifc_class="IfcBuildingStorey", name="DECK 5")
        storey.Elevation = DECK_Z
        ifcopenshell.api.aggregate.assign_object(m, products=[site], relating_object=project)
        ifcopenshell.api.aggregate.assign_object(m, products=[building], relating_object=site)
        ifcopenshell.api.aggregate.assign_object(m, products=[storey], relating_object=building)
        elements = []
        for d in D.DOORS:
            clear = d.get("ifc_clear", d["clear"])
            door = ifcopenshell.api.root.create_entity(m, ifc_class="IfcDoor", name=str(d["no"]))
            door.Description = d["loc"]
            door.OverallHeight = 2000.0
            width = (clear or 900) / 1000  # no clear width in the model: 5108 gets no OverallWidth either
            if clear is not None:
                door.OverallWidth = float(clear + 100)  # frame opening, deliberately not the clear width
            door.Representation = ifcopenshell.api.geometry.add_wall_representation(
                m, context=body, length=width + 0.1, height=2.0, thickness=(d["depth"] or 150) / 1000)
            x, y = D.door_xy(d)
            place(m, door, FRAME_ORIGIN_MM + x * 1000, y * 1000)
            props = {"AccessibleRoute": "Yes" if d["acc"] else "No"}
            if clear is not None:
                props["ClearWidth"] = length(m, clear)
            if d["depth"] is not None:
                props["OpeningDepth"] = length(m, d["depth"])
            pset = ifcopenshell.api.pset.add_pset(m, product=door, name="SYN_DoorData")
            ifcopenshell.api.pset.edit_pset(m, pset=pset, properties=props)
            fire = ifcopenshell.api.pset.add_pset(m, product=door, name="Pset_DoorCommon")
            ifcopenshell.api.pset.edit_pset(m, pset=fire, properties={"FireRating": d["fire"]})
            elements.append(door)
        for name, s in D.STAIRS.items():
            flight = ifcopenshell.api.root.create_entity(m, ifc_class="IfcStairFlight", name=f"STAIR {name}")
            flight.NumberOfRisers, flight.NumberOfTreads = 22, 21
            flight.RiserHeight, flight.TreadLength = 3000 / 22, 280.0
            sg = 1 if s["side"] == "P" else -1
            flight.Representation = ifcopenshell.api.geometry.add_wall_representation(
                m, context=body, length=6.2, height=3.0, thickness=s["ifc"] / 1000)
            place(m, flight, FRAME_ORIGIN_MM + (s["x0"] + 3.2) * 1000, sg * (1400 + s["ifc"] / 2))
            pset = ifcopenshell.api.pset.add_pset(m, product=flight, name="SYN_EscapeData")
            ifcopenshell.api.pset.edit_pset(m, pset=pset, properties={
                "ClearWidth": length(m, s["ifc"]), "PersonsServed": m.create_entity("IfcInteger", s["persons"])})
            elements.append(flight)
        for e in elements:  # one by one: the API walks a set when given a list
            ifcopenshell.api.spatial.assign_container(m, products=[e], relating_structure=storey)
        rel = m.by_type("IfcRelContainedInSpatialStructure")[0]
        rel.RelatedElements = sorted(rel.RelatedElements, key=lambda e: e.id())
        m.write(path)
