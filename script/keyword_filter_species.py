#!/usr/bin/env python3
"""
Pure pandas + local keyword filter for the species-scoped GBIF download - no
DeepSeek API calls for classification.

Per user decision (2026-09-17): the word-frequency calibration run against
the 1,205 already-confirmed relevant records (from the earlier family-wide
classify pass) showed the local keyword prefilter already carries the
dominant signal, and this file is already scoped to 426 known-migratory
species (not a whole family) - so keyword match alone is treated as good
enough for candidacy here. No LLM classify/review calls happen in this
script; the DeepSeek budget goes only into the extract stage afterwards
(direction/quantity/distance), which genuinely needs an LLM to pull
structured fields out of free text - keyword search can't do that part.

Reuses the exact calibrated STRONG/WEAK/ANCHOR regex patterns from
deepseek_migration_pipeline.py (same rule: WEAK direction/wind/distance words
only count when they co-occur with an ANCHOR movement word), so the two
paths can't silently drift apart.

Usage
-----
    python script/keyword_filter_species.py --input data/raw/gbif_migratory_species_download.csv --outdir data/interim/deepseek_output_species

Output: <outdir>/classify.jsonl, in the same schema classify_row() writes on
a real LLM success, so the existing extract stage can consume it unchanged:
    python script/deepseek_migration_pipeline.py --stage extract --outdir data/interim/deepseek_output_species
"""

import argparse
import json
import warnings
from pathlib import Path

import pandas as pd

# Our STRONG/WEAK/ANCHOR patterns use non-capturing-unaware groups like
# (y|ies|ying...) for alternation, not for extraction - str.contains only
# needs a boolean match, so this warning ("did you mean str.extract?") never
# applies here.
warnings.filterwarnings("ignore", message="This pattern is interpreted as a regular expression")

import deepseek_migration_pipeline as pipeline

CSV_DELIMITER = "\t"
CHUNK_SIZE = 200_000

OUTPUT_COLUMNS = [
    "row_id", "sourceFile", "uid", "gbifID", "species",
    "decimalLatitude", "decimalLongitude", "year", "month", "basisOfRecord",
    "taxonKey", "family", "occurrenceRemarks", "eventRemarks",
    "dynamicProperties", "fieldNotes", "behavior", "locationRemarks",
    "organismRemarks", "individualCount", "organismQuantity",
    "organismQuantityType",
]


def build_combined_freetext(df: pd.DataFrame) -> pd.Series:
    """Same fields as Row.prefilter_text() - FREETEXT_COLUMNS only, ignoring
    STRUCTURED_COLUMNS (dynamicProperties/individualCount/etc), which don't
    drive candidacy (see deepseek_migration_pipeline.py for why)."""
    parts = None
    for col, _label in pipeline.FREETEXT_COLUMNS:
        series = df.get(col, pd.Series("", index=df.index)).fillna("").astype(str)
        parts = series if parts is None else parts.str.cat(series, sep="\n")
    return parts


def keyword_mask(freetext: pd.Series) -> pd.Series:
    # Mirrors pipeline.passes_local_prefilter() exactly - see that function's
    # docstring/comments for why quantity words are anchor-gated and why
    # known boilerplate templates are stripped before matching.
    # Pass the compiled pattern (not .pattern text) so its IGNORECASE|MULTILINE
    # flags carry over - MULTILINE matters here since the bare-activity-tag
    # alternative in _BOILERPLATE_RE anchors on ^/$ per line, and freetext
    # rows are multiple \n-joined fields.
    cleaned = freetext.str.replace(pipeline._BOILERPLATE_RE, " ", regex=True)
    strong = cleaned.str.contains(pipeline._STRONG_RE.pattern, case=False, regex=True, na=False)
    weak = cleaned.str.contains(pipeline._WEAK_RE.pattern, case=False, regex=True, na=False)
    quantity = cleaned.str.contains(pipeline._QUANTITY_RE.pattern, case=False, regex=True, na=False)
    anchor = cleaned.str.contains(pipeline._ANCHOR_RE.pattern, case=False, regex=True, na=False)
    return strong | (anchor & (weak | quantity))


FREETEXT_COL_NAMES = {col for col, _label in pipeline.FREETEXT_COLUMNS}


def row_to_record(row: pd.Series, row_id: int, source_file: str) -> dict:
    gbifid = str(row.get("gbifid") or "").strip()
    uid = gbifid if gbifid else f"{source_file}:{row_id}"

    def notes_field(col: str) -> str:
        val = str(row.get(col) or "").strip()
        # Per user decision: a row can match on ONE free-text column's
        # keyword (e.g. eventRemarks) while carrying unrelated text in
        # another (e.g. fieldNotes about a nectar plant) - clear any
        # FREETEXT_COLUMNS field that doesn't itself contain a keyword hit,
        # so only the text that actually triggered relevance reaches the
        # extraction LLM later. STRUCTURED_COLUMNS (dynamicProperties/
        # individualCount/etc) are never keyword-screened in the first
        # place, so they're left untouched here regardless of content.
        if col in FREETEXT_COL_NAMES and val and not pipeline.passes_local_prefilter(val):
            return ""
        return val

    notes_text_parts = []
    for col, label in pipeline.NOTE_COLUMNS:
        val = notes_field(col)
        if val and val.lower() not in pipeline._IGNORE_VALUES:
            notes_text_parts.append(f"{label}: {val}")

    return {
        "uid": uid,
        "row_id": row_id,
        "sourceFile": source_file,
        "gbifID": gbifid or None,
        "species": str(row.get("species") or "").strip(),
        "decimalLatitude": str(row.get("decimallatitude") or ""),
        "decimalLongitude": str(row.get("decimallongitude") or ""),
        "year": str(row.get("year") or ""),
        "month": str(row.get("month") or ""),
        "basisOfRecord": str(row.get("basisofrecord") or ""),
        "taxonKey": str(row.get("taxonkey") or ""),
        "family": str(row.get("family") or ""),
        "occurrenceRemarks": notes_field("occurrenceremarks"),
        "eventRemarks": notes_field("eventremarks"),
        "dynamicProperties": notes_field("dynamicproperties"),
        "fieldNotes": notes_field("fieldnotes"),
        "behavior": notes_field("behavior"),
        "locationRemarks": notes_field("locationremarks"),
        "organismRemarks": notes_field("organismremarks"),
        "individualCount": notes_field("individualcount"),
        "organismQuantity": notes_field("organismquantity"),
        "organismQuantityType": notes_field("organismquantitytype"),
        "notesText": "\n".join(notes_text_parts),
        "classification": {
            "relevant": True,
            "confidence": None,
            "reason": "local keyword match only (species-scoped download, no LLM classify - see keyword_filter_species.py)",
        },
        "classification_reviewed": None,
        "relevant": True,
        "review_verified": None,
        "review_corrections": None,
        "error": None,
        "model": "keyword-only",
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, help="Species-scoped GBIF TSV/CSV")
    p.add_argument("--outdir", default="data/interim/deepseek_output_species", help="Where to write classify.jsonl")
    p.add_argument("--limit", type=int, default=None, help="Only scan the first N rows (test runs)")
    args = p.parse_args()

    input_path = Path(args.input)
    source_file = input_path.name
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / "classify.jsonl"

    total_seen = 0
    total_matched = 0
    out_f = open(out_path, "w", encoding="utf-8")
    try:
        reader = pd.read_csv(
            input_path, sep=CSV_DELIMITER, dtype=str, chunksize=CHUNK_SIZE,
            keep_default_na=False, na_values=[], engine="c",
        )
        row_id_offset = 0
        for chunk in reader:
            if args.limit is not None and total_seen >= args.limit:
                break
            if args.limit is not None:
                remaining = args.limit - total_seen
                if remaining < len(chunk):
                    chunk = chunk.iloc[:remaining]

            # Global row_id = position in the whole file, independent of
            # pandas' own chunk-local index - explicit rather than relying on
            # TextFileReader's index-continuation behaviour across chunks.
            chunk = chunk.reset_index(drop=True)
            freetext = build_combined_freetext(chunk)
            mask = keyword_mask(freetext)
            matched_local_positions = chunk.index[mask]

            for local_pos in matched_local_positions:
                row = chunk.iloc[local_pos]
                rec = row_to_record(row, row_id_offset + int(local_pos), source_file)
                out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")

            total_seen += len(chunk)
            total_matched += len(matched_local_positions)
            row_id_offset += len(chunk)
            print(f"seen={total_seen} matched={total_matched} "
                  f"rate={total_matched/total_seen*100:.2f}%", flush=True)
    finally:
        out_f.close()

    print(f"Done. seen={total_seen} matched={total_matched} -> {out_path}")


if __name__ == "__main__":
    main()
