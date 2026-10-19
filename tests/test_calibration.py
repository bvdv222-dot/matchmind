"""The generator is calibrated from this file; guard its shape so a bad re-run can't slip in."""
import json
from pathlib import Path

PARAMS = Path(__file__).resolve().parents[1] / "calibration" / "params_wyscout_pl1718.json"


def test_params_present_and_sane():
    p = json.loads(PARAMS.read_text(encoding="utf-8"))
    assert p["matches"] == 380
    goals = p["results"]["home_goals_mean"] + p["results"]["away_goals_mean"]
    assert 2.4 < goals < 3.0
    xg = p["shots"]["xg_model"]
    assert xg["b1"] < 0 < xg["b2"]  # further = worse, wider angle = better
    for key in ("possessions", "set_pieces", "passes", "team_strength", "players", "game_state"):
        assert key in p
