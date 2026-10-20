# Butterfly migration citizen-science data — API extraction pipeline

Extracts structured migration and demographic information (flight direction, wind direction,

quantity, observation unit/rate, sex, life stage, distance, destination, corridor observations)

from free-text remarks in GBIF occurrence records of **426 known migratory butterfly

species**, using a local keyword pre-filter followed by a DeepSeek LLM

extract + reviewer prompt chain.

For detailed methodology, QA logs, and accuracy assessments, see [`doc/methods_summary.md`].

&#x23;# Pipeline overview

GBIF SQL Download API (426 species, has coordinates, non-empty remarks)

│ gbif_redownload_species.py → data/raw/gbif_migratory_species_download.csv (~4.08 M rows)

▼

Local keyword pre-filter (pandas, no API)

│ keyword_filter_species.py → data/interim/deepseek_output_species/classify.jsonl (~43.5 k candidates, 1.06 %)

▼

DeepSeek LLM: extract → reviewer audit

│ deepseek_migration_pipeline.py --stage extract

│ → data/interim/deepseek_output_species/results.jsonl / results.json

▼

Deterministic post-processing & export

build_metadata_csv.py → output/metadata.csv (all candidates, slim columns)

build_verification_csv.py → output/extraction_verification.csv (rows with any extracted info, text side-by-side)

code

Code

&#x23;## 1. Data download — `gbif\_redownload\_species.py` (uses `gbif\_redownload.py`)

- Submits a GBIF SQL download for the species in `data/raw/migratory\_species\_list.txt`,

&#x20; filtered to `hascoordinate = true` and at least one non-empty

&#x20; `occurrenceRemarks / eventRemarks / dynamicProperties / fieldNotes`.

- Polls until ready, downloads and unzips; resumable (download key is cached locally).

&#x23;## 2. Keyword pre-filter — `keyword\_filter\_species.py`

Regex tiers shared with the main pipeline (single source of truth):

- **STRONG** (migrat / dispers / flock / influx …) — sufficient on its own.

- **WEAK** (north / wind / km …) — counts only when co-occurring with an **ANCHOR**

&#x20; (heading / route / tagged / released …).

- **QUANTITY** (individuals / count …) — needs ANCHOR or WEAK co-occurrence.

- **BOILERPLATE** platform templates (e.g. UKBMS transect sentences, "Activity: Flying.")

&#x20; are stripped first.

Reduces raw records (~4.08M) to high-probability candidates (~43.5k, ~1.06%).

&#x23;## 3. LLM extraction — `deepseek\_migration\_pipeline.py --stage extract`

- Model `deepseek-flash`, `temperature=0`, thinking disabled.

- Two calls per record: **extract** then **reviewer**, which audits the extraction

&#x20; against the original text, nulls unsupported values, and disambiguates observer vs. animal movements.

- Target fields include:

&#x20; - Movement: `direction`, `direction\_raw`, `direction\_is\_arrival`, `direction\_degrees` (only if stated in text), `wind\_direction`, `corridor\_observation`, `distance`, `distance\_unit`, `destination`.

&#x20; - Demography & Phenology: `quantity`, `quantity\_raw`, `quantity\_unit`, `quantity\_unit\_raw` (e.g. individuals vs. rates like 'individuals / 10 min'), `sex`, `sex\_raw` (male/female/mixed), `life\_stage`, `life\_stage\_raw` (adult/freshly emerged/larva), and `behaviour\_notes`.

- `direction\_degrees\_computed` is computed by the deterministic

&#x20; `direction\_to\_degrees()` (16-point compass sectors, union for compound

&#x20; directions, reversal for arrival directions) — not by the LLM.

- Cost control: exact + fuzzy content cache with ordered digit signatures to avoid

&#x20; sharing answers between records with different counts. Full run (43,484 records) cost ≈ ¥58.5 CNY (~$8.1 USD).

- Resumable checkpoints; `--sample N` for random QA subsets, `--limit N` for head-of-file tests.

- `requeue\_bad\_uids.py` removes given uids from the checkpoint so they are re-run.

&#x23;## 4. Export — `build\_metadata\_csv.py`, `build\_verification\_csv.py`

- `metadata.csv`: species / family / year / month / coordinates / individualCount

&#x20; + all extracted fields (including `quantity\_unit`, `sex`, `life\_stage`) + `distance\_confidence`.

- `distance\_confidence` is a deterministic rule: distance < 50 m with no

&#x20; migration-context word (migrat / dispers / overwinter / tag / recover / releas /

&#x20; offshore / crossing / corridor / sanctuary) → `low`, otherwise `high`.

- `extraction\_verification.csv`: only records with any non-null extracted trait,

&#x20; original text alongside extracted values, for manual review and QA.

&#x23;# Usage

```bash

pip install -r script/requirements.txt

cp script/config.example.py script/config.py   # fill in DeepSeek key + GBIF account (never commit)



python script/gbif\_redownload\_species.py

python script/keyword\_filter\_species.py \\

&#x20;   --input data/raw/gbif\_migratory\_species\_download.csv \\

&#x20;   --outdir data/interim/deepseek\_output\_species

python script/deepseek\_migration\_pipeline.py --stage extract \\

&#x20;   --outdir data/interim/deepseek\_output\_species --sample 20    # QA smoke test

python script/deepseek\_migration\_pipeline.py --stage extract \\

&#x20;   --outdir data/interim/deepseek\_output\_species                # full run (resumable)

python script/build\_metadata\_csv.py

python script/build\_verification\_csv.py

The DeepSeek key can also be supplied via the DEEPSEEK\_API\_KEY environment

variable or --api-key.

**Accuracy (stratified manual review, \~150–200 records)**

Field	Est. accuracy

quantity / quantity\_unit	\~99 %+

direction / wind\_direction	\~98 %+

sex / life\_stage	\~98 %+ 

corridor\_observation	\~95 %+

destination	\~90–95 %

distance (long, km/mi)	\~98 %+

distance (short, < \~50 m)	\~35–40 % 

**Repository contents**

Raw GBIF downloads, LLM checkpoints, and output CSVs are not included (due to file size;

regenerate with the scripts above). script/config.py holding personal credentials is gitignored.

```

