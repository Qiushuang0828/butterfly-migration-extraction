#!/usr/bin/env python3
"""Remove specific uids from an extract-stage checkpoint (results.jsonl) so
they get reprocessed on the next `--stage extract` run.

Part of the staged QA workflow: run a random --sample batch, audit it, fix
the prompt if a bug is found, then requeue just the affected rows from that
batch (not the whole batch) so they re-run under the fixed prompt while
everything already-correct stays cached.

Usage
-----
    python script/requeue_bad_uids.py --outdir data/interim/deepseek_output_species uid1 uid2 ...
    python script/requeue_bad_uids.py --outdir data/interim/deepseek_output_species --uids-file bad_uids.txt
"""
import argparse
import json
import sys
from pathlib import Path

OLD_FORMAT_DEFAULT_SOURCE = "gbif_migratory_species_download.csv"


def rec_uid(rec: dict) -> str:
    uid = rec.get("uid")
    if uid:
        return uid
    source = rec.get("sourceFile") or OLD_FORMAT_DEFAULT_SOURCE
    return f"{source}:{rec['row_id']}"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--outdir", required=True)
    p.add_argument("--uids-file", default=None, help="File with one uid per line")
    p.add_argument("uids", nargs="*", help="uids to requeue")
    args = p.parse_args()

    uids = set(args.uids)
    if args.uids_file:
        uids |= {line.strip() for line in Path(args.uids_file).read_text().splitlines() if line.strip()}
    if not uids:
        sys.exit("No uids given.")

    jsonl_path = Path(args.outdir) / "results.jsonl"
    if not jsonl_path.exists():
        sys.exit(f"{jsonl_path} not found.")

    kept = []
    removed = 0
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec_uid(rec) in uids:
                removed += 1
                continue
            kept.append(line)

    jsonl_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    print(f"Removed {removed}/{len(uids)} requested uids from {jsonl_path} - "
          f"they'll be reprocessed on the next extract run.")
    if removed < len(uids):
        print(f"Note: {len(uids) - removed} requested uids were not found in the checkpoint.")


if __name__ == "__main__":
    main()
