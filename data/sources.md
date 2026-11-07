# Test data sources

Checked 7 Nov 2026. Every link below was opened or downloaded in this session, unless it says otherwise.
Only official sites, Wikimedia Commons and dataset publishers were used.

**Score** (1-5) = how useful the source is for testing our accessibility checks (door width first).
**Licence:** files with an unclear licence sit in `data/restricted/` and are git-ignored.

## Real drawings

| # | Name | Link | Format | Licence | Scale | Objects | Score | Why |
|---|---|---|---|---|---|---|---|---|
| 1 | **RCRV General Arrangement** (Glosten dwg 12100-070-01 rev P17, 2014, "Draft-Subject to Change"), Exhibit B of OSU RFI DLN173761I | [bid.oregonstate.edu](https://bid.oregonstate.edu/opportunity/viewFile/4812/DLN173761I%20RFI%20RCRV%20Overside%20Handling%20System%20Posted%20111814.pdf) | Vector PDF, 11 pages. Pages 6-11 are GA sheets (11x17). Text is outlined as curves, so PyMuPDF reads **no** labels from the sheets. | Public procurement document, no licence stated → `restricted/` | Yes: 1/16"=1'-0", frame spacing, deck heights | Door swing symbols, cabins, stair towers, passages, compartment numbers. **No door widths written.** | 4 | Same ship as our sample design. Good for 2D↔3D matching and vision reading, but needs page images: the app currently sends only the text layer (see report). |
| 2 | **R/V Sikuliaq General Arrangement** (dwg 0650-601-01 rev G, as-built 2014) | [UAF vessel layout page](https://ops.sikuliaq.alaska.edu/cruise-planning/vessel-layout), "General Arrangement" (Google Drive link) | Scanned PDF (6000x2550 px pages) with an OCR text layer, 8 sheets | Not stated. Site: "Copyright © 2025 University of Alaska Fairbanks" → `restricted/` | Yes: 3/32"=1'-0", principal characteristics | Door swings with door numbers (e.g. 01-16-2), passages, stairs, ladders, cabins. No door widths. | 4 | Similar research ship (also Glosten). OCR text is noisy, which is a realistic reader test. **Hand-labelled ground truth:** `ground_truth/sikuliaq_GA_0650-601-01_revG.json`. |
| 3 | **MARAD vessel history GA** (Military Sea Transportation Service ship, boat deck, bridge deck, navigating bridge) | [vesselhistory.marad.dot.gov](https://vesselhistory.marad.dot.gov/documents/0106907a-748b-4130-89e7-cac640e4caf8.pdf) | Scanned PDF, 8 pages, no text layer (13648x8990 px) | US government drawing, probably public domain, but not stated on the file → `restricted/` | Not found by the probe | Cabins, passages, doors, stairs (hand-drawn) | 2 | Old and hard to read. The app refuses it as is (8 image pages, max 6). |
| 4 | **RMS Lusitania deck plans**, recreated from builder blueprints | [Commons file page](https://commons.wikimedia.org/wiki/File:Lusitania_Deck_Plans.jpg) | JPG 12320x16109 px, 26 MB | **CC BY-SA 4.0** (Bbankhammer). Credit the author when shown. | No | Passenger cabins, corridors, stairs, public rooms | 3 | Passenger ship layout for testing room and corridor reading. No dimensions. Too big to commit, and too big for the app's image path (not resized). |
| 5 | **RMS Lusitania deck plans, 1907** (John Brown & Co., from *Engineering*) | [Commons file page](https://commons.wikimedia.org/wiki/File:Deck_plans.jpg) | JPG 961x1242 px, 220 KB | **Public domain in the US** (PD-US); may not be PD everywhere | No | Cabins, corridors | 2 | Small and legal to share. Low resolution, so only a vision smoke test. |

### Checked, not downloaded

| Name | Link | Result |
|---|---|---|
| WSF 160-auto hybrid ferry (IFB, May 2024) | [WSDOT electrification page](https://wsdot.wa.gov/projects/system-electrification/home) | The page links no GA or deck plans, only a rendering and plans. The IFB volumes weren't found on WSDOT. |
| Orkney Islands Council RoPax GA (2025) | orkney.gov.uk/media/zubjbewp/2500322011001-general-arrangement.pdf | HTTP 404 on download (found in search, moved or removed). |
| Skagit County ferry preliminary design report | skagitcounty.net/PublicWorksFerryReplacement/.../01 - Preliminary Design Report.pdf | HTTP 404 on download. |
| Bermuda Government, Annex C GA for 2 x 500-pax ferries | gov.bm/sites/default/files/Annex-C--General-Arrangements-2-x-500-Pax-Ferries.pdf | HTTP 404 on download. Worth asking for: 500-passenger ferries are in PVAG scope. |
| Sikuliaq other sheets (deck dimensions in ft and m, cargo hold) | [UAF vessel layout page](https://ops.sikuliaq.alaska.edu/cruise-planning/vessel-layout) | Available, not downloaded. Main deck dimension sheets could give stated dimensions. |
| MARAD NSMV outline specification | [maritime.dot.gov PDF](https://www.maritime.dot.gov/sites/marad.dot.gov/files/docs/national-defense/office-ship-operations/rrf/2576/nsmv-outline-specification.pdf) | Found in search, **not opened**. Has a cabin arrangement section; may have no drawings. |
| Operator deck plans (Viking Line, Tallink, etc.) | e.g. cruisemapper.com | Skipped: third-party copies of copyrighted brochures. Official operator PDFs weren't found. |

## Floor-plan datasets (buildings, labelled; for door and corridor detection)

| Name | Link | Format | Licence | Score | Why |
|---|---|---|---|---|---|
| **CubiCasa5K**: 5,000 floor plans with polygon labels (doors, walls, rooms) | [Zenodo 2613548](https://zenodo.org/records/2613548), [GitHub](https://github.com/CubiCasa/CubiCasa5k) | PNG + SVG labels, one 5.5 GB zip | **CC BY-NC-SA 4.0** (Zenodo record) | 3 | Best labelled source for door detection. Non-commercial, which is fine for a hackathon demo, and share-alike. Too big to download now: link only. |
| **FloorPlanCAD**: CAD drawings with symbol labels (including doors) | [floorplancad.github.io](https://floorplancad.github.io) | SVG with labels + PNG | Labels **CC BY-NC 4.0**. The authors **don't own the drawings' copyright** | 2 | Vector SVG is close to our vector-PDF case, but drawing rights are unclear. Use for internal testing only, don't redistribute. |

## Synthetic (ours)

| Name | Path | Format | Licence | Scale | Objects | Score |
|---|---|---|---|---|---|---|
| Seeded-error deck plans, 3 sheets | `synthetic/syn_0*.pdf` + `.truth.json` | Vector PDF with a text layer | Ours | Yes, 1:50 + scale bar | 22 doors (6 too narrow, 1 width missing, 1 conflict with a door schedule), 5 corridors, 3 ramps | 5 |

Made by `tools/make_synthetic_ga.py`. Limits come only from verified rule texts in `docs/rules` (PVAG, proposed, not in force): door ≥ 32 in (V404.2.3), walking surface ≥ 36 in (V403.5.1), ramp ≤ 1:12 (V405.2). **Always label results from these sheets as synthetic.**

## Not now (roadmap)
OCX Consortium sample models and 3docx.org: 3D structural models, not useful for accessibility tests yet. Not checked.
