"""Validate serving data: run `python validate.py` from the backend directory."""

import json
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError

from backend.config import Settings
from backend.schemas import Curve, Districts, FeatureCollection
from backend.services import brief_for, current_week, worklist_for
from backend.store import ServingStore


def main() -> int:
    store = ServingStore(Settings.from_env())
    try:
        meta = store.meta()
        parks = store.parks()
        active = store.ranked()
        if len(active) != meta.population:
            raise ValueError("Active count differs from meta.population")
        ranks = [park.risk.rank for park in active]
        if ranks != list(range(1, len(active) + 1)):
            raise ValueError("Active ranks must be unique and consecutive")
        store.validated("districts", Districts)
        store.validated("curve", Curve)
        geo = store.validated("map", FeatureCollection)
        if any(f.properties.park_id not in parks for f in geo.features):
            raise ValueError("Map contains unknown park ids")
        for park in parks.values():
            brief_for(store, park)
        worklist_for(store, current_week(), 200)
        print(
            json.dumps(
                {
                    "version": meta.version,
                    "parks": len(parks),
                    "active": len(active),
                    "map_points": len(geo.features),
                    "parks_without_reason_codes": sum(not p.reasons for p in parks.values()),
                    "status": "valid",
                }
            )
        )
        return 0
    except ValidationError as exc:
        # Field locations are useful during development; raw inputs may contain personal data.
        print(
            json.dumps(
                {
                    "status": "invalid",
                    "fields": [
                        {"location": list(error["loc"]), "type": error["type"]}
                        for error in exc.errors(include_input=False)
                    ],
                }
            ),
            file=sys.stderr,
        )
    except Exception as exc:  # noqa: BLE001 - CLI reports no raw artifact contents
        print(json.dumps({"status": "invalid", "error_type": type(exc).__name__}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
