# Offline demo set (SYNTHETIC)

Four small generated drawings, not a real ship. Upload one in the app with the **passenger-test**
profile. Vector PDFs are read by code, so no API key and no Wi-Fi are needed.

| File | Shows |
|---|---|
| SYNTHETIC_demo_1_PASS.pdf | door 34 in, corridor 1200 mm, ramp 1:14: all PASS |
| SYNTHETIC_demo_2_FAIL.pdf | door 30 in, corridor 2'-6", ramp 150/1500 mm (1:10): all FAIL |
| SYNTHETIC_demo_3_CANT_TELL.pdf | door with no width, corridor 34 in (exception band), rotated ramp slope: CAN'T TELL |
| SYNTHETIC_demo_4_CONFLICT.pdf | door 34 in on the plan, 30 in in the schedule: CONFLICT |

Rebuild: `.venv/Scripts/python tools/make_offline_demo.py`. Tested by `backend/tests/test_offline_demo.py`.
