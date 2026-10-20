#!/usr/bin/env python3
"""
Re-submit the original GBIF SQL download (0001017-260916113435855) with extra
free-text/behaviour columns added, via the GBIF Download API, then poll until
it's ready and save the result into this project directory.

Reproduces the exact filter from the original download's own metadata
(fetched from https://api.gbif.org/v1/occurrence/download/0001017-260916113435855):

    WHERE family IN ('Papilionidae','Pieridae','Nymphalidae','Lycaenidae',
                      'Hesperiidae','Riodinidae')
      AND hascoordinate = true
      AND occurrenceRemarks IS NOT NULL AND occurrenceRemarks != ''

...but relaxes the last line to "any of occurrenceRemarks / eventRemarks /
dynamicProperties / fieldNotes is non-empty" (the whole point of the
re-download), and adds a few more free-text/structured fields found via
GET /v1/occurrence/download/describe/sql that are also plausible carriers of
flight/migration/behaviour info: behavior, individualCount, organismQuantity,
organismQuantityType, locationRemarks, organismRemarks, plus gbifID so future
downloads can be diffed by ID instead of a content signature.

Usage
-----
    1. Fill in GBIF_USER / GBIF_PASSWORD / GBIF_NOTIFICATION_EMAIL in config.py
    2. python gbif_redownload.py

Polls every 60s (download prep is usually minutes, can be longer under load).
Safe to Ctrl-C and re-run - if a download key is already saved in
.gbif_download_key it resumes polling that one instead of submitting a new
request.
"""

import functools
import json
import sys
import time
import zipfile
from pathlib import Path

print = functools.partial(print, flush=True)  # stdout is block-buffered when redirected to a log file

import requests

try:
    from config import GBIF_USER, GBIF_PASSWORD, GBIF_NOTIFICATION_EMAIL
except ImportError:
    sys.exit("Fill in GBIF_USER / GBIF_PASSWORD / GBIF_NOTIFICATION_EMAIL in config.py first.")

PROJECT_DIR = Path(__file__).parent.parent
DATA_RAW_DIR = PROJECT_DIR / "data" / "raw"
OLD_DOWNLOAD_KEY = "0001017-260916113435855"
KEY_FILE = DATA_RAW_DIR / ".gbif_download_key"
OUTPUT_CSV = DATA_RAW_DIR / "gbif_new_download.csv"  # .csv for consistency, though it's tab-delimited like the original

SQL = """
SELECT
  gbifid,
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
WHERE family IN ('Papilionidae', 'Pieridae', 'Nymphalidae', 'Lycaenidae', 'Hesperiidae', 'Riodinidae')
  AND hascoordinate = true
  AND (
    (occurrenceRemarks IS NOT NULL AND occurrenceRemarks != '')
    OR (eventRemarks IS NOT NULL AND eventRemarks != '')
    OR (dynamicProperties IS NOT NULL AND dynamicProperties != '')
    OR (fieldNotes IS NOT NULL AND fieldNotes != '')
  )
""".strip()

API = "https://api.gbif.org/v1/occurrence/download"


def submit(sql: str, key_file: Path) -> str:
    body = {
        "sendNotification": True,
        "notificationAddresses": [GBIF_NOTIFICATION_EMAIL],
        "format": "SQL_TSV_ZIP",
        "sql": sql,
    }
    resp = requests.post(
        f"{API}/request",
        auth=(GBIF_USER, GBIF_PASSWORD),
        headers={"Content-Type": "application/json"},
        data=json.dumps(body),
    )
    resp.raise_for_status()
    key = resp.text.strip()
    key_file.write_text(key)
    print(f"Submitted. Download key: {key}")
    return key


def poll(key: str) -> dict:
    while True:
        resp = requests.get(f"{API}/{key}")
        resp.raise_for_status()
        info = resp.json()
        status = info.get("status")
        print(f"[{time.strftime('%H:%M:%S')}] status={status}")
        if status == "SUCCEEDED":
            return info
        if status in ("KILLED", "FAILED", "CANCELLED"):
            sys.exit(f"Download {key} ended with status={status}: {info}")
        time.sleep(60)


DOWNLOAD_MAX_RETRIES = 20  # the connection has been dropping mid-transfer on a slow link


def download_resumable(url: str, dest: Path, expected_size: int) -> None:
    """Stream url -> dest, resuming via HTTP Range on any connection error
    instead of restarting from byte 0 - important on a slow/flaky link where a
    425MB download can drop several times before finishing."""
    for attempt in range(1, DOWNLOAD_MAX_RETRIES + 1):
        have = dest.stat().st_size if dest.exists() else 0
        if expected_size and have >= expected_size:
            return
        headers = {"Range": f"bytes={have}-"} if have else {}
        mode = "ab" if have else "wb"
        try:
            with requests.get(url, stream=True, headers=headers, timeout=30) as r:
                if have and r.status_code == 200:
                    # server ignored our Range request - it's sending the whole
                    # file again, so we must start this attempt over from 0.
                    have = 0
                    mode = "wb"
                elif r.status_code not in (200, 206):
                    r.raise_for_status()
                with open(dest, mode) as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
            got = dest.stat().st_size
            if expected_size and got < expected_size:
                raise IOError(f"incomplete: got {got} of {expected_size} bytes")
            return
        except (requests.exceptions.RequestException, IOError, OSError) as e:
            got = dest.stat().st_size if dest.exists() else 0
            pct = (got / expected_size * 100) if expected_size else 0
            print(f"Download interrupted (attempt {attempt}/{DOWNLOAD_MAX_RETRIES}, "
                  f"{got/1e6:.1f}MB / {expected_size/1e6:.1f}MB = {pct:.0f}%): {e}")
            if attempt == DOWNLOAD_MAX_RETRIES:
                raise
            time.sleep(min(30, 2 * attempt))


def fetch_and_extract(info: dict, output_csv: Path) -> Path:
    zip_url = info["downloadLink"]
    zip_path = DATA_RAW_DIR / f"{info['key']}.zip"
    expected_size = info.get("size", 0)
    print(f"Downloading {zip_url} -> {zip_path} ({expected_size / 1e6:.1f} MB)")
    download_resumable(zip_url, zip_path, expected_size)

    with zipfile.ZipFile(zip_path) as z:
        # SQL_TSV_ZIP downloads contain a single .tsv/.csv data file (plus
        # citation/metadata files we don't need).
        data_members = [n for n in z.namelist() if n.lower().endswith((".tsv", ".csv"))]
        if not data_members:
            sys.exit(f"No .tsv/.csv found inside {zip_path}: {z.namelist()}")
        member = data_members[0]
        with z.open(member) as src, open(output_csv, "wb") as dst:
            dst.write(src.read())
    zip_path.unlink()
    print(f"Saved -> {output_csv}")
    return output_csv


def main(sql: str = SQL, key_file: Path = KEY_FILE, output_csv: Path = OUTPUT_CSV) -> None:
    if key_file.exists():
        key = key_file.read_text().strip()
        print(f"Resuming existing download request: {key}")
    else:
        key = submit(sql, key_file)
    info = poll(key)
    fetch_and_extract(info, output_csv)
    key_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
