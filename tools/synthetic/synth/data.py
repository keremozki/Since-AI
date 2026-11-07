"""Ground-truth values for the synthetic SYN-1 package: the single source for every file."""

PACKAGE = "meyer-style-v1"
SEED = 701
GENERATED = "2026-11-07"  # fixed so the output is reproducible
SYNTH = "SYNTHETIC TEST DATA: not a real ship"
SHIP_NAME = "SYN-1 (synthetic cruise ship)"
HULL = "S-701"
YARD = "SYNTHETIC YARD (INVENTED)"

# Ship values: key -> (value, unit). These are the truth.
SHIP = {
    "ship_type": ("passenger", ""),
    "voyage_type": ("international, not short", ""),
    "flag": ("Malta", ""),
    "contract_date": ("2025-03-01", "date"),
    "keel_date": ("2027-02-15", "date"),
    "delivery_date": ("2029-05-30", "date"),
    "length_overall": (299.80, "m"),
    "length_between_perpendiculars": (271.00, "m"),
    "beam": (37.00, "m"),
    "breadth_greatest": (37.40, "m"),
    "depth": (21.50, "m"),
    "design_draft": (8.40, "m"),
    "gross_tonnage": (141500, "GT"),
    "frame_spacing": (800, "mm"),
    "main_vertical_zones": (7, ""),
    "passengers": (3300, "persons"),
    "crew_complement": (1450, "persons"),
    "persons_on_board": (4750, "persons"),
}
GA_LOA = 300.10  # planted conflict P-LOA: the GA particulars box disagrees with the spec

LIFEBOATS = {"port": (7, 350), "starboard": (7, 350)}  # count, persons each
LIFERAFTS = 16  # davit-launched, capacity deliberately not stated (P-RAFT-CAP)

EVAC = {  # EA-101
    "rt": 38.0, "el": 30.0, "total": 67.5, "case": "Case 1 (night)",
    "case2": {"name": "Case 2 (day)", "rt": 35.0, "el": 29.0, "total": 63.1},
}
EVAC_LIMIT_MIN = 80.0  # more than 3 main vertical zones; not printed in EA-101

# Frames: FR 100 is x = 0 on the plan; frame spacing 0.8 m.
FR0, FR1, FSP = 100, 160, 0.8

# Doors: no, clear width mm (None = blank), opening depth mm (None = not stated),
# accessible route, IFC clear width override, schedule/layout details.
DOORS = [
    dict(no=5101, clear=900, depth=150, acc=True, kind="cab_out", side="P", cs=108,
         loc="ACCESSIBLE CABIN, PORT OUTBOARD", typ="SINGLE HINGED", fire="B-15"),
    dict(no=5102, clear=850, depth=150, acc=True, kind="cab_out", side="P", cs=116,
         loc="ACCESSIBLE CABIN, PORT OUTBOARD", typ="SINGLE HINGED", fire="B-15"),
    dict(no=5103, clear=815, depth=150, acc=True, kind="cab_out", side="P", cs=124,
         loc="ACCESSIBLE CABIN, PORT OUTBOARD", typ="SINGLE HINGED", fire="B-15"),
    dict(no=5104, clear=900, depth=700, acc=True, kind="cab_in", side="P", cs=132,
         loc="ACCESSIBLE CABIN, PORT INBOARD", typ="SINGLE HINGED", fire="B-15"),
    dict(no=5105, clear=920, depth=700, acc=True, kind="cab_in", side="P", cs=140,
         loc="ACCESSIBLE CABIN, PORT INBOARD", typ="SINGLE HINGED", fire="B-15"),
    dict(no=5106, clear=750, depth=150, acc=False, kind="store", side="P", cs=None,
         loc="CREW STORE, PORT CORE", typ="SINGLE HINGED", fire="A-0"),
    dict(no=5107, clear=800, depth=150, acc=True, kind="cab_out", side="S", cs=112,
         loc="ACCESSIBLE CABIN, STBD OUTBOARD", typ="SINGLE HINGED", fire="B-15"),
    dict(no=5108, clear=None, depth=150, acc=True, kind="cab_out", side="S", cs=120,
         loc="ACCESSIBLE CABIN, STBD OUTBOARD", typ="SINGLE HINGED", fire="B-15"),
    dict(no=5109, clear=860, depth=150, acc=True, kind="zone", side="P", fr=100,
         loc="PORT CORRIDOR AT FR 100 (MVZ 2/3)", typ="HINGED FIRE DOOR", fire="A-60"),
    dict(no=5110, clear=1000, depth=150, acc=True, kind="zone", side="P", fr=160, ifc_clear=900,
         loc="PORT CORRIDOR AT FR 160 (MVZ 3/4)", typ="HINGED FIRE DOOR", fire="A-60"),
    dict(no=5111, clear=870, depth=150, acc=True, kind="zone", side="S", fr=100,
         loc="STBD CORRIDOR AT FR 100 (MVZ 2/3)", typ="HINGED FIRE DOOR", fire="A-60"),
    dict(no=5112, clear=880, depth=None, acc=True, kind="zone", side="S", fr=160,
         loc="STBD CORRIDOR AT FR 160 (MVZ 3/4)", typ="HINGED FIRE DOOR", fire="A-60"),
]
CAB_W = 4 * FSP  # cabin width, m (4 frames)

# Stairs on deck 5: clear width mm per source, persons served, enclosure start (m from FR 100)
STAIRS = {
    "A": dict(clear=1200, persons=110, side="P", x0=1.6, ga=1200, ifc=1200),
    "B": dict(clear=850, persons=95, side="S", x0=19.2, ga=850, ifc=850, ga_b=1000),
    "C": dict(clear=1000, persons=80, side="P", x0=36.8, ga=1000, ifc=950),
}
ENC_LEN, ENC_DEPTH = 9.6, 3.2  # stair enclosure, m
CORE_Y, PASS_Y = 4.4, 1.2  # core half-width and passage half-width, m
STAIR_DECK, STAIR_MVZ = 5, 3

# Drawing identity
GA = dict(no="SYN-GA-105", title="GENERAL ARRANGEMENT DECK 5 (MVZ 3)", size="A3",
          scale_note="1:100", scale_drawn="1:200",
          revs={"A": ("2026-10-01", "FIRST ISSUE"),
                "B": ("2026-11-01", "STAIR B WIDENED TO 1000 MM CLEAR")})


def door_xy(d):
    """Door centre as (x m from FR 100, y m, port positive)."""
    w = (d["clear"] or 900) / 1000
    sg = 1 if d["side"] == "P" else -1
    if d["kind"] == "zone":
        return (d["fr"] - FR0) * FSP, sg * 10.0
    if d["kind"] == "store":
        return 18.4, PASS_Y
    wall = 11.0 if d["kind"] == "cab_out" else 9.0
    return (d["cs"] - FR0) * FSP + 0.4 + w / 2, sg * wall


def door_fr(d):
    return FR0 + door_xy(d)[0] / FSP


def stair_flight(name, rev="A"):
    """Stair flight clear width in the GA for this revision (mm)."""
    s = STAIRS[name]
    return s.get("ga_b", s["ga"]) if rev == "B" else s["ga"]


def fss_required(persons):
    """FSS Code ch. 13: 900 mm up to 90 persons, +10 mm per extra person."""
    return 900 + 10 * max(0, persons - 90)
