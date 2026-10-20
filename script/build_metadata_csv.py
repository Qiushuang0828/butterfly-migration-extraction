#!/usr/bin/env python3
"""Build the final slim deliverable CSV from deepseek_output_species/results.json.

Updated with:
- quantity_unit, quantity_unit_raw
- sex, sex_raw
- life_stage, life_stage_raw
"""
import csv
import json
import re
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
RESULTS_JSON = PROJECT_DIR / "data" / "interim" / "deepseek_output_species" / "results.json"
OUTPUT_CSV = PROJECT_DIR / "output" / "metadata.csv"

FIELDS = [
    "uid", "gbifID", "species", "family", "year", "month",
    "decimalLatitude", "decimalLongitude", "individualCount",
    "direction", "direction_raw", "direction_is_arrival",
    "direction_degrees_mid", "direction_degrees_min", "direction_degrees_max",
    "wind_direction", "wind_direction_raw",
    "corridor_observation", "corridor_observation_raw",
    "quantity", "quantity_unit", "quantity_unit_raw", "quantity_raw",
    "sex", "sex_raw",
    "life_stage", "life_stage_raw",
    "distance", "distance_unit", "distance_raw", "distance_confidence",
    "destination", "destination_raw",
    "behaviour_notes",
]

SHORT_DISTANCE_THRESHOLD_M = 50.0
_UNIT_TO_METERS = {
    "m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0,
    "feet": 0.3048, "foot": 0.3048, "ft": 0.3048, "'": 0.3048,
    "mile": 1609.34, "miles": 1609.34, "mi": 1609.34,
    "km": 1000.0, "kilometer": 1000.0, "kilometers": 1000.0,
    "kilometre": 1000.0, "kilometres": 1000.0,
}
_MIGRATION_CONTEXT_RE = re.compile(
    r"migrat|dispers|overwinter|tag|recover|releas|offshore|crossing|corridor|sanctuary",
    re.IGNORECASE,
)


def distance_confidence(distance, distance_unit: str, distance_raw: str, notes_text: str) -> str:
    if distance is None or distance == "":
        return ""
    try:
        value_m = float(distance) * _UNIT_TO_METERS.get((distance_unit or "").strip().lower(), 1.0)
    except (TypeError, ValueError):
        return "unknown"
    if value_m >= SHORT_DISTANCE_THRESHOLD_M:
        return "high"
    context = f"{distance_raw or ''} {notes_text or ''}"
    if _MIGRATION_CONTEXT_RE.search(context):
        return "high"
    return "low"


def row_from_record(r: dict) -> dict:
    er = r.get("extraction_reviewed") or {}
    deg = r.get("direction_degrees_computed") or {}
    return {
        "uid": r.get("uid", ""),
        "gbifID": r.get("gbifID", ""),
        "species": r.get("species", ""),
        "family": r.get("family", ""),
        "year": r.get("year", ""),
        "month": r.get("month", ""),
        "decimalLatitude": r.get("decimalLatitude", ""),
        "decimalLongitude": r.get("decimalLongitude", ""),
        "individualCount": r.get("individualCount", ""),
        "direction": er.get("direction") or "",
        "direction_raw": er.get("direction_raw") or "",
        "direction_is_arrival": er.get("direction_is_arrival"),
        "direction_degrees_mid": deg.get("mid", ""),
        "direction_degrees_min": deg.get("min", ""),
        "direction_degrees_max": deg.get("max", ""),
        "wind_direction": er.get("wind_direction") or "",
        "wind_direction_raw": er.get("wind_direction_raw") or "",
        "corridor_observation": er.get("corridor_observation"),
        "corridor_observation_raw": er.get("corridor_observation_raw") or "",
        "quantity": er.get("quantity") if er.get("quantity") is not None else "",
        "quantity_unit": er.get("quantity_unit") or "",
        "quantity_unit_raw": er.get("quantity_unit_raw") or "",
        "quantity_raw": er.get("quantity_raw") or "",
        "sex": er.get("sex") or "",
        "sex_raw": er.get("sex_raw") or "",
        "life_stage": er.get("life_stage") or "",
        "life_stage_raw": er.get("life_stage_raw") or "",
        "distance": er.get("distance") if er.get("distance") is not None else "",
        "distance_unit": er.get("distance_unit") or "",
        "distance_raw": er.get("distance_raw") or "",
        "distance_confidence": distance_confidence(
            er.get("distance"), er.get("distance_unit"), er.get("distance_raw"), r.get("notesText")
        ),
        "destination": er.get("destination") or "",
        "destination_raw": er.get("destination_raw") or "",
        "behaviour_notes": er.get("behaviour_notes") or "",
    }


def main() -> None:
    if not RESULTS_JSON.exists():
        print(f"Error: {RESULTS_JSON} not found. Please run extraction first.")
        return
    records = json.load(open(RESULTS_JSON, encoding="utf-8"))
    skipped_errors = 0
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for r in records:
            if r.get("extract_error"):
                skipped_errors += 1
                continue
            writer.writerow(row_from_record(r))
    print(f"Wrote {len(records) - skipped_errors} rows -> {OUTPUT_CSV} "
          f"(skipped {skipped_errors} error rows)")


if __name__ == "__main__":
    main()