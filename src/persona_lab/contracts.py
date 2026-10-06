"""Small, executable v0.1 contracts; unknown is a first-class answer."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

CONTRACT_VERSION = "0.1"
DOMAINS = {"need", "understanding", "alternatives", "purchase", "trust", "onboarding", "churn"}


class ContractError(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def text_id(value: Any, label: str) -> None:
    require(isinstance(value, str) and bool(value.strip()), f"{label} must be a nonempty string")


def positive_int(value: Any, label: str) -> None:
    require(type(value) is int and value > 0, f"{label} must be a positive integer")


def validate_source(source: dict) -> dict:
    require(isinstance(source, dict), "source must be an object")
    require(source.get("schema_version") == CONTRACT_VERSION, "unsupported source contract")
    for key in ("source_id", "version", "url", "license_id", "license_url", "origin"):
        text_id(source.get(key), key)
    require(source["origin"] in {"project_synthetic_fixture", "upstream_synthetic"}, "unsupported origin")
    return source


def validate_experiment(spec: dict) -> dict:
    require(isinstance(spec, dict), "experiment must be an object")
    require(spec.get("schema_version") == CONTRACT_VERSION, "unsupported experiment contract")
    text_id(spec.get("experiment_id"), "experiment_id")
    require(spec.get("mode") == "independent_comparison", "only independent comparison is implemented")
    panel = spec.get("panel")
    require(isinstance(panel, dict) and panel.get("selection") in {"all", "filter"}, "panel selection must be all or filter")
    require(set(panel) <= {"selection", "prefecture", "age_min", "age_max", "query"}, "unsupported panel filter")
    for key in ("prefecture", "query"):
        require(key not in panel or isinstance(panel[key], str), f"{key} must be text")
    for key in ("age_min", "age_max"):
        require(key not in panel or type(panel[key]) is int and panel[key] >= 0, f"{key} must be a nonnegative integer")
    require(panel.get("age_min", 0) <= panel.get("age_max", 10000), "age range is reversed")
    require(panel["selection"] != "all" or len(panel) == 1, "all selection cannot also contain filters")
    require(type(spec.get("seed")) is int, "seed must be an integer")
    positive_int(spec.get("repeats"), "repeats")
    positive_int(spec.get("batch_size"), "batch_size")
    require(spec["batch_size"] <= 1024, "v0.1 batch_size must be at most 1024; this is not a panel size cap")
    require(isinstance(spec.get("scenario"), dict), "scenario must be an object")
    scenario = spec["scenario"]
    text_id(scenario.get("initial_state_id"), "initial_state_id")
    require(isinstance(scenario.get("events"), list), "events must be explicit, possibly empty")
    for event in scenario["events"]:
        require(isinstance(event, dict), "event must be an object")
        text_id(event.get("code"), "event.code")
    require(isinstance(spec.get("assumptions"), dict), "assumptions must be explicit, possibly empty")
    budgets = spec["assumptions"].get("fixture_budget_jpy_minor_by_uuid", {})
    require(isinstance(budgets, dict), "fixture budgets must be an object")
    for uuid, amount in budgets.items():
        text_id(uuid, "budget uuid")
        require(type(amount) is int and amount >= 0, "fixture budget must be a nonnegative integer")
    if "purchase_budget_jpy_minor" in spec["assumptions"]:
        amount = spec["assumptions"]["purchase_budget_jpy_minor"]
        require(type(amount) is int and amount >= 0, "explicit panel budget must be a nonnegative integer")
    for collection in ("products", "questions"):
        items = spec.get(collection)
        require(isinstance(items, list) and bool(items), f"{collection} must be a nonempty list")
        ids = []
        for item in items:
            require(isinstance(item, dict), f"{collection} item must be an object")
            text_id(item.get("id"), f"{collection}.id")
            ids.append(item["id"])
        require(len(set(ids)) == len(ids), f"duplicate {collection} ids")
    for product in spec["products"]:
        for key in ("name", "intro"):
            text_id(product.get(key), f"product.{key}")
        require(isinstance(product.get("features"), list) and all(isinstance(f, str) for f in product["features"]), "features must be strings")
        price = product.get("price")
        require(isinstance(price, dict), "price must be an object")
        require(type(price.get("amount_minor")) is int and price["amount_minor"] >= 0, "price must be a nonnegative integer in minor units")
        require(isinstance(price.get("currency"), str) and len(price["currency"]) == 3 and price["currency"].isupper(), "currency must be an uppercase 3-letter code")
        require(price.get("billing") in {"one_time", "monthly", "annual"}, "unsupported billing")
    for question in spec["questions"]:
        require(question.get("domain") in DOMAINS, "unsupported question domain")
        text_id(question.get("prompt"), "question.prompt")
        choices = question.get("choices")
        require(isinstance(choices, list) and all(isinstance(c, str) and c for c in choices), "choices must be nonempty strings")
        require("unknown" in choices and len(set(choices)) == len(choices), "choices require unknown and must be unique")
    return spec


@dataclass(frozen=True)
class Persona:
    persona_id: str
    uuid: str
    source: dict
    raw: dict
    content_hash: str
    narratives: dict
    missing: dict
    field_provenance: dict


@dataclass(frozen=True)
class Job:
    ordinal: int
    job_id: str
    persona: Persona
    product: dict
    question: dict
    repeat: int
    seed: int
    scenario: dict
    assumptions: dict


@dataclass(frozen=True)
class Decision:
    choice: str
    status: str
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    score: float | None = None
    score_semantics: str = "not_provided"
    evidence_semantics: str = "backend_cited_input"


def validate_decision(decision: Decision, job: Job) -> None:
    require(isinstance(decision, Decision), "backend must return a Decision")
    require(decision.choice in job.question["choices"], "backend returned an unlisted choice")
    require(decision.status in {"ok", "insufficient_information"}, "invalid decision status")
    require((decision.choice == "unknown") == (decision.status == "insufficient_information"), "unknown must mark insufficient information")
    require(bool(decision.reason_codes) and all(isinstance(r, str) and r for r in decision.reason_codes), "reason codes are required")
    require(all(isinstance(r, str) and r for r in decision.evidence_refs), "evidence refs must be strings")
    if decision.choice != "unknown":
        require(bool(decision.evidence_refs), "known choices need input evidence refs")
    roots = {"persona": {"raw": job.persona.raw}, "product": job.product, "scenario": job.scenario, "assumptions": job.assumptions}
    for ref in decision.evidence_refs:
        value = roots
        for part in ref.split("."):
            require(isinstance(value, dict) and part in value, f"evidence path does not exist: {ref}")
            value = value[part]
        require(value is not None and value != "", f"evidence points to missing input: {ref}")
    if job.question["domain"] == "churn" and not job.scenario["events"]:
        require(decision.choice == "unknown", "churn requires an explicit post-use event")
    require(decision.score is None, "v0.1 does not accept uncalibrated numeric scores")
    require(decision.score_semantics == "not_provided", "unexpected score semantics")
    require(decision.evidence_semantics in {"backend_cited_input", "supplied_input_only"}, "unexpected evidence semantics")
