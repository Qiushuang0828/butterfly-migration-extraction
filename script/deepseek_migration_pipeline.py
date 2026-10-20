#!/usr/bin/env python3
"""
DeepSeek prompt-chain pipeline for butterfly migration/dispersal note mining.

Updated with:
- quantity_unit (e.g. 'individuals', '5 individuals / 10 minutes')
- sex (e.g. 'male', 'female', 'mixed')
- life_stage (e.g. 'adult', 'freshly emerged', 'larva')
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime
import difflib
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from openai import (
    AsyncOpenAI,
    APIError,
    APIConnectionError,
    APIStatusError,
    RateLimitError,
)

try:
    from config import DEEPSEEK_API_KEY
except ImportError:
    DEEPSEEK_API_KEY = None

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-flash"

DEFAULT_INPUT = "data/raw/0001017-260916113435855.csv"
DEFAULT_OUTDIR = "data/interim/deepseek_output"
CSV_DELIMITER = "\t"

FREETEXT_COLUMNS = [
    ("occurrenceremarks", "occurrenceRemarks"),
    ("eventremarks", "eventRemarks"),
    ("fieldnotes", "fieldNotes"),
    ("behavior", "behavior"),
]

STRUCTURED_COLUMNS = [
    ("locationremarks", "locationRemarks"),
    ("organismremarks", "organismRemarks"),
    ("dynamicproperties", "dynamicProperties"),
    ("individualcount", "individualCount"),
    ("organismquantity", "organismQuantity"),
    ("organismquantitytype", "organismQuantityType"),
]
NOTE_COLUMNS = FREETEXT_COLUMNS + STRUCTURED_COLUMNS

DEFAULT_CONCURRENCY = 20
MAX_TOKENS = 600
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0

csv.field_size_limit(sys.maxsize)

_STRONG_KEYWORDS = [
    r"\bfl(y|ies|ying|ight|ew|own)\w*", r"migrat\w*", r"dispers\w*", r"thermal\w*",
    r"updraft", r"passage", r"influx", r"invasion\w*", r"wander\w*", r"vagran\w*",
    r"stray\w*", r"immigra\w*", r"emigra\w*", r"overflying", r"swarm\w*", r"\bflock\w*",
    r"vol(e|er|ant|é)?\w*", r"migrat(ion|eur|oire)\w*", r"dispersion\w*", r"errant\w*",
    r"vuel(o|a|an|ando)\w*", r"migraci[óo]n\w*", r"migra[çc][ãa]o\w*", r"dispersi[óo]n\w*",
    r"vol(o|are|ando)\w*", r"migrazion\w*", r"dispersion\w*",
    r"\bfly(r|ging|tur|ndel?)?\w*", r"trekk\w*", r"migrasjon\w*", r"migration\w*",
    r"spredning\w*", r"flyttning\w*", r"flyt\w*",
    r"flug\w*", r"flieg\w*", r"zug\w*", r"ausbreitung\w*",
    r"vlieg\w*", r"trek\w*", r"verspreiding\w*",
    r"lent[äo]\w*", r"lensi\w*", r"lenno\w*", r"lentäv\w*", r"muutt\w*", r"vaelt\w*",
]

_WEAK_KEYWORDS = [
    r"direction\w*", r"north\w*", r"south\w*", r"east\w*", r"west\w*",
    r"northeast\w*", r"northwest\w*", r"southeast\w*", r"southwest\w*",
    r"\bN\b", r"\bS\b", r"\bE\b", r"\bW\b", r"\bNE\b", r"\bNW\b", r"\bSE\b", r"\bSW\b",
    r"wind\w*", r"tailwind", r"\bkm\b", r"\bkm/h\b", r"\bmph\b", r"\bmi\b",
    r"\bmiles?\b", r"\bmeters?\b", r"\bmetres?\b", r"\byards?\b", r"distance\w*",
    r"nord\w*", r"sud\w*", r"\best\b", r"ouest\w*", r"nord-est", r"nord-ouest",
    r"sud-est", r"sud-ouest", r"distance\w*", r"vent\b",
    r"direc[çc][ãa]o\w*", r"direcci[óo]n\w*", r"norte\w*", r"sur\b", r"sul\b",
    r"este\b", r"oeste\w*", r"leste\w*", r"distancia\w*", r"dist[âa]ncia\w*",
    r"vento\b", r"viento\b",
    r"direzione\w*", r"nord\w*", r"sud\w*", r"est\b", r"ovest\w*", r"distanza\w*",
    r"retning\w*", r"nord\w*", r"s[øo]r\w*", r"[øo]st\w*", r"vest\w*",
    r"vind\b", r"avstand\w*",
    r"richtung\w*", r"norden?\b", r"s[üu]den?\b", r"osten?\b", r"westen?\b",
    r"nordost\w*", r"nordwest\w*", r"s[üu]dost\w*", r"s[üu]dwest\w*",
    r"entfernung\w*", r"distanz\w*", r"wind\w*",
    r"richting\w*", r"noord\w*", r"zuid\w*", r"oost\w*", r"west\w*", r"afstand\w*",
    r"suunta\w*", r"pohjois\w*", r"etel[äa]\w*", r"it[äa]\w*", r"l[äa]nsi\w*",
    r"et[äa]isyys\w*",
]

_ANCHOR_KEYWORDS = [
    r"headin?g", r"mov(e|es|ed|ing|ement)\w*", r"route\w*",
    r"bearing", r"azimuth", r"compass", r"transect\w*",
    r"travel(l)?(ed|ing|s)?", r"journey\w*", r"en\s?route", r"track(ed|ing)?",
    r"crossing\w*", r"trajet\w*", r"itinéraire",
    r"\btag(ged|ging)?\w*", r"recover(ed|y|ies)?\w*", r"releas(e|ed|ing)\w*",
    r"flapping", r"patrolling",
]

_QUANTITY_KEYWORDS = [
    r"\bind(s|ividuals?)?\.?\b", r"specimens?", r"counted", r"count\b",
    r"\bnumbers?\b\s+of", r"individus?", r"exemplaires?", r"indiv[íi]duos?",
    r"ejemplares?", r"individui", r"antall\b", r"individ\w*", r"individuen", r"exemplare",
]

_STRONG_RE = re.compile("|".join(_STRONG_KEYWORDS), re.IGNORECASE)
_WEAK_RE = re.compile("|".join(_WEAK_KEYWORDS), re.IGNORECASE)
_QUANTITY_RE = re.compile("|".join(_QUANTITY_KEYWORDS), re.IGNORECASE)
_ANCHOR_RE = re.compile("|".join(_ANCHOR_KEYWORDS), re.IGNORECASE)

_BOILERPLATE_RE = re.compile(
    r"the number of individuals observed is the sum total from the "
    r"(?:surveyed segments of the )?(?:transect|whole point) site\.?"
    r"|transect section \d+ count\.?"
    r"|activity:\s*flying\.?"
    r"|\bfree-flying\b"
    r"|^\s*(?:flying|fly|flew|vuelo|al\s+vuelo|en\s+vuelo|volando)\.?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_IGNORE_VALUES = {"", "wgs84", "n/a", "na", "none", "null"}


def passes_local_prefilter(remarks: str) -> bool:
    if not remarks:
        return False
    val = remarks.strip()
    if val.lower() in _IGNORE_VALUES:
        return False
    val = _BOILERPLATE_RE.sub(" ", val).strip()
    if not val:
        return False
    if _STRONG_RE.search(val):
        return True
    if _ANCHOR_RE.search(val) and (_WEAK_RE.search(val) or _QUANTITY_RE.search(val)):
        return True
    return False


CLASSIFY_SYSTEM = """Screen a citizen-science butterfly occurrence note (any European language) \
for FLIGHT, MIGRATION, or DISPERSAL info: direction of movement, migratory flight, dispersal \
distance, group counts seen flying/migrating together, wind-assisted movement, flight route/corridor.

NOT relevant: habitat, host plant, ID method, unrelated weather, locality, determination \
confidence - unless movement/flight/migration is also described.

STRICT JSON only, no prose:
{"relevant": true|false, "confidence": <0-1>, "reason": "<short, English>"}
"""

CLASSIFY_REVIEW_SYSTEM = """Audit another model's relevant/irrelevant call for a butterfly field \
note (relevant = describes flight/migration/dispersal: direction, distance, group counts, \
wind-assisted movement, route/corridor).

Check against the ORIGINAL TEXT only, no outside knowledge:
- relevant=true and correct -> keep
- relevant=true but nothing in the text supports it -> correct to false
- relevant=false but the text does describe it -> correct to true

STRICT JSON only, no prose:
{"relevant": true|false, "confidence": <0-1>, "reason": "<short, English>",
 "verified": true|false, "corrections": "<what changed, or null>"}

verified=true only if nothing needed correcting.
"""

_CARDINAL_DEGREES = {
    "n": 0, "north": 0,
    "ne": 45, "northeast": 45,
    "e": 90, "east": 90,
    "se": 135, "southeast": 135,
    "s": 180, "south": 180,
    "sw": 225, "southwest": 225,
    "w": 270, "west": 270,
    "nw": 315, "northwest": 315,
    "nne": 22.5, "northnortheast": 22.5,
    "ene": 67.5, "eastnortheast": 67.5,
    "ese": 112.5, "eastsoutheast": 112.5,
    "sse": 157.5, "southsoutheast": 157.5,
    "ssw": 202.5, "southsouthwest": 202.5,
    "wsw": 247.5, "westsouthwest": 247.5,
    "wnw": 292.5, "westnorthwest": 292.5,
    "nnw": 337.5, "northnorthwest": 337.5,
}
_CARDINAL_TOKEN_RE = re.compile(
    r"\b(?:" + "|".join(sorted(_CARDINAL_DEGREES, key=len, reverse=True)) + r")\b", re.IGNORECASE
)


def _sector_union_mid(cardinal_words: list) -> Optional[tuple]:
    angles = [_CARDINAL_DEGREES[w] for w in cardinal_words if w in _CARDINAL_DEGREES]
    if not angles:
        return None
    base = angles[0]
    rel = [((a - base + 180) % 360) - 180 for a in angles]
    lo, hi = min(rel) - 22.5, max(rel) + 22.5
    mid = (base + (lo + hi) / 2) % 360
    return mid, (base + lo) % 360, (base + hi) % 360


def direction_to_degrees(direction, is_arrival: bool = False) -> Optional[dict]:
    if not direction or not isinstance(direction, str):
        return None
    tokens = [t.lower() for t in _CARDINAL_TOKEN_RE.findall(direction)]
    seen, words = set(), []
    for t in tokens:
        key = t.replace("-", "")
        if key not in seen:
            seen.add(key)
            words.append(key)
    result = _sector_union_mid(words)
    if result is None:
        return None
    mid, lo, hi = result
    if is_arrival:
        mid, lo, hi = (mid + 180) % 360, (lo + 180) % 360, (hi + 180) % 360
    return {"mid": mid, "min": lo, "max": hi}


EXTRACT_SYSTEM = """This is a direct data-extraction task, not a reasoning task: read the note \
once, transcribe what it literally says into the fields below, do not think step by step, do \
not explain your reasoning, do not add any text before or after the JSON object.

Extract structured migration/dispersal info from a butterfly field note (any \
language; keep original wording in the *_raw fields), aimed at flyway analysis (direction/ \
distance/destination of movement). If present in the text:

IMPORTANT - observer vs. animal: field notes routinely narrate the OBSERVER's own walk, hike, \
drive, or survey route ("walked from the trailhead to the ridge", "drove west along the coast \
road", "traveled to Port Williams") in the same sentence as, or instead of, anything about the \
butterfly. None of direction/distance/destination below may be filled from the observer's own \
movement, route, or destination - only from movement explicitly attributed to the animal itself \
(it flew/migrated/headed/was tagged-recovered-released at). If a clause's subject is the person \
("I", "we", a named observer, or an implied narrator walking/driving/surveying) rather than the \
butterfly, that clause is not a source for these fields, even if it contains a compass word, a \
distance, or a place name. When in doubt about whose movement a clause describes, use null.

- direction / direction_raw: compass word(s) for the ANIMAL's HEADING - the direction it is \
  travelling TOWARD (e.g. "north", "southeast and east"), or null. Do not use wind direction \
  here, and do not use a direction that belongs to the observer's own walking/driving route.
- direction_is_arrival: true if the text actually describes where the animal came FROM (e.g. \
  "arrived from the west") rather than where it's heading - the heading is the reciprocal of \
  this, which will be computed downstream, not by you. false/null if the text already describes \
  a heading (the normal case) or no direction is given.
- direction_degrees / direction_degrees_raw: a numeric bearing in degrees (0-360) ONLY if the \
  text literally states one (e.g. "bearing 210", "heading 45 degrees") - null otherwise. \
  NEVER infer/convert a degree value from a cardinal direction word yourself.
- wind_direction / wind_direction_raw: compass word for WIND direction if mentioned, kept \
  separate from `direction` since butterflies often fly into the wind, not with it - null if \
  not mentioned or if the note doesn't distinguish wind from flight direction.
- corridor_observation / corridor_observation_raw: true (with the supporting snippet) if the \
  observation was made along a river, road, valley, or other linear corridor that could bias \
  the apparent direction versus true open-area flight - false/null if not described as a corridor.
- quantity / quantity_raw: count of individuals (integer, or "many"/"few" etc.), or null.
- quantity_unit / quantity_unit_raw: unit, duration, or observation rate corresponding to the \
  count (e.g. "individuals", "individuals / 10 min", "per hour", "over 3 days", "clusters"). \
  If it is just a plain total count of butterflies, output "individuals". If it is a passage rate \
  or count per time window (e.g., "5 in 10 minutes", "100/hr"), record that rate/duration unit. \
  Output null if no quantity is mentioned.
- sex / sex_raw: biological sex of the butterfly/butterflies if explicitly stated \
  ("male", "female", "mixed", or local language equivalent), or null if not mentioned.
- life_stage / life_stage_raw: developmental stage, freshness, or condition if mentioned \
  (e.g., "adult", "freshly emerged", "teneral", "worn", "caterpillar", "larva", "pupa"), \
  or null if not mentioned.
- distance / distance_unit / distance_raw: numeric distance the ANIMAL itself moved, flew, or \
  was recovered from (e.g. "flew approximately 5km", "recovered 300 miles from the tagging \
  site"), or null. Do NOT use observer's survey effort (e.g. "walked 2 miles"). Null for trivial \
  same-scene movement (< 50m / 150ft between flowers/perches) unless framed as migration/water-crossing/tag-recovery.
- destination / destination_raw: named place the ANIMAL was heading toward or recovered at, distinct \
  from the observation locality itself - null otherwise.
- behaviour_notes: one English sentence, max 15 words, summarizing the behaviour, or null.

Output ONLY the JSON object below, exactly these 22 keys, nothing else:
{"direction": ..., "direction_raw": ..., "direction_is_arrival": ...,
 "direction_degrees": ..., "direction_degrees_raw": ...,
 "wind_direction": ..., "wind_direction_raw": ...,
 "corridor_observation": ..., "corridor_observation_raw": ...,
 "quantity": ..., "quantity_unit": ..., "quantity_unit_raw": ..., "quantity_raw": ...,
 "sex": ..., "sex_raw": ...,
 "life_stage": ..., "life_stage_raw": ...,
 "distance": ..., "distance_unit": ..., "distance_raw": ...,
 "destination": ..., "destination_raw": ..., "behaviour_notes": ...}
"""

EXTRACT_REVIEW_SYSTEM = """This is a direct verification task, not a reasoning task: check each \
field against the text once, do not think step by step, do not explain your reasoning, do not \
add any text before or after the JSON object.

Audit an EXTRACTION against the ORIGINAL field note, no outside \
knowledge:
- field correct & supported by the text -> keep
- field wrong, hallucinated, or unsupported -> fix it (null if nothing supports it)
- never invent new info the extraction/text didn't already have
- observer vs. animal: direction/distance/destination must describe the ANIMAL's own movement,
  never the observer's own walk/hike/drive/survey route.
- direction_degrees must be null unless the original text literally states a numeric bearing.
- direction must be the animal's heading, not wind direction.
- direction_is_arrival must be true only when the text literally describes provenance.
- corridor_observation must be true only when the text actually names a linear corridor.
- sex and life_stage must strictly be stated in the text. NEVER infer sex or assume adult \
  just because the insect was flying. If not explicitly supported, set to null.
- quantity_unit must reflect the text: total count vs. rate/duration (e.g., "per 10 minutes").
- distance must describe the ANIMAL's own movement, never observer's survey effort.
- distance and destination must be migration/dispersal-scale, not a trivial same-scene move.
- destination must not be the observation locality's own name.
- behaviour_notes must be at most 15 words.

Output ONLY the JSON object below, nothing else:
{"direction": ..., "direction_raw": ..., "direction_is_arrival": ...,
 "direction_degrees": ..., "direction_degrees_raw": ...,
 "wind_direction": ..., "wind_direction_raw": ...,
 "corridor_observation": ..., "corridor_observation_raw": ...,
 "quantity": ..., "quantity_unit": ..., "quantity_unit_raw": ..., "quantity_raw": ...,
 "sex": ..., "sex_raw": ...,
 "life_stage": ..., "life_stage_raw": ...,
 "distance": ..., "distance_unit": ..., "distance_raw": ...,
 "destination": ..., "destination_raw": ..., "behaviour_notes": ...,
 "verified": true|false, "corrections": "<what changed, or null>"}

verified=true only if nothing needed correcting.
"""


def build_classify_messages(remarks: str, family: str) -> list[dict]:
    return [
        {"role": "system", "content": CLASSIFY_SYSTEM},
        {"role": "user", "content": f"Family: {family or 'unknown'}\nNote: {remarks}"},
    ]


def build_classify_review_messages(remarks: str, family: str, classification: dict) -> list[dict]:
    return [
        {"role": "system", "content": CLASSIFY_REVIEW_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Family: {family or 'unknown'}\n"
                f"ORIGINAL NOTE:\n{remarks}\n\n"
                f"CLASSIFICATION (JSON):\n{json.dumps(classification, ensure_ascii=False)}"
            ),
        },
    ]


def build_extract_messages(remarks: str, family: str) -> list[dict]:
    return [
        {"role": "system", "content": EXTRACT_SYSTEM},
        {"role": "user", "content": f"Family: {family or 'unknown'}\nNote: {remarks}"},
    ]


def build_extract_review_messages(remarks: str, extraction: dict) -> list[dict]:
    return [
        {"role": "system", "content": EXTRACT_REVIEW_SYSTEM},
        {
            "role": "user",
            "content": (
                f"ORIGINAL NOTE:\n{remarks}\n\n"
                f"EXTRACTION (JSON):\n{json.dumps(extraction, ensure_ascii=False)}"
            ),
        },
    ]


@dataclass
class Row:
    row_id: int
    decimallatitude: str
    decimallongitude: str
    year: str
    month: str
    basisofrecord: str
    taxonkey: str
    family: str
    species: str = ""
    occurrenceremarks: str = ""
    eventremarks: str = ""
    dynamicproperties: str = ""
    fieldnotes: str = ""
    behavior: str = ""
    locationremarks: str = ""
    organismremarks: str = ""
    individualcount: str = ""
    organismquantity: str = ""
    organismquantitytype: str = ""
    gbifid: str = ""
    source_file: str = ""

    def uid(self) -> str:
        gid = self.gbifid.strip()
        return gid if gid else f"{self.source_file}:{self.row_id}"

    def notes_text(self) -> str:
        parts = []
        for col, label in NOTE_COLUMNS:
            val = getattr(self, col).strip()
            if val and val.lower() not in _IGNORE_VALUES:
                parts.append(f"{label}: {val}")
        return "\n".join(parts)

    def prefilter_text(self) -> str:
        parts = []
        for col, _label in FREETEXT_COLUMNS:
            val = getattr(self, col).strip()
            if val and val.lower() not in _IGNORE_VALUES:
                parts.append(val)
        return "\n".join(parts)

    def signature(self) -> tuple:
        return (
            self.decimallatitude, self.decimallongitude, self.year, self.month,
            self.taxonkey, self.occurrenceremarks.strip(),
        )


def is_deepseek_peak_now() -> bool:
    beijing = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(beijing)
    if now.weekday() >= 5:
        return False
    return (9 <= now.hour < 12) or (14 <= now.hour < 18)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    calls: int = 0

    def add(self, resp_usage) -> None:
        if resp_usage is None:
            return
        self.calls += 1
        self.prompt_tokens += getattr(resp_usage, "prompt_tokens", 0) or 0
        self.completion_tokens += getattr(resp_usage, "completion_tokens", 0) or 0
        self.cache_hit_tokens += getattr(resp_usage, "prompt_cache_hit_tokens", 0) or 0
        self.cache_miss_tokens += getattr(resp_usage, "prompt_cache_miss_tokens", 0) or 0

    def estimate_cost_cny(self) -> float:
        peak = is_deepseek_peak_now()
        hit_price = 0.04 if peak else 0.02
        miss_price = 2.0 if peak else 1.0
        out_price = 8.0 if peak else 4.0
        return (
            self.cache_hit_tokens * hit_price
            + self.cache_miss_tokens * miss_price
            + self.completion_tokens * out_price
        ) / 1_000_000

    def line(self) -> str:
        return (
            f"tokens: prompt={self.prompt_tokens}(hit={self.cache_hit_tokens} "
            f"miss={self.cache_miss_tokens}) completion={self.completion_tokens} "
            f"calls={self.calls} est_cost=¥{self.estimate_cost_cny():.3f}"
        )


FUZZY_SIMILARITY_THRESHOLD = 0.92

_CACHE_NOISE_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
    r"|\b\d{4}-\d{2}-\d{2}t\d{2}:\d{2}:\d{2}\b"
    r"|\bent number\s*\d+\b"
    r"|\baccn\s*=\s*\S+"
    r"|\bphoto tag\s*#?\d+\b"
    r"|\"(?:irn|media|mm_repository_id|solr_long_lat|created|guid|catalognumber)\"\s*:\s*\"?[^,\"}]*\"?",
    re.IGNORECASE,
)


def normalize_for_cache(text: str) -> str:
    t = text.strip().lower()
    t = _CACHE_NOISE_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t)
    t = t.strip(" .;,:!?\"'")
    return t


_DIGITS_RE = re.compile(r"\d+")


def _quantity_signature(norm_text: str) -> tuple:
    return tuple(_DIGITS_RE.findall(norm_text))


@dataclass
class ContentCache:
    exact: dict = field(default_factory=dict)
    buckets: dict = field(default_factory=dict)
    exact_hits: int = 0
    fuzzy_hits: int = 0

    def lookup(self, text: str, family: str) -> Optional[tuple]:
        norm = normalize_for_cache(text)
        if not norm:
            return None
        hit = self.exact.get(norm)
        if hit is not None:
            self.exact_hits += 1
            return hit, "exact"

        sig = _quantity_signature(norm)
        bucket = self.buckets.get(family or "unknown", [])
        best_result = None
        best_ratio = 0.0
        for cand_norm, cand_sig, cand_result in bucket:
            if cand_sig != sig:
                continue
            if abs(len(cand_norm) - len(norm)) > max(20, int(len(norm) * 0.3)):
                continue
            sm = difflib.SequenceMatcher(None, norm, cand_norm)
            if sm.quick_ratio() < FUZZY_SIMILARITY_THRESHOLD:
                continue
            ratio = sm.ratio()
            if ratio >= FUZZY_SIMILARITY_THRESHOLD and ratio > best_ratio:
                best_result, best_ratio = cand_result, ratio
        if best_result is not None:
            self.fuzzy_hits += 1
            return best_result, f"fuzzy({best_ratio:.2f})"
        return None

    def add(self, text: str, family: str, result: dict) -> None:
        norm = normalize_for_cache(text)
        if not norm or norm in self.exact:
            return
        self.exact[norm] = result
        self.buckets.setdefault(family or "unknown", []).append((norm, _quantity_signature(norm), result))


@dataclass
class ClassifyStats:
    total_seen: int = 0
    already_in_old: int = 0
    prefiltered_out: int = 0
    cache_hits: int = 0
    sent_to_llm: int = 0
    relevant: int = 0
    irrelevant: int = 0
    review_corrected: int = 0
    errors: int = 0
    usage: Usage = field(default_factory=Usage)
    started_at: float = field(default_factory=time.time)

    def log_line(self) -> str:
        elapsed = time.time() - self.started_at
        rate = self.total_seen / elapsed if elapsed > 0 else 0
        return (
            f"[{elapsed:7.0f}s] seen={self.total_seen} already_in_old={self.already_in_old} "
            f"prefiltered_out={self.prefiltered_out} cache_hits={self.cache_hits} "
            f"sent_to_llm={self.sent_to_llm} relevant={self.relevant} irrelevant={self.irrelevant} "
            f"review_corrected={self.review_corrected} errors={self.errors} rate={rate:.1f} rows/s "
            f"| {self.usage.line()}"
        )


@dataclass
class ExtractStats:
    total_candidates: int = 0
    cache_hits: int = 0
    extracted: int = 0
    review_corrected: int = 0
    errors: int = 0
    usage: Usage = field(default_factory=Usage)
    started_at: float = field(default_factory=time.time)

    def log_line(self) -> str:
        elapsed = time.time() - self.started_at
        rate = self.total_candidates / elapsed if elapsed > 0 else 0
        return (
            f"[{elapsed:7.0f}s] candidates={self.total_candidates} cache_hits={self.cache_hits} "
            f"extracted={self.extracted} review_corrected={self.review_corrected} "
            f"errors={self.errors} rate={rate:.1f} rows/s | {self.usage.line()}"
        )


def iter_rows(path: Path, limit: Optional[int] = None):
    source_file = path.name
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter=CSV_DELIMITER)
        for i, raw in enumerate(reader):
            if limit is not None and i >= limit:
                return
            yield Row(
                row_id=i,
                decimallatitude=raw.get("decimallatitude", ""),
                decimallongitude=raw.get("decimallongitude", ""),
                year=raw.get("year", ""),
                month=raw.get("month", ""),
                basisofrecord=raw.get("basisofrecord", ""),
                taxonkey=raw.get("taxonkey", ""),
                family=raw.get("family", ""),
                species=raw.get("species", ""),
                occurrenceremarks=raw.get("occurrenceremarks", ""),
                eventremarks=raw.get("eventremarks", ""),
                dynamicproperties=raw.get("dynamicproperties", ""),
                fieldnotes=raw.get("fieldnotes", ""),
                behavior=raw.get("behavior", ""),
                locationremarks=raw.get("locationremarks", ""),
                organismremarks=raw.get("organismremarks", ""),
                individualcount=raw.get("individualcount", ""),
                organismquantity=raw.get("organismquantity", ""),
                organismquantitytype=raw.get("organismquantitytype", ""),
                gbifid=raw.get("gbifid", ""),
                source_file=source_file,
            )


def load_old_signatures(old_csv_path: Path) -> set[tuple]:
    sigs: set[tuple] = set()
    for row in iter_rows(old_csv_path):
        sigs.add(row.signature())
    return sigs


def iter_relevant_classify_records(path: Path, limit: Optional[int] = None):
    if not path.exists():
        return
    n = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not rec.get("relevant"):
                continue
            if limit is not None and n >= limit:
                return
            n += 1
            yield rec


OLD_FORMAT_DEFAULT_SOURCE = "0001017-260916113435855.csv"


def rec_uid(rec: dict) -> str:
    uid = rec.get("uid")
    if uid:
        return uid
    source = rec.get("sourceFile") or OLD_FORMAT_DEFAULT_SOURCE
    return f"{source}:{rec['row_id']}"


def load_classify_done_and_cache(jsonl_path: Path) -> tuple:
    done: set = set()
    cache = ContentCache()
    if not jsonl_path.exists():
        return done, cache
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                done.add(rec_uid(rec))
            except (json.JSONDecodeError, KeyError):
                continue
            if rec.get("error"):
                continue
            text = rec.get("notesText") or rec.get("occurrenceRemarks", "")
            if text:
                cache.add(text, rec.get("family", ""), {
                    "classification": rec.get("classification"),
                    "classification_reviewed": rec.get("classification_reviewed"),
                    "relevant": rec.get("relevant"),
                    "review_verified": rec.get("review_verified"),
                    "review_corrections": rec.get("review_corrections"),
                })
    return done, cache


def load_extract_done_and_cache(jsonl_path: Path) -> tuple:
    done: set = set()
    cache = ContentCache()
    if not jsonl_path.exists():
        return done, cache
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                done.add(rec_uid(rec))
            except (json.JSONDecodeError, KeyError):
                continue
            if rec.get("extract_error"):
                continue
            text = rec.get("notesText") or rec.get("occurrenceRemarks", "")
            if text:
                cache.add(text, rec.get("family", ""), {
                    "extraction_raw": rec.get("extraction_raw"),
                    "extraction_reviewed": rec.get("extraction_reviewed"),
                    "extract_review_verified": rec.get("extract_review_verified"),
                    "extract_review_corrections": rec.get("extract_review_corrections"),
                })
    return done, cache


class FatalAPIError(RuntimeError):
    pass


async def call_json(
    client: AsyncOpenAI, model: str, messages: list[dict], usage: Optional[Usage] = None
) -> dict:
    last_err: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=MAX_TOKENS,
                extra_body={"thinking": {"type": "disabled"}},
            )
            if usage is not None:
                usage.add(getattr(resp, "usage", None))
            content = resp.choices[0].message.content
            if not content:
                raise json.JSONDecodeError("empty content", "", 0)
            return json.loads(content)
        except APIStatusError as e:
            if e.status_code in (401, 402):
                raise FatalAPIError(
                    f"DeepSeek API error {e.status_code} ({e.message}) - check API key / balance."
                ) from e
            last_err = e
            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
        except (RateLimitError, APIConnectionError, APIError, json.JSONDecodeError) as e:
            last_err = e
            await asyncio.sleep(RETRY_BASE_DELAY * (2 ** attempt))
    raise RuntimeError(f"DeepSeek call failed after {MAX_RETRIES} retries: {last_err}")


async def classify_row(
    row: Row, client: AsyncOpenAI, model: str, sem: asyncio.Semaphore, stats: ClassifyStats
) -> Optional[dict]:
    remarks = row.notes_text()
    async with sem:
        stats.sent_to_llm += 1
        try:
            classification = await call_json(
                client, model, build_classify_messages(remarks, row.family), usage=stats.usage
            )
            review = await call_json(
                client, model, build_classify_review_messages(remarks, row.family, classification),
                usage=stats.usage,
            )
            if not review.get("verified", False):
                stats.review_corrected += 1

            final_relevant = bool(review.get("relevant"))
            if final_relevant:
                stats.relevant += 1
            else:
                stats.irrelevant += 1

        except FatalAPIError:
            raise
        except Exception as e:
            stats.errors += 1
            sys.stderr.write(f"[row {row.row_id}] ERROR: {e}\n")
            return {
                "uid": row.uid(),
                "row_id": row.row_id,
                "sourceFile": row.source_file,
                "gbifID": row.gbifid or None,
                "decimalLatitude": row.decimallatitude,
                "decimalLongitude": row.decimallongitude,
                "year": row.year,
                "month": row.month,
                "basisOfRecord": row.basisofrecord,
                "taxonKey": row.taxonkey,
                "family": row.family,
                "occurrenceRemarks": row.occurrenceremarks,
                "eventRemarks": row.eventremarks,
                "dynamicProperties": row.dynamicproperties,
                "fieldNotes": row.fieldnotes,
                "notesText": remarks,
                "classification": None,
                "classification_reviewed": None,
                "relevant": False,
                "review_verified": False,
                "review_corrections": None,
                "error": str(e),
                "model": model,
            }

    return {
        "uid": row.uid(),
        "row_id": row.row_id,
        "sourceFile": row.source_file,
        "gbifID": row.gbifid or None,
        "decimalLatitude": row.decimallatitude,
        "decimalLongitude": row.decimallongitude,
        "year": row.year,
        "month": row.month,
        "basisOfRecord": row.basisofrecord,
        "taxonKey": row.taxonkey,
        "family": row.family,
        "occurrenceRemarks": row.occurrenceremarks,
        "eventRemarks": row.eventremarks,
        "dynamicProperties": row.dynamicproperties,
        "fieldNotes": row.fieldnotes,
        "notesText": remarks,
        "classification": classification,
        "classification_reviewed": {k: v for k, v in review.items() if k not in ("verified", "corrections")},
        "relevant": final_relevant,
        "review_verified": review.get("verified"),
        "review_corrections": review.get("corrections"),
        "error": None,
        "model": model,
    }


async def extract_row(
    rec: dict, client: AsyncOpenAI, model: str, sem: asyncio.Semaphore, stats: ExtractStats
) -> Optional[dict]:
    remarks = rec.get("notesText") or rec.get("occurrenceRemarks", "")
    family = rec.get("family", "")

    async with sem:
        stats.total_candidates += 1
        try:
            extraction = await call_json(
                client, model, build_extract_messages(remarks, family), usage=stats.usage
            )
            review = await call_json(
                client, model, build_extract_review_messages(remarks, extraction), usage=stats.usage
            )
            if not review.get("verified", False):
                stats.review_corrected += 1
            stats.extracted += 1
        except FatalAPIError:
            raise
        except Exception as e:
            stats.errors += 1
            sys.stderr.write(f"[row {rec.get('row_id')}] ERROR: {e}\n")
            out = dict(rec)
            out["extraction_raw"] = None
            out["extraction_reviewed"] = None
            out["direction_degrees_computed"] = None
            out["extract_review_verified"] = False
            out["extract_review_corrections"] = None
            out["extract_error"] = str(e)
            out["model"] = model
            return out

    out = dict(rec)
    out["extraction_raw"] = extraction
    out["extraction_reviewed"] = {k: v for k, v in review.items() if k not in ("verified", "corrections")}
    out["direction_degrees_computed"] = direction_to_degrees(
        review.get("direction"), is_arrival=bool(review.get("direction_is_arrival"))
    )
    out["extract_review_verified"] = review.get("verified")
    out["extract_review_corrections"] = review.get("corrections")
    out["extract_error"] = None
    out["model"] = model
    return out


def finalize_json(jsonl_path: Path, json_path: Path) -> int:
    records = []
    if jsonl_path.exists():
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    records.sort(key=lambda r: r.get("row_id", 0))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    return len(records)


def make_client(args: argparse.Namespace) -> AsyncOpenAI:
    api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY") or DEEPSEEK_API_KEY
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        sys.exit(
            "No DeepSeek API key set. Copy config.example.py -> config.py and fill in "
            "DEEPSEEK_API_KEY there, set the DEEPSEEK_API_KEY env var, or pass --api-key."
        )
    return AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)


async def run_classify(args: argparse.Namespace, jsonl_path: Path, json_path: Path) -> None:
    client = make_client(args)
    if args.resume:
        done_ids, content_cache = load_classify_done_and_cache(jsonl_path)
    else:
        done_ids, content_cache = set(), ContentCache()
    if done_ids:
        print(f"Resuming classify: {len(done_ids)} rows already done, will skip them.")
    if content_cache.exact:
        print(f"Content cache primed with {len(content_cache.exact)} distinct prior note texts.")

    old_signatures: Optional[set] = None
    if args.diff_against:
        print(f"Diffing against {args.diff_against} to find only newly added rows...")
        old_signatures = load_old_signatures(Path(args.diff_against))
        print(f"Loaded {len(old_signatures)} signatures from the old download.")

    stats = ClassifyStats()
    sem = asyncio.Semaphore(args.concurrency)
    write_lock = asyncio.Lock()
    out_f = open(jsonl_path, "a", encoding="utf-8")

    def cache_result_fields() -> tuple:
        return ("classification", "classification_reviewed", "relevant",
                "review_verified", "review_corrections")

    inflight: dict = {}

    async def handle(row: Row) -> Optional[dict]:
        result = await classify_row(row, client, args.model, sem, stats)
        if result is not None:
            line = json.dumps(result, ensure_ascii=False)
            async with write_lock:
                out_f.write(line + "\n")
                out_f.flush()
            if not result.get("error"):
                content_cache.add(result["notesText"], result.get("family", ""), {
                    k: result[k] for k in cache_result_fields()
                })
        return result

    async def handle_dedup_wait(row: Row, remarks: str, src_task: asyncio.Task) -> None:
        src_result = await src_task
        if src_result is None or src_result.get("error"):
            await handle(row)
            return
        write_cached(row, remarks, {k: src_result[k] for k in cache_result_fields()}, "inflight-dup")

    def write_cached(row: Row, remarks: str, cached: dict, tag: str) -> None:
        result = {
            "row_id": row.row_id,
            "gbifID": row.gbifid or None,
            "decimalLatitude": row.decimallatitude,
            "decimalLongitude": row.decimallongitude,
            "year": row.year,
            "month": row.month,
            "basisOfRecord": row.basisofrecord,
            "taxonKey": row.taxonkey,
            "family": row.family,
            "occurrenceRemarks": row.occurrenceremarks,
            "eventRemarks": row.eventremarks,
            "dynamicProperties": row.dynamicproperties,
            "fieldNotes": row.fieldnotes,
            "notesText": remarks,
            "error": None,
            "cached_from": tag,
            "model": args.model,
            **cached,
        }
        stats.cache_hits += 1
        if result["relevant"]:
            stats.relevant += 1
        else:
            stats.irrelevant += 1
        out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
        out_f.flush()

    tasks = []
    fatal: Optional[FatalAPIError] = None
    try:
        for row in iter_rows(Path(args.input), limit=args.limit):
            stats.total_seen += 1
            if row.uid() in done_ids:
                continue
            if old_signatures is not None and row.signature() in old_signatures:
                stats.already_in_old += 1
                continue
            if not passes_local_prefilter(row.prefilter_text()):
                stats.prefiltered_out += 1
                continue
            remarks = row.notes_text()
            cache_hit = content_cache.lookup(remarks, row.family)
            if cache_hit is not None:
                write_cached(row, remarks, cache_hit[0], cache_hit[1])
                continue
            norm = normalize_for_cache(remarks)
            if norm and norm in inflight:
                tasks.append(asyncio.create_task(handle_dedup_wait(row, remarks, inflight[norm])))
                continue
            t = asyncio.create_task(handle(row))
            if norm:
                inflight[norm] = t
                t.add_done_callback(lambda _t, n=norm: inflight.pop(n, None))
            tasks.append(t)
            if len(tasks) >= args.concurrency * 4:
                await asyncio.gather(*tasks)
                tasks = []
                print(stats.log_line(), flush=True)
        if tasks:
            await asyncio.gather(*tasks)
    except FatalAPIError as e:
        fatal = e
    finally:
        out_f.close()

    print(stats.log_line())
    n = finalize_json(jsonl_path, json_path)
    if fatal is not None:
        sys.exit(f"\nSTOPPED: {fatal}\n(Partial progress saved -> {json_path})")
    n_relevant = sum(1 for r in iter_relevant_classify_records(jsonl_path))
    print(f"Done. Finalized {n} records -> {json_path} ({n_relevant} marked relevant).")


async def run_extract(args: argparse.Namespace, jsonl_path: Path, json_path: Path, classify_jsonl: Path) -> None:
    if not classify_jsonl.exists():
        sys.exit(
            f"{classify_jsonl} not found. Run the classify stage first: "
            "python deepseek_migration_pipeline.py --stage classify"
        )

    client = make_client(args)
    if args.resume:
        done_ids, content_cache = load_extract_done_and_cache(jsonl_path)
    else:
        done_ids, content_cache = set(), ContentCache()
    if done_ids:
        print(f"Resuming extract: {len(done_ids)} rows already done, will skip them.")
    if content_cache.exact:
        print(f"Content cache primed with {len(content_cache.exact)} distinct prior note texts.")

    stats = ExtractStats()
    sem = asyncio.Semaphore(args.concurrency)
    write_lock = asyncio.Lock()
    out_f = open(jsonl_path, "a", encoding="utf-8")

    def cache_result_fields() -> tuple:
        return ("extraction_raw", "extraction_reviewed", "extract_review_verified",
                "extract_review_corrections", "direction_degrees_computed")

    inflight: dict = {}

    async def handle(rec: dict) -> Optional[dict]:
        result = await extract_row(rec, client, args.model, sem, stats)
        if result is not None:
            line = json.dumps(result, ensure_ascii=False)
            async with write_lock:
                out_f.write(line + "\n")
                out_f.flush()
            if not result.get("extract_error"):
                text = result.get("notesText") or result.get("occurrenceRemarks", "")
                content_cache.add(text, result.get("family", ""), {
                    k: result[k] for k in cache_result_fields()
                })
        return result

    async def handle_dedup_wait(rec: dict, remarks: str, src_task: asyncio.Task) -> None:
        src_result = await src_task
        if src_result is None or src_result.get("extract_error"):
            await handle(rec)
            return
        write_cached(rec, remarks, {k: src_result[k] for k in cache_result_fields()}, "inflight-dup")

    def write_cached(rec: dict, remarks: str, cached: dict, tag: str) -> None:
        result = dict(rec)
        result["extract_error"] = None
        result["extract_cached_from"] = tag
        result["model"] = args.model
        result.update(cached)
        stats.cache_hits += 1
        out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
        out_f.flush()

    if args.sample:
        pool = [r for r in iter_relevant_classify_records(classify_jsonl)
                if rec_uid(r) not in done_ids]
        record_iter = random.sample(pool, min(args.sample, len(pool)))
        print(f"Sampled {len(record_iter)} candidates at random "
              f"(from {len(pool)} not-yet-done) for this QA batch.")
    else:
        record_iter = iter_relevant_classify_records(classify_jsonl, limit=args.limit)

    tasks = []
    fatal: Optional[FatalAPIError] = None
    try:
        for rec in record_iter:
            if rec_uid(rec) in done_ids:
                continue
            remarks = rec.get("notesText") or rec.get("occurrenceRemarks", "")
            cache_hit = content_cache.lookup(remarks, rec.get("family", ""))
            if cache_hit is not None:
                write_cached(rec, remarks, cache_hit[0], cache_hit[1])
                continue
            norm = normalize_for_cache(remarks)
            if norm and norm in inflight:
                tasks.append(asyncio.create_task(handle_dedup_wait(rec, remarks, inflight[norm])))
                continue
            t = asyncio.create_task(handle(rec))
            if norm:
                inflight[norm] = t
                t.add_done_callback(lambda _t, n=norm: inflight.pop(n, None))
            tasks.append(t)
            if len(tasks) >= args.concurrency * 4:
                await asyncio.gather(*tasks)
                tasks = []
                print(stats.log_line(), flush=True)
        if tasks:
            await asyncio.gather(*tasks)
    except FatalAPIError as e:
        fatal = e
    finally:
        out_f.close()

    print(stats.log_line())
    n = finalize_json(jsonl_path, json_path)
    if fatal is not None:
        sys.exit(f"\nSTOPPED: {fatal}\n(Partial progress saved -> {json_path})")
    print(f"Done. Finalized {n} records -> {json_path}")


async def run(args: argparse.Namespace) -> None:
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    classify_jsonl = outdir / "classify.jsonl"
    classify_json = outdir / "classify.json"
    results_jsonl = outdir / "results.jsonl"
    results_json = outdir / "results.json"

    if args.stage == "classify":
        if args.finalize_only:
            n = finalize_json(classify_jsonl, classify_json)
            print(f"Finalized {n} records -> {classify_json}")
            return
        await run_classify(args, classify_jsonl, classify_json)
    else:
        if args.finalize_only:
            n = finalize_json(results_jsonl, results_json)
            print(f"Finalized {n} records -> {results_json}")
            return
        await run_extract(args, results_jsonl, results_json, classify_jsonl)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stage", choices=["classify", "extract"], required=True)
    p.add_argument("--input", default=DEFAULT_INPUT)
    p.add_argument("--diff-against", default=None)
    p.add_argument("--outdir", default=DEFAULT_OUTDIR)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--sample", type=int, default=None)
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    p.add_argument("--model", default=DEEPSEEK_MODEL)
    p.add_argument("--api-key", default=None)
    p.add_argument("--no-resume", dest="resume", action="store_false")
    p.add_argument("--finalize-only", action="store_true")
    p.set_defaults(resume=True)
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))