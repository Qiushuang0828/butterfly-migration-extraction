#!/usr/bin/env python3
"""
Submit a NEW, species-scoped GBIF SQL download instead of the family-wide one
(0001017.../gbif_new_download.csv) - restricted to the 426 known-migratory
species listed in migratory_species_list.txt (extracted from the filenames in
~/Desktop/Phd_Haiyu_LI/Rapoport-s-rule-and-Bergmann-s-rule-of-Migratory-butterflies/
data/SuitabilityMaps_MigratorySpecies/).

This exists because the earlier family-wide download's "taxonkey" column
turned out not to be a usable GBIF taxonKey (cross-checked one row against the
real occurrence record via its gbifID - the values didn't match, and no
base-36/etc transform reproduced it), and neither download included a
species/scientificName column - so there was no way to filter the existing
data to just these species locally. This submits a fresh, narrower query with
`species` included in SELECT and `species IN (...)` in WHERE, so filtering
happens at the source instead of after downloading everything.

Reuses the submit/poll/resumable-download machinery from gbif_redownload.py.

Usage
-----
    python gbif_redownload_species.py
"""

import sys
from pathlib import Path

import gbif_redownload as base

PROJECT_DIR = Path(__file__).parent.parent
DATA_RAW_DIR = PROJECT_DIR / "data" / "raw"
SPECIES_LIST_FILE = DATA_RAW_DIR / "migratory_species_list.txt"
KEY_FILE = DATA_RAW_DIR / ".gbif_download_key_species"
OUTPUT_CSV = DATA_RAW_DIR / "gbif_migratory_species_download.csv"


def build_sql() -> str:
    species = [line.strip() for line in SPECIES_LIST_FILE.read_text().splitlines() if line.strip()]
    if not species:
        sys.exit(f"No species names found in {SPECIES_LIST_FILE}")
    in_list = ", ".join(f"'{s}'" for s in species)
    return f"""
SELECT
  gbifid,
  species,
  decimallatitude,
  decimallongitude,
  "year",
  "month",
  basisofrecord,
  taxonkey,
  family,
  occurrenceRemarks,
  eventRemarks,
  dynamicProperties,
  fieldNotes,
  behavior,
  individualCount,
  organismQuantity,
  organismQuantityType,
  locationRemarks,
  organismRemarks
FROM occurrence
WHERE species IN ({in_list})
  AND hascoordinate = true
  AND (
    (occurrenceRemarks IS NOT NULL AND occurrenceRemarks != '')
    OR (eventRemarks IS NOT NULL AND eventRemarks != '')
    OR (dynamicProperties IS NOT NULL AND dynamicProperties != '')
    OR (fieldNotes IS NOT NULL AND fieldNotes != '')
  )
""".strip()


if __name__ == "__main__":
    base.main(sql=build_sql(), key_file=KEY_FILE, output_csv=OUTPUT_CSV)
