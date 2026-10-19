"""Write the JSON Schemas for the contract models into schema/ (run after changing contracts/models.py)."""
import json
from pathlib import Path

from contracts import models

OUT = Path(__file__).resolve().parents[1] / "schema"
EXPORTS = {
    "league": models.League,
    "match_meta": models.MatchMeta,
    "event": models.Event,
    "position_frame": models.PositionFrame,
    "overlay_message": models.OverlayMessage,
    "stream_message": models.StreamMessage,
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, model in EXPORTS.items():
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://github.com/bvdv222-dot/matchmind/schema/{name}.schema.json"
        (OUT / f"{name}.schema.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        print(f"wrote schema/{name}.schema.json")


if __name__ == "__main__":
    main()
