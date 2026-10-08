"""Nemotron-shaped rows: one UUID, one person, six narrative views.

This adapter reads local JSONL only. Upstream Parquet streaming is a next step.
"""

import json
from pathlib import Path
from collections.abc import Iterator

from .contracts import ContractError, Persona, digest, require, text_id, validate_source

NARRATIVE_FIELDS = ("professional_persona", "sports_persona", "arts_persona", "travel_persona", "culinary_persona", "persona")
CONTEXT_FIELDS = ("cultural_background", "skills_and_expertise", "skills_and_expertise_list", "hobbies_and_interests", "hobbies_and_interests_list", "career_goals_and_ambitions", "sex", "age", "marital_status", "education_level", "occupation", "region", "area", "prefecture", "country")
EXPECTED_FIELDS = ("uuid",) + NARRATIVE_FIELDS + CONTEXT_FIELDS


def normalize(raw: dict, source: dict) -> Persona:
    require(isinstance(raw, dict), "persona row must be an object")
    validate_source(source)
    text_id(raw.get("uuid"), "original uuid")
    missing = {}
    for field in EXPECTED_FIELDS:
        if field not in raw:
            missing[field] = "absent"
        elif raw[field] is None:
            missing[field] = "null"
        elif raw[field] == "":
            missing[field] = "empty"
    for field, value in raw.items():
        if field == "age":
            require(value is None or type(value) is int, "age must be an integer or null")
        elif field in EXPECTED_FIELDS:
            require(value is None or isinstance(value, str), f"{field} must remain a source string or null")
    # *_list are source strings, not Python programs or guaranteed JSON arrays.
    content_hash = digest(raw)
    source_copy = dict(source)
    raw_copy = dict(raw)
    provenance = {field: {"source_id": source["source_id"], "version": source["version"], "origin": source["origin"], "path": f"raw.{field}"} for field in raw}
    return Persona(
        persona_id=digest([source["source_id"], source["version"], raw["uuid"]]),
        uuid=raw["uuid"], source=source_copy, raw=raw_copy,
        content_hash=content_hash,
        narratives={field: raw.get(field) for field in NARRATIVE_FIELDS},
        missing=missing, field_provenance=provenance,
    )


def read_personas(path: Path, source: dict) -> Iterator[Persona]:
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield normalize(json.loads(line), source)
            except (ValueError, TypeError) as error:
                raise ContractError(f"{path.name}:{line_no}: {error}") from error
