# Calibration

`params_wyscout_pl1718.json` holds the distributions the generator samples from. It was profiled from the Wyscout Premier League 2017/18 event data (380 matches; CC BY 4.0; see [../docs/DATA_PROVENANCE.md](../docs/DATA_PROVENANCE.md)).

- `profile_wyscout.py` rebuilds the parameters from the raw Wyscout files (not included).
- `profile_sc.py` profiles SkillCorner open data (MIT) for physical profiles by position.

Run both with `py -I <script> ...` so nothing in the data folder can shadow an import.
