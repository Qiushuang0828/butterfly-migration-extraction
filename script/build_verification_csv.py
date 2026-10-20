#!/usr/bin/env python3
"""Build a human-verification CSV: only rows where the extraction actually
pulled out migration-relevant info, pairing the ORIGINAL source text next to
every extracted field so a person can check each extraction against its source.

Updated with:
- quantity_unit
- sex
- life_stage
"""
import csv
import json
from pathlib import Path

from build_metadata_csv import distance_confidence

PROJECT_DIR = Path(__file__).parent.parent
RESULTS_JSON = PROJECT_DIR / "data" / "interim" / "deepseek_output_species" / "results.json"
OUTPUT_CSV = PROJECT_DIR / "output" / "extraction_verification.csv"

MOVEMENT_FIELDS = [
    "direction", "wind_direction", "distance", "destination", 
    "corridor_observation", "sex", "life_stage"
]

FIELDS = [
    "uid", "gbifID", "species", "family", "taxonKey", "basisOfRecord",
    "year", "month", "decimalLatitude", "decimalLongitude",
    "original_text",
    "direction", "direction_raw", "direction_is_arrival",
    "direction_degrees_mid", "direction_degrees_min", "direction_degrees_max",
    "wind_direction", "wind_direction_raw",
    "corridor_observation", "corridor_observation_raw",
    "quantity", "quantity_unit", "quantity_unit_raw", "quantity_raw", "individualCount",
    "sex", "sex_raw",
    "life_stage", "life_stage_raw",
    "distance", "distance_unit", "distance_raw", "distance_confidence",
    "destination", "destination_raw",
    "behaviour_notes",
    "review_verified", "review_corrections",
]


def row_from_record(r: dict) -> dict:
    er = r.get("extraction_reviewed") or {}
    deg = r.get("direction_degrees_computed") or {}
    return {
        "uid": r.get("uid", ""),
        "gbifID": r.get("gbifID", ""),
        "species": r.get("species", ""),
        "family": r.get("family", ""),
        "taxonKey": r.get("taxonKey", ""),
        "basisOfRecord": r.get("basisOfRecord", ""),
        "year": r.get("year", ""),
        "month": r.get("month", ""),
        "decimalLatitude": r.get("decimalLatitude", ""),
        "decimalLongitude": r.get("decimalLongitude", ""),
        "original_text": r.get("notesText", ""),
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
        "individualCount": r.get("individualCount", ""),
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
        "review_verified": r.get("extract_review_verified"),
        "review_corrections": r.get("extract_review_corrections") or "",
    }


def main() -> None:
    if not RESULTS_JSON.exists():
        print(f"Error: {RESULTS_JSON} not found. Please run extraction first.")
        return
    records = json.load(open(RESULTS_JSON, encoding="utf-8"))
    kept = 0
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for r in records:
            if r.get("extract_error"):
                continue
            er = r.get("extraction_reviewed") or {}
            if not any(er.get(f) not in (None, "") for f in MOVEMENT_FIELDS):
                continue
            writer.writerow(row_from_record(r))
            kept += 1
    print(f"Wrote {kept} rows (of {len(records)} total) -> {OUTPUT_CSV}")


if __name__ == "__main__":
    main()