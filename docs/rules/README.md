# Rule data for the Meyer Turku compliance checker (Since AI Hackathon 2026)

Rules collected from the official sources in scope: **COLREG** (International Rules + International Annexes), **PVAG** (proposed), **ADA 2010 Standards** (requested subset), **DNV** (not retrieved).
Every rule is one fenced YAML block with the fields of the build-brief schema. Every verbatim_quote and exceptions text was checked word for word against the saved source text (0 failures, see "Verification").

## Sources, editions, status

| source | edition used | publisher / URL | retrieved | legal status |
|---|---|---|---|---|
| COLREG | 72 COLREGS International Rules 1-38 + Annexes I-IV as printed in the USCG Navigation Rules and Regulations Handbook, corrected 8 August 2024; Part F (Rules 39-41) from the USCG Amalgamated Navigation Rules page (last changed 08/21/2024). **Not the IMO consolidated edition.** | U.S. Coast Guard: https://www.navcen.uscg.gov/sites/default/files/pdf/navRules/Handbook/NavRules_Handbook_Corrected_08_08_2024.pdf ; https://navcen.uscg.gov/navigation-rules-amalgamated | 2026-11-06 | in force (international convention); text is a USCG rendering |
| PVAG | Proposed rule (NPRM) 78 FR 38102, 25 June 2013, 36 CFR Part 1196, RIN 3014-AA11 (+ correction 78 FR 39649) | U.S. Access Board: https://www.access-board.gov/pvag/ch-v1/ ... ch-v11/ | 2026-11-06 | **PROPOSED, not in force** (no final rule found, checked 2026-11-06) |
| ADA | 2010 ADA Standards for Accessible Design (DOJ, 15 September 2010) | U.S. DOJ: https://www.ada.gov/law-and-regs/design-standards/2010-stds/ | 2026-11-06 | in force for facilities under ADA titles II/III; applicability to vessels not stated in source |
| DNV | **NOT RETRIEVED** (Explorer requires Veracity login: HTTP 401; rules.dnv.com is a JavaScript-only app) | https://www.dnv.com/rules-standards/ | 2026-11-06 | n/a |

Details and checksums: rules/_sources/<source>/SOURCE.md.

## Counts

Total rules: **1375** (PVAG 839, ADA 282, COLREG 254, DNV 0).
Unassigned rules: **385**. Rules with verified: false: **274** (listed at the end of this file).

### Per ship type (folder)
| ship type | ADA | COLREG | PVAG | DNV | total |
|---|---|---|---|---|---|
| all-ship-types | 0 | 158 | 832 | 0 | 990 |
| ferry | 0 | 0 | 0 | 0 | 0 |
| cruise-ship | 0 | 0 | 0 | 0 | 0 |
| fast-ferry | 0 | 0 | 0 | 0 | 0 |
| unassigned | 282 | 96 | 7 | 0 | 385 |

The folders ferry/, cruise-ship/ and fast-ferry/ are empty: no rule in the retrieved sources states its applicability using one of these three types
(PVAG scopes by "Large vessels"/"Ferries" with passenger counts and both get the same Chapters V1-V10; COLREG uses its own vessel categories). See the mapping table below.

### Per discipline
| discipline | ADA | COLREG | PVAG | DNV | total |
|---|---|---|---|---|---|
| design and arrangement | 0 | 0 | 0 | 0 | 0 |
| hull and structure | 0 | 0 | 0 | 0 | 0 |
| machinery | 0 | 0 | 0 | 0 | 0 |
| electrical | 0 | 0 | 0 | 0 | 0 |
| fire safety | 0 | 0 | 0 | 0 | 0 |
| navigation and lights | 0 | 245 | 0 | 0 | 245 |
| lifesaving | 0 | 0 | 0 | 0 | 0 |
| accessibility | 282 | 0 | 839 | 0 | 1121 |
| other | 0 | 9 | 0 | 0 | 9 |

### Per source / folder / discipline
| source | ship-type folder | discipline | rules |
|---|---|---|---|
| ADA | unassigned | accessibility | 282 |
| COLREG | all-ship-types | navigation and lights | 158 |
| COLREG | unassigned | navigation and lights | 87 |
| COLREG | unassigned | other | 9 |
| PVAG | all-ship-types | accessibility | 832 |
| PVAG | unassigned | accessibility | 7 |

### Checkable and verified
| source | measurable | qualitative | verified: true | verified: false |
|---|---|---|---|---|
| PVAG | 256 | 583 | 673 | 166 |
| ADA | 61 | 221 | 243 | 39 |
| COLREG | 44 | 210 | 185 | 69 |

## Files
| file | rules |
|---|---|
| ada/unassigned/accessibility.md | 282 |
| colreg/all-ship-types/navigation-lights.md | 158 |
| colreg/unassigned/navigation-lights.md | 87 |
| colreg/unassigned/other.md | 9 |
| pvag/all-ship-types/accessibility.md | 832 |
| pvag/unassigned/accessibility.md | 7 |

Other files:
- rules/rules-master.md: all rule files concatenated with `cat pvag/*/*.md ada/*/*.md colreg/*/*.md > rules-master.md` (run in rules/). Every rule appears exactly once (checked).
- rules/<source>/coverage-ledger.md: coverage ledger per source (pvag, ada, colreg, dnv).
- rules/open-questions.md: conflicts, ambiguities and decisions for the user.
- rules/_sources/<source>/: raw downloaded files, canonical text used for the quote check, SOURCE.md.
- rules/_tools/: the scripts that produced everything (`bash rules/_tools/build_all.sh` rebuilds and verifies).

## Coverage (from the ledgers)
| source | status |
|---|---|
| PVAG | Chapters V1-V11 complete by the ledger: 106 sections EXTRACTED, every row reconciles (source rules = file rules), no NOT RETRIEVED / NOT YET DONE. |
| COLREG | Rules 1-41 and Annexes I-IV complete by the ledger **as printed in the USCG publications** (not compared with the IMO edition). 64 rows EXTRACTED, 2 NOT APPLICABLE (handbook's Inland-only Annex V column "[BLANK]", and U.S. law pages). |
| ADA | Requested subset complete (25 rows EXTRACTED and reconciled). The rest of the 2010 Standards: 84 sections NOT YET DONE (not requested). Not 100% of ADA. |
| DNV | NOT RETRIEVED (RU-SHIP, RU-HSLC). 0 rules. |

No "100%" claim is made for ADA or DNV, or for the project as a whole.

**Not collected yet (out of scope for this task, used by the plan):** SOLAS, FSS Code, HSC Code, MARPOL, Load Line Convention, Ballast Water Convention.
Cross-references from in-scope rules to out-of-scope or external instruments (recorded only, content not extracted):
- ASTM (referenced standard): ADA-105.2.3, ADA-106.5-use-zone, PVAG-V105.2.1, PVAG-V1004.2.6.1, PVAG-V1004.2.6.2, PVAG-V106.5-use-zone
- NFPA (referenced standard): ADA-105.2.5, PVAG-V105.2.2, PVAG-V702.2, PVAG-V806.3.3.1
- COLREGS 1960: COLREG-R38-intro
- International Code of Signals: COLREG-AnnexIV-3-text
- IAMSAR Manual: COLREG-AnnexIV-3-text
- 46 CFR (U.S. Coast Guard regulations): PVAG-V202.3, PVAG-V204.1

## Rule format
Each rule: a heading `### <id>` and a fenced ```yaml block with exactly these fields:
id, source, source_status, edition, clause, title, verbatim_quote, applies_to_ship_type, applicability_condition, discipline, applies_to, parameter, operator, threshold, unit, checkable, exceptions, cross_references, source_url, retrieved_on, verified, notes.
- verbatim_quote / exceptions: copied by code from the saved source text (never retyped). Multi-line values use YAML block scalars `|2-`. COLREG quotes keep the PDF line breaks.
- operator: `>=`, `<=`, `=`, `range` or `qualitative`. Where a clause contains several limits they are listed in source order separated by ` ; ` in parameter/operator/threshold/unit.
- threshold / unit: exactly as printed (no conversion, no rounding); the SI value printed next to a U.S. value is recorded in notes.
- parameter: for machine-derived rules = the clause title as in the source; for manually reviewed rules = the source's own words for each value.
- verified: **true** = quote found word for word in the saved source (script-checked) AND the structured fields are either empty (qualitative) or come from one unambiguous limit in the clause ("32 inches (815 mm) minimum", "not steeper than 1:12", "not less than 27°"), or were reviewed by hand (rules/_tools/manual_review.json: ADA-404.2.3, PVAG-V404.2.3, COLREG-R22a, COLREG-R22b, COLREG-R22c, COLREG-R22d, COLREG-AnnexI-2-a).
  **false** = the quote is still verified, but the structured fields need a human check (several values in one clause, values without minimum/maximum, formulas flattened by the PDF text layer, ...). The reason is the first sentence of notes.
- Units and numbers are exactly as printed; COLREG uses U.S. spelling ("meters") as printed in the USCG handbook.

## Ship-type grouping (Step A)
- **all-ship-types**: the rule applies throughout the source's general scope. PVAG Chapters V1-V10 apply to "Large vessels" (V201.1.1) and "Ferries" (V201.1.2) alike, so they are stored once here with both scope clauses quoted in applicability_condition. COLREG paragraphs that do not restrict themselves to a vessel category (Rule 1(a): all vessels) are stored here; a length condition (e.g. "of 50 meters or more in length") is not a ship type and stays in applicability_condition.
- **ferry / cruise-ship / fast-ferry**: only if the source names that type for the rule. No retrieved rule does.
- **unassigned**: applicability not stated in source, or stated with a source category that needs the mapping table. Breakdown:
  - ADA: applicability to vessels not stated in source (all ADA rules): 282
  - COLREG paragraph names vessel category: power-driven vessel: 20
  - COLREG paragraph names vessel category: sailing vessel: 9
  - COLREG Part F: addressed to Contracting Parties, not to vessels: 9
  - COLREG paragraph names vessel category: vessel engaged in fishing: 7
  - PVAG Chapter V11: Tenders permitted to carry more than 59 passengers (V201.1.3): 7
  - COLREG paragraph names vessel category: towing / towed vessel: 6
  - COLREG paragraph names vessel category: vessel engaged in trawling: 4
  - COLREG paragraph names vessel category: vessel at anchor: 4
  - COLREG paragraph names vessel category: vessel engaged on pilotage duty: 3
  - COLREG paragraph names vessel category: vessel aground: 3
  - COLREG paragraph names vessel category: WIG craft: 2
  - COLREG paragraph names vessel category: power-driven vessel, towing / towed vessel: 2
  - COLREG paragraph names vessel category: power-driven vessel, pushing vessel, composite unit: 2
  - COLREG paragraph names vessel category: vessel engaged in diving operations: 2
  - COLREG paragraph names vessel category: high-speed craft: 2
  - COLREG paragraph names vessel category: power-driven vessel, sailing vessel: 1
  - COLREG paragraph names vessel category: vessel restricted in her ability to maneuver: 1
  - COLREG paragraph names vessel category: vessel restricted in her ability to maneuver, submarine: 1
  - COLREG paragraph names vessel category: vessel not under command, vessel restricted in her ability to maneuver: 1
  - COLREG paragraph names vessel category: seaplane: 1
  - COLREG paragraph names vessel category: air-cushion vessel: 1
  - COLREG paragraph names vessel category: power-driven vessel, towing / towed vessel, pushing vessel, composite unit: 1
  - COLREG paragraph names vessel category: towing / towed vessel, pushing vessel: 1
  - COLREG paragraph names vessel category: vessel engaged in fishing, vessel at anchor: 1
  - COLREG paragraph names vessel category: vessel engaged in fishing, vessel engaged in trawling: 1
  - COLREG paragraph names vessel category: vessel not under command: 1
  - COLREG paragraph names vessel category: vessel restricted in her ability to maneuver, vessel engaged in mine clearance: 1
  - COLREG paragraph names vessel category: vessel restricted in her ability to maneuver, vessel engaged in dredging or underwater operations: 1
  - COLREG paragraph names vessel category: power-driven vessel, vessel at anchor, vessel engaged in mine clearance: 1
  - COLREG paragraph names vessel category: power-driven vessel, vessel constrained by her draft: 1
  - COLREG paragraph names vessel category: seaplane, WIG craft: 1
  - COLREG paragraph names vessel category: sailing vessel, vessel engaged in fishing, vessel not under command, vessel restricted in her ability to maneuver, vessel constrained by her draft, towing / towed vessel: 1
  - COLREG paragraph names vessel category: vessel engaged in fishing, vessel restricted in her ability to maneuver, vessel at anchor: 1
  - COLREG paragraph names vessel category: power-driven vessel, towing / towed vessel, pushing vessel: 1
  - COLREG paragraph names vessel category: vessel engaged in dredging or underwater operations: 1
  - COLREG paragraph names vessel category: vessel engaged in fishing, vessel fishing with purse seine: 1

### Mapping of source definitions to the three ship types — team assumption, to be confirmed by the user
| source definition / term | text as in source | maps to (team assumption, to be confirmed by the user) |
|---|---|---|
| PVAG V106.5 "Ferry" | A vessel that is used on a regular schedule to: (1) provide transportation only between places that are not more than 300 miles apart, and (2) transport only passengers, or vehicles or railroad cars used in transporting passengers or goods. | ferry; fast-ferry (a fast ferry on a regular schedule between places not more than 300 miles apart also meets this definition) |
| PVAG V201.1.2 Ferries (scope) | Ferries permitted to carry more than 99 passengers shall comply with Chapters V 1 through V 10. | ferry; fast-ferry (only if permitted to carry more than 99 passengers) |
| PVAG V201.1.1 Large Vessels (scope) | Passenger vessels, other than ferries and tenders, permitted to carry more than 150 passengers or more than 49 overnight passengers shall comply with Chapters V 1 through V 10. | cruise-ship (passenger vessels other than ferries and tenders, more than 150 passengers or more than 49 overnight passengers) |
| PVAG V106.5 "Tender" | A vessel primarily intended for transporting passengers for non-emergency purposes between passenger vessels and shore side facilities. | none of the three types (a cruise ship's tender boats would be separate vessels) |
| PVAG "high-speed passenger vessels" | term used in exceptions (e.g. V206.2.1 exceptions 4 and 5); not defined in V106.5 | fast-ferry |
| COLREG Rule 3(a) "vessel" | (a) The word vessel includes every description of water craft, including non- displacement craft, WIG craft and seaplanes, used or capable of being used as a means of transportation on water. | ferry; cruise-ship; fast-ferry |
| COLREG Rule 3(b) "power-driven vessel" | (b) The term power-driven vessel means any vessel propelled by machinery. | ferry; cruise-ship; fast-ferry (all are propelled by machinery) |
| COLREG Annex I section 13 "high-speed craft" | term used in Annex I 13(a)/(b); not defined in the Rules; footnote: "Refer to the International Code of Safety for High-Speed Craft, 1994 and the International Code of Safety for High-Speed Craft, 2000." (HSC Code out of scope) | fast-ferry (only if the craft is a high-speed craft under the HSC Code, which was not collected) |
| COLREG Rule 23(b) "air-cushion vessel ... non-displacement mode" | term used in Rule 23(b); not defined in Rule 3 | fast-ferry only if the design is an air-cushion vessel |
| COLREG Rule 3(m) "Wing-In-Ground (WIG) craft" | (m) The term Wing-In-Ground (WIG) craft means a multimodal craft which, in its main operational mode, flies in close proximity to the surface by utilizing surface-effect action. Condition of Visibility | none of the three types |
| ADA 2010 Standards | no vessel definitions; scope 101.1 covers "sites, facilities, buildings, and elements" | not mapped (applicability to vessels not stated) |
| DNV RU-SHIP / RU-HSLC | NOT RETRIEVED: no definitions available | not mapped |

## Verification
Run `python rules/_tools/verify.py` (also run by build_all.sh). Result of the last run is in the final report and in open-questions.md. It checks:
1. every rule block loads with PyYAML and has every field filled (parameter/threshold/unit may be empty only for qualitative rules);
2. every verbatim_quote and exceptions line is found word for word (whitespace-normalised) in the saved canonical source text;
3. independently, every quote line is also found in the raw downloaded file (HTML with tags stripped / PDF text layer);
4. every coverage-ledger row lists exactly the rules counted, and every EXTRACTED row has source count = file count;
5. rules-master.md contains every rule exactly once.

## Rules with verified: false

### PVAG: 166 rules with verified: false

| id | file | reason (from notes) |
|---|---|---|
| PVAG-V206.3 | pvag/all-ship-types/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| PVAG-V206.7.1 | pvag/all-ship-types/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| PVAG-V211.3 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V224.4 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V302.3 | pvag/all-ship-types/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| PVAG-V303.3 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V303.4 | pvag/all-ship-types/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| PVAG-V304.3.2 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (4 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V305.3 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V305.7.1 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V305.7.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V306.2.1 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V306.2.4 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V306.3.1 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V306.3.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V306.3.3 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V306.3.4 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V307.2 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (2 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V307.4 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (2 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V308.1 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V308.2.1 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V308.2.2 | pvag/all-ship-types/accessibility.md | clause contains 5 numeric values (4 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V308.3.1 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V308.3.2 | pvag/all-ship-types/accessibility.md | clause contains 7 numeric values (6 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V403.3 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V403.5.2.1 | pvag/all-ship-types/accessibility.md | clause contains 5 numeric values (3 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V403.5.2.2 | pvag/all-ship-types/accessibility.md | clause contains 6 numeric values (4 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V403.5.3 | pvag/all-ship-types/accessibility.md | clause contains 5 numeric values (4 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V404.2.4.1 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V404.2.4.2 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V404.2.4.3 | pvag/all-ship-types/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| PVAG-V404.2.7 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V404.2.8.1 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (1 read as minimum/maximum/slope limits, 2 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V404.2.8.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V404.2.10 | pvag/all-ship-types/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| PVAG-V405.7.4 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V405.8 | pvag/all-ship-types/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| PVAG-V405.9.2 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V407.2.2.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V407.2.2.3 | pvag/all-ship-types/accessibility.md | clause contains 5 numeric values (5 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V407.3.3.1 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V407.3.4 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (1 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V407.4.4 | pvag/all-ship-types/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| PVAG-V407.4.5 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V407.4.7.2 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V407.4.8.2.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V407.4.8.2.3 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V408.4.1 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V409.5 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V410.7.4 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V410.8 | pvag/all-ship-types/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| PVAG-V410.9.2 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V411.5 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V411.9 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V411.11 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (3 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V502.2 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V502.5 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V503.4 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V503.6 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V503.7.1 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V503.7.2 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V602.5 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V602.6 | pvag/all-ship-types/accessibility.md | clause contains 7 numeric values (5 read as minimum/maximum/slope limits, 2 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V602.7 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V603.3 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V603.4 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V604.2 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (4 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V604.3.1 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V604.4 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V604.5.1 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V604.5.2 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V604.7 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (4 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V604.8.1.1 | pvag/all-ship-types/accessibility.md | clause contains 5 numeric values (5 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V604.8.1.2 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V604.8.1.4 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V604.8.2.1 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V604.8.3 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V604.9 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V604.9.1 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (4 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V604.9.3 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V604.9.6 | pvag/all-ship-types/accessibility.md | clause contains 5 numeric values (5 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V605.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V607.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V607.4.1.1 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (4 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V607.4.2.1 | pvag/all-ship-types/accessibility.md | clause contains 5 numeric values (5 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V608.2.1 | pvag/all-ship-types/accessibility.md | clause contains 5 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V608.2.2 | pvag/all-ship-types/accessibility.md | clause contains 5 numeric values (5 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V608.2.3 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V608.2.4 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V608.3.1 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V608.5.1 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V608.5.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V608.5.3 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V608.7 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V609.2.1 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V609.2.2 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V609.3 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V609.4 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (4 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V609.8 | pvag/all-ship-types/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| PVAG-V610.2 | pvag/all-ship-types/accessibility.md | clause contains 5 numeric values (5 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V610.3 | pvag/all-ship-types/accessibility.md | clause contains 5 numeric values (2 read as minimum/maximum/slope limits, 3 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V610.3.1 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (4 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V610.3.2 | pvag/all-ship-types/accessibility.md | clause contains 9 numeric values (8 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V610.4 | pvag/all-ship-types/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| PVAG-V611.4 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V703.2.4 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V703.2.5 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V703.2.7 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (4 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V703.2.8 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V703.3.1 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V703.3.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V703.4.1 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V703.4.2 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V703.5.4 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V703.5.5 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V703.5.7 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V703.5.8 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V703.5.9 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V704.3 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V706.2 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V706.4 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (2 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V707.7.1 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V802.1.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V802.1.3 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V802.3.1 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V803.5 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V804.5.6 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V806.3.4 | pvag/all-ship-types/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| PVAG-V902.3 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V902.4.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V903.3 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V903.4 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (4 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V903.5 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V903.6 | pvag/all-ship-types/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| PVAG-V904.3.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V904.4.1 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V904.4.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V904.5.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1003.3.1 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1003.3.2 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (4 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1004.2 | pvag/all-ship-types/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| PVAG-V1004.2.5.3.1 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1004.2.5.3.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1004.3.1.1 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1004.3.1.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1004.3.1.3 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1004.3.2.1 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1004.4.3 | pvag/all-ship-types/accessibility.md | clause contains 5 numeric values (3 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1004.4.4 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1005.2.1 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1005.2.2 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1005.2.3 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1005.3.2 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (4 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1005.3.3 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1005.4.1 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1005.4.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1005.4.3 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1005.4.5 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (4 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1005.5.1 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1005.5.2 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (4 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1005.5.4 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1005.5.6 | pvag/all-ship-types/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1005.5.7 | pvag/all-ship-types/accessibility.md | clause contains 4 numeric values (4 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1005.6.2 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1006.1 | pvag/all-ship-types/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| PVAG-V1102.2 | pvag/unassigned/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |

### ADA: 39 rules with verified: false

| id | file | reason (from notes) |
|---|---|---|
| ADA-203.9 | ada/unassigned/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| ADA-302.3 | ada/unassigned/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| ADA-303.3 | ada/unassigned/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| ADA-303.4 | ada/unassigned/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| ADA-304.3.2 | ada/unassigned/accessibility.md | clause contains 4 numeric values (4 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| ADA-305.3 | ada/unassigned/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| ADA-305.7.1 | ada/unassigned/accessibility.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| ADA-305.7.2 | ada/unassigned/accessibility.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| ADA-306.2.1 | ada/unassigned/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| ADA-306.2.4 | ada/unassigned/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| ADA-306.3.1 | ada/unassigned/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| ADA-306.3.2 | ada/unassigned/accessibility.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| ADA-306.3.3 | ada/unassigned/accessibility.md | clause contains 4 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| ADA-306.3.4 | ada/unassigned/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| ADA-307.2 | ada/unassigned/accessibility.md | clause contains 3 numeric values (2 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| ADA-307.3 | ada/unassigned/accessibility.md | clause contains 6 numeric values (5 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| ADA-307.4 | ada/unassigned/accessibility.md | clause contains 3 numeric values (2 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| ADA-308.2.1 | ada/unassigned/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| ADA-308.2.2 | ada/unassigned/accessibility.md | clause contains 5 numeric values (4 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| ADA-308.3.1 | ada/unassigned/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| ADA-308.3.2 | ada/unassigned/accessibility.md | clause contains 7 numeric values (6 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| ADA-403.3 | ada/unassigned/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| ADA-403.5.2 | ada/unassigned/accessibility.md | clause contains 5 numeric values (3 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| ADA-403.5.3 | ada/unassigned/accessibility.md | clause contains 5 numeric values (4 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| ADA-404.2.4.1 | ada/unassigned/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| ADA-404.2.4.2 | ada/unassigned/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| ADA-404.2.4.3 | ada/unassigned/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| ADA-404.2.7 | ada/unassigned/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| ADA-404.2.8.1 | ada/unassigned/accessibility.md | clause contains 3 numeric values (1 read as minimum/maximum/slope limits, 2 as conditions); structured fields list only the limit values in source order and nee |
| ADA-404.2.8.2 | ada/unassigned/accessibility.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| ADA-404.2.9 | ada/unassigned/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| ADA-404.2.10 | ada/unassigned/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| ADA-405.7.4 | ada/unassigned/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| ADA-405.8 | ada/unassigned/accessibility.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| ADA-405.9.2 | ada/unassigned/accessibility.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| ADA-505.4 | ada/unassigned/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| ADA-505.6 | ada/unassigned/accessibility.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| ADA-505.7.1 | ada/unassigned/accessibility.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| ADA-505.7.2 | ada/unassigned/accessibility.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |

### COLREG: 69 rules with verified: false

| id | file | reason (from notes) |
|---|---|---|
| COLREG-R10d | colreg/all-ship-types/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R13b | colreg/all-ship-types/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R21a | colreg/all-ship-types/navigation-lights.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| COLREG-R21b | colreg/all-ship-types/navigation-lights.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| COLREG-R21c | colreg/all-ship-types/navigation-lights.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| COLREG-R21e | colreg/all-ship-types/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R30b | colreg/all-ship-types/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R33a | colreg/all-ship-types/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R33b | colreg/all-ship-types/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R34b | colreg/all-ship-types/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R34f | colreg/all-ship-types/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R35i | colreg/all-ship-types/navigation-lights.md | clause contains 3 numeric values (1 read as minimum/maximum/slope limits, 2 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-R35j | colreg/all-ship-types/navigation-lights.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-R38d | colreg/all-ship-types/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R38d-part2 | colreg/all-ship-types/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-AnnexI-2-i | colreg/all-ship-types/navigation-lights.md | clause contains 6 numeric values (3 read as minimum/maximum/slope limits, 3 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-AnnexI-2-k | colreg/all-ship-types/navigation-lights.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| COLREG-AnnexI-5-text | colreg/all-ship-types/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-AnnexI-6-a | colreg/all-ship-types/navigation-lights.md | clause contains 3 numeric values (3 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-AnnexI-6-c | colreg/all-ship-types/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-AnnexI-8-a | colreg/all-ship-types/navigation-lights.md | the PDF prints a formula or exponent (superscript/subscript) that plain-text extraction flattens (e.g. "106" for 10 to the power 6); the quote is exactly what t |
| COLREG-AnnexI-9-a | colreg/all-ship-types/navigation-lights.md | clause contains 7 numeric values (2 read as minimum/maximum/slope limits, 2 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-AnnexI-9-b | colreg/all-ship-types/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-AnnexI-12-text | colreg/all-ship-types/navigation-lights.md | clause contains 3 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-AnnexII-1-text | colreg/all-ship-types/navigation-lights.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-AnnexIII-1-a | colreg/all-ship-types/navigation-lights.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| COLREG-AnnexIII-1-b | colreg/all-ship-types/navigation-lights.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| COLREG-AnnexIII-1-c | colreg/all-ship-types/navigation-lights.md | the Annex III 1(c) table is printed on the next PDF page (139) and its text order in the extraction differs from the logical order; check the PDF; the PDF print |
| COLREG-AnnexIII-1-d | colreg/all-ship-types/navigation-lights.md | the Annex III 1(c) table is printed on the next PDF page (139) and its text order in the extraction differs from the logical order; check the PDF; clause contai |
| COLREG-AnnexIII-1-e | colreg/all-ship-types/navigation-lights.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-AnnexIII-1-f | colreg/all-ship-types/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-AnnexIII-1-g | colreg/all-ship-types/navigation-lights.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-AnnexIII-2-a | colreg/all-ship-types/navigation-lights.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-AnnexIII-2-b | colreg/all-ship-types/navigation-lights.md | clause contains 3 numeric values (2 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-AnnexIV-1-l | colreg/all-ship-types/navigation-lights.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| COLREG-R9b | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R10j | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R23a | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R23d | colreg/unassigned/navigation-lights.md | clause contains 4 numeric values (1 read as minimum/maximum/slope limits, 3 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-R24a | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R24e | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R24g | colreg/unassigned/navigation-lights.md | clause contains 5 numeric values (1 read as minimum/maximum/slope limits, 4 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-R25b | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R25d | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R26b | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R26c | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R27f | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R27g | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R30c | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R30e | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R30f | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-R35b | colreg/unassigned/navigation-lights.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-R35c | colreg/unassigned/navigation-lights.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| COLREG-R35g | colreg/unassigned/navigation-lights.md | clause contains numeric values without "minimum"/"maximum"; per the source conventions such values may be absolute or may be conditions; operator "=" is provisi |
| COLREG-AnnexI-2-b | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-AnnexI-2-c | colreg/unassigned/navigation-lights.md | clause contains 3 numeric values (1 read as minimum/maximum/slope limits, 2 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-AnnexI-2-d | colreg/unassigned/navigation-lights.md | clause contains 3 numeric values (1 read as minimum/maximum/slope limits, 2 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-AnnexI-2-h | colreg/unassigned/navigation-lights.md | clause contains 2 numeric values (1 read as minimum/maximum/slope limits, 1 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-AnnexI-3-a | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-AnnexI-3-b | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-AnnexI-3-d | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-AnnexI-4-a | colreg/unassigned/navigation-lights.md | clause contains 2 numeric values (2 read as minimum/maximum/slope limits, 0 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-AnnexI-4-b | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-AnnexI-10-a | colreg/unassigned/navigation-lights.md | clause contains 5 numeric values (1 read as minimum/maximum/slope limits, 2 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-AnnexI-10-b | colreg/unassigned/navigation-lights.md | clause contains 5 numeric values (1 read as minimum/maximum/slope limits, 2 as conditions); structured fields list only the limit values in source order and nee |
| COLREG-AnnexI-13-b | colreg/unassigned/navigation-lights.md | the PDF prints a formula or exponent (superscript/subscript) that plain-text extraction flattens (e.g. "106" for 10 to the power 6); the quote is exactly what t |
| COLREG-AnnexII-2-a | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-AnnexII-2-b | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
| COLREG-AnnexII-2-c | colreg/unassigned/navigation-lights.md | clause contains numeric values that read as conditions only (e.g. "less than 20 meters in length"); no numeric limit structured; check whether a measurable limi |
