# Butterfly Migration Trait Extraction Pipeline — Methodology & Validation Summary

## 1. Data Source and Taxonomic Scope

* **Data Source**: Global Biodiversity Information Facility (GBIF) occurrence database, retrieved via the official SQL Download API.

* **Taxonomic Scope**: 426 known migratory butterfly species (compiled from published migratory inventories and suitability map directories), avoiding unnecessary processing of non-migratory taxa.

* **Inclusion Criteria**: `hascoordinate = true` AND at least one non-empty field among `occurrenceRemarks`, `eventRemarks`, `dynamicProperties`, or `fieldNotes`.

* **Query Download Results**: **4,085,985 records** across 19 Darwin Core and behavioral fields (Download Key: `0036328-260928105237408`).

***

## 2. Two-Stage Processing Pipeline

### Stage 1: Local Multilingual Keyword Pre-Filtering (keyword_filter_species.py)

Executed locally in Pandas using local computation. Employs a multi-tier regex matching architecture across 10 European languages:

* **STRONG Tier**: Migration- and flight-specific verbs/nouns (`migrat*`, `dispers*`, `thermal*`, `updraft`, `influx`, `swarm*`, `flock*`, `vuelo`, `volant`, `trekk*`, `flug*`, etc.). Triggers candidate status standalone.

* **WEAK Tier**: Compass headings, wind terms, and distance units (`north*`, `south*`, `east*`, `west*`, `tailwind`, `km`, `mph`, `miles`, `meters`, `nord`, `sud`, `vento`). Prone to false positives in survey narratives; requires co-occurrence with an ANCHOR term.

* **ANCHOR Tier**: Locomotion, tracking, and tag-recovery verbs (`heading`, `route`, `bearing`, `compass`, `transect`, `travel*`, `track*`, `crossing`, `tagged`, `recovered`, `released`).

* **QUANTITY Tier**: Group count nouns (`individuals`, `specimens`, `counted`, `exemplaires`, `indivíduos`). Prone to specimen catalog noise; requires co-occurrence with an ANCHOR term.

* **BOILERPLATE Stripping**: Strips standardized monitoring templates (e.g., UKBMS transect summaries, bare Darwin Core tags such as `"Activity: Flying."` or isolated `"Flying"`) prior to evaluation.

**Filtering Outcome**: Reduced 4,085,985 raw occurrence records to **43,484 high-probability candidate records (1.06% hit rate)**, exported to `classify.jsonl`.

### Stage 2: DeepSeek LLM Information Extraction (deepseek_migration_pipeline.py --stage extract)

* **Model Engine**: `deepseek-flash`, `temperature=0`, thinking mode explicitly disabled for deterministic factual transcription.

* **Dual-Agent Verification**: Every candidate undergoes a two-call prompt chain: **Extractor (Agent 1) + Independent Reviewer (Agent 2)**. The Reviewer conducts a 100% full-coverage audit against the original text, actively nulling hallucinations and overreach.

* **Extraction Schema (22 Structured Attributes)**:

  * *Locomotion & Heading*: `direction`, `direction_raw`, `direction_is_arrival`, `direction_degrees` (transcribed numeric bearings only), `wind_direction`, `wind_direction_raw`, `corridor_observation`, `corridor_observation_raw`.

  * *Demographic & Phenological Traits (Newly Extended)*: `quantity`, `quantity_raw`, `quantity_unit`, `quantity_unit_raw` (differentiates total counts from rates like `individuals / 10 min` or `per hour`), `sex`, `sex_raw` (`male`, `female`, `mixed`), `life_stage`, `life_stage_raw` (`adult`, `freshly emerged`, `larva`, `pupa`), and `behaviour_notes` (concise English summary <= 15 words).

  * *Dispersal & Scale*: `distance`, `distance_unit`, `distance_raw`, `destination`, `destination_raw`.

* **Deterministic Heading Computation**: `direction_degrees_computed` (`mid`, `min`, `max`) is calculated via Python sector-union geometry (`_sector_union_mid`), applying a +180° reciprocal transformation for arrival bearings. It is never estimated by the LLM.

### Computational Performance and Efficiency

* **Ordered Digit-Signature Cache**: Fuzzy text matching requires identical digit sequences in identical order to prevent template records with differing counts from cross-contaminating answers.

* **Production Execution Metrics**: Across 43,484 candidates, 28,207 required live model calls, while 15,257 were served directly from cache (avoiding >35% redundant processing).

* **Audit Statistics**: Agent 2 performed **56,414 total model calls** ($28,207 \times 2$) and executed **9,268 active reviewer interventions/corrections**.

* **Runtime and Robustness**: Completed in ~67 minutes (~7 rows/s) with **0 fatal errors**.

***

## 3. Disambiguation Rules and Quality Assurance

### Rule 1: Observer vs. Animal Disambiguation

* **Target Fields**: `direction`, `distance`, `destination`

* **Implementation**: Explicit negative constraints in prompt: human routes (*"walked 2 miles north"*) are strictly excluded; values are nulled unless movement is explicitly attributed to the butterfly.

### Rule 2: Demographic Inference Suppression

* **Target Fields**: `sex`, `life_stage`

* **Implementation**: Strict grounding rule: models are forbidden from inferring adult stage or sex purely from flight behavior. Explicit textual evidence is required; otherwise nulled.

### Rule 3: Observation Rate Disambiguation

* **Target Fields**: `quantity_unit`

* **Implementation**: Accurately captures both total cumulative counts (`individuals`) and temporal passage rates (e.g., `5 individuals / 10 min`, `per hour`).

### Rule 4: Locality and Micro-habitat Exclusion

* **Target Fields**: `destination`

* **Implementation**: Excludes observation site names and trivial micro-scale moves (e.g., perching on flowers, fences, or watering cans).

### Rule 5: Local Trivial Repositioning (<50m)

* **Target Fields**: `distance`, `distance_confidence`

* **Implementation**: Flights <50m without migratory context are flagged deterministically as `low` confidence; true dispersal and tag-recoveries are scored as `high`.

***

## 4. Deliverable Files and Schemas

### 1. Primary Analysis Dataset (output/metadata.csv, 43,484 rows)

Full dataset containing GBIF identifiers, taxonomy, temporal attributes, coordinates, and all 22 extracted/audited traits alongside `distance_confidence`. Optimized for spatial GIS plotting, realm comparisons (Temperate vs. Tropics), and trait distributions.

### 2. QA Subset Table (output/extraction_verification.csv, ~4.7k rows)

Contains only records with positive extractions. Pairs `original_text` side-by-side with extracted fields, raw evidence snippets, and the reviewer correction log (`review_corrections`) for manual spot-checking and audit transparency.

### 3. Deterministic distance_confidence Scoring Rule

&#x23;## Rule 1: Observer vs. Animal Disambiguation - **Target Fields**: `direction`, `distance`, `destination` - **Implementation**: Explicit negative constraints in prompt: human routes (*"walked 2 miles north"*) are strictly excluded; values are nulled unless movement is explicitly attributed to the butterfly.&#x20;

&#x23;## Rule 2: Demographic Inference Suppression - **Target Fields**: `sex`, `life_stage` - **Implementation**: Strict grounding rule: models are forbidden from inferring adult stage or sex purely from flight behavior. Explicit textual evidence is required; otherwise nulled.&#x20;

&#x23;## Rule 3: Observation Rate Disambiguation - **Target Fields**: `quantity_unit` - **Implementation**: Accurately captures both total cumulative counts (`individuals`) and temporal passage rates (e.g., `5 individuals / 10 min`, `per hour`).&#x20;

&#x23;## Rule 4: Locality and Micro-habitat Exclusion - **Target Fields**: `destination` - **Implementation**: Excludes observation site names and trivial micro-scale moves (e.g., perching on flowers, fences, or watering cans).&#x20;

&#x23;## Rule 5: Local Trivial Repositioning (<50m) - **Target Fields**: `distance`, `distance_confidence` - **Implementation**: Flights <50m without migratory context are flagged deterministically as `low` confidence; true dispersal and tag-recoveries are scored as `high`.&#x20;

## 5. Script Inventory

* gbif_redownload_species.py: Automated species-scoped GBIF SQL download pipeline.

* keyword_filter_species.py: Multilingual Pandas regex pre-filtering.

* deepseek_migration_pipeline.py --stage extract: Two-stage LLM extraction and review chain.

* build_metadata_csv.py: Generates the primary analysis dataset (output/metadata.csv).

* build_verification_csv.py: Generates the audit verification table (output/extraction_verification.csv).

* requeue_bad_uids.py: Utility to un-checkpoint specific records for prompt iteration.

