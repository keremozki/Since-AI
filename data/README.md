# Test data

- `sources.md`: every source checked, with links, licence, format, scale and a score.
- `raw/`: files with a clear licence (Wikimedia). The 26 MB Lusitania plan is git-ignored, so download it from the link.
- `restricted/`: files with no stated licence (RCRV, Sikuliaq, MARAD). Git-ignored. Keep them local.
- `synthetic/`: our seeded-error deck plans and their truth files (**synthetic**).
- `ground_truth/`: hand-labelled facts for real drawings, in the app's `Fact` shape.
- `reports/`: probe images and `eval.json` (renders of restricted files are git-ignored).

```bash
.venv/Scripts/python tools/make_synthetic_ga.py     # rebuild the synthetic sheets
.venv/Scripts/python tools/probe_drawing.py FILE    # vector or scan? scale? object words?
.venv/Scripts/python tools/eval_test_data.py        # oracle run, plus the reader run if ANTHROPIC_API_KEY is set
```

## Results on 7 Nov 2026 (no API key, so oracle mode only)

The oracle run feeds the exact truth facts into the engine, so reading errors are excluded.

| Sheet | Doors | Expected | App result |
|---|---|---|---|
| syn_01_mixed | 8 | 4 pass, 3 fail, 1 can't tell | **0/8**: no result for any door |
| syn_02_units_conflict | 8 | 4 pass, 3 fail, 1 conflict | **1/8**: only the conflict |
| syn_03_compliant_control | 6 | 6 pass | **0/6**: no result |

Why: `check_door_clear_width` only judges doors from the 3D model (`door:` subjects). Door widths read
from a drawing (`door-number:N`) are used only to find conflicts. A drawing-only design gets no door
result at all, not even "can't tell". Corridor width and ramp slope have no check in the app yet.

Reader path problems found by `build_content` (no API call made):
- RCRV RFI PDF: the drawing pages have no text, but the text pages push the average over the limit. So
  the reader sends only text, and the GA sheets are never shown to the model.
- MARAD scan: refused (8 image pages, max 6), unless pages are chosen.
- Large images (Lusitania, 12320x16109 px) are sent without resizing. This will probably break the API's image size limit (not tested, since there is no key).
