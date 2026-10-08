"""Small, executable v0.1 contracts; unknown is a first-class answer."""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any

CONTRACT_VERSION = "0.1"
DOMAINS = {"need", "understanding", "alternatives", "purchase", "trust", "onboarding", "churn", "usage", "fair_price",
           "relevance", "current_solution", "clarity", "benefit", "differentiation", "credibility", "switching"}
CURRENCIES = {"JPY": 0, "KRW": 0, "USD": 2, "EUR": 2}
BILLINGS = {"one_time", "monthly", "annual"}


class ContractError(ValueError):
    pass


class JudgmentQualityError(ContractError):
    """The model returned unsupported or inconsistent judgment evidence."""


class DependencyError(ContractError):
    """An earlier assessment failed; this is not missing persona information."""


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


def validate_money(value: dict, label="금액") -> dict:
    require(isinstance(value, dict) and set(value) == {"amount_minor", "currency", "billing"}, f"{label} 형식을 확인하세요.")
    require(type(value["amount_minor"]) is int and 0 <= value["amount_minor"] <= 9223372036854775807, f"{label} 범위를 확인하세요.")
    require(isinstance(value['currency'],str) and value["currency"] in CURRENCIES and isinstance(value['billing'],str) and value["billing"] in BILLINGS, f"{label} 통화와 결제 주기를 확인하세요.")
    return value


def validate_valuation_bands(bands) -> list:
    require(isinstance(bands, list) and len(bands) in {0, 4}, '평가 가격대는 비워 두거나 네 구간으로 입력하세요.')
    next_low = 0
    for index, band in enumerate(bands):
        require(isinstance(band, dict) and set(band) == {'id', 'low_minor', 'high_minor'}
                and band['id'] == f'price_{index}', '평가 가격대 형식을 확인하세요.')
        low, high = band['low_minor'], band['high_minor']
        require(type(low) is int and low == next_low and 0 <= low <= 9223372036854775807,
                '평가 가격대는 0부터 이어지는 구간이어야 합니다.')
        if index == 3:
            require(high is None, '마지막 평가 가격대는 상한 없이 입력하세요.')
        else:
            require(type(high) is int and low <= high < 9223372036854775807, '평가 가격대 경계값은 증가해야 합니다.')
            next_low = high + 1
    return bands


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
    require(isinstance(panel, dict) and panel.get("selection") in {"all", "filter", "random"}, "unsupported panel selection")
    require(set(panel) <= {"selection", "prefecture", "age_min", "age_max", "query", "sex", "sample_size", "sample_seed", "sampling_version", "selected_uuids"}, "unsupported panel filter")
    for key in ("prefecture", "query"):
        require(key not in panel or isinstance(panel[key], str), f"{key} must be text")
    for key in ("age_min", "age_max"):
        require(key not in panel or type(panel[key]) is int and panel[key] >= 0, f"{key} must be a nonnegative integer")
    require(panel.get("age_min", 0) <= panel.get("age_max", 10000), "age range is reversed")
    require(panel["selection"] != "all" or len(panel) == 1, "all selection cannot also contain filters")
    require('sex' not in panel or isinstance(panel['sex'],str) and panel['sex'] in {'female','male','other','unknown'}, 'unsupported sex filter')
    if panel['selection']=='random':
        positive_int(panel.get('sample_size'),'sample size')
        require(type(panel.get('sample_seed')) is int, 'sampling seed must be an integer')
        require(panel.get('sampling_version','hash-rank-v1')=='hash-rank-v1', 'unsupported sampling version')
        if 'selected_uuids' in panel:
            ids=panel['selected_uuids']
            require(isinstance(ids,list) and 0<len(ids)<=panel['sample_size'] and all(isinstance(value,str) and value for value in ids), 'invalid frozen sample')
            require(len(set(ids))==len(ids), 'duplicate frozen sample IDs')
    else:
        require(not {'sample_size','sample_seed','sampling_version','selected_uuids'} & set(panel), 'sampling fields require random selection')
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
    if "purchase_budget" in spec["assumptions"]:
        validate_money(spec["assumptions"]["purchase_budget"], "구매 상한")
    for collection in ("products", "questions"):
        items = spec.get(collection)
        require(isinstance(items, list) and bool(items), f"{collection} must be a nonempty list")
        ids = []
        for item in items:
            require(isinstance(item, dict), f"{collection} item must be an object")
            text_id(item.get("id"), f"{collection}.id")
            ids.append(item["id"])
        require(len(set(ids)) == len(ids), f"duplicate {collection} ids")
    require(len(spec["products"]) <= 5, "an experiment accepts at most five items")
    for product in spec["products"]:
        for key in ("name", "intro"):
            text_id(product.get(key), f"product.{key}")
        require(isinstance(product.get("features"), list) and all(isinstance(f, str) for f in product["features"]), "features must be strings")
        price = product.get("price")
        if scenario.get('id') == 'product-survey-v2' and price is not None:
            validate_money(price, '판매가격')
        if price is None and isinstance(product.get("document"), str):
            text_id(product["document"], "product.document")
            continue
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
    from .scenarios import validate_scenario
    validate_scenario(spec)
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
    assessments: dict | None = None


@dataclass(frozen=True)
class Decision:
    choice: str
    status: str
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    score: float | None = None
    score_semantics: str = "not_provided"
    evidence_semantics: str = "backend_cited_input"
    reason: str = ""
    missing_information: tuple[str, ...] = ()
    evidence: tuple[dict, ...] = ()
    valuation: dict | None = None
    option_probabilities: dict | None = None
    probability_semantics: str = 'not_provided'
    diagnostic_error: dict | None = None


def validate_decision(decision: Decision, job: Job) -> None:
    require(isinstance(decision, Decision), "backend must return a Decision")
    require(decision.choice in job.question["choices"], "backend returned an unlisted choice")
    require(decision.status in {"ok", "insufficient_information", "not_run"}, "invalid decision status")
    require((decision.choice == "unknown") == (decision.status == "insufficient_information"), "unknown must mark insufficient information")
    require((decision.choice == 'not_run') == (decision.status == 'not_run'), 'not-run status must be explicit')
    if decision.status == 'not_run':
        require(job.question['domain']=='purchase' and job.product.get('price') is None
                or job.scenario.get('id') == 'product-survey-v2' and job.question['domain']=='fair_price'
                and job.product.get('valuation_bands') == [], 'only an unset measurement condition can skip a question')
    if job.scenario.get('id') == 'product-response-v1':
        from .responses import REASON_PATTERN, MISSING_PATTERN
        require(isinstance(decision.reason,str) and re.fullmatch(REASON_PATTERN,decision.reason) is not None, '판단 근거는 짧은 한국어 문장이어야 합니다.')
        require(isinstance(decision.missing_information,(tuple,list)) and len(decision.missing_information)<=3 and all(isinstance(value,str) and re.fullmatch(MISSING_PATTERN,value) is not None for value in decision.missing_information), '부족 정보는 구체적인 한국어 항목이어야 합니다.')
        require(decision.choice!='unknown' or bool(decision.missing_information), 'unknown requires the specific missing information')
    if job.scenario.get('id') == 'product-response-v2':
        require(isinstance(decision.reason,str) and 8<=len(decision.reason)<=801, '개인별 판단 근거를 확인할 수 없습니다.')
        require(decision.choice!='unknown' or bool(decision.missing_information), '판단 불가의 부족 정보를 확인할 수 없습니다.')
        if decision.valuation is not None:
            validate_money(decision.valuation,'추정 가격')
            require(job.question['domain']=='fair_price' and decision.choice.startswith('price_'),'가격 추정이 아닌 판단에 금액을 생성할 수 없습니다.')
    if job.scenario.get('id') in {'product-decision-v1','product-survey-v1','product-survey-v2'}:
        require(decision.valuation is None, '유한 선택 평가에는 임의의 금액을 생성할 수 없습니다.')
        require(decision.choice!='unknown' or bool(decision.missing_information) or decision.diagnostic_error is not None, '판단 불가의 확인 항목이 필요합니다.')
        if decision.diagnostic_error is not None:
            error=decision.diagnostic_error
            require(decision.choice=='unknown' and not decision.missing_information, '후속 분류 오류는 원래 판단 불가와 구분해야 합니다.')
            require(isinstance(error,dict) and set(error)=={'type','message'} and all(isinstance(value,str) and value for value in error.values()), '후속 분류 오류 형식이 올바르지 않습니다.')
        if decision.status != 'not_run':
            probabilities = decision.option_probabilities
            allowed = set(job.question['choices']) - {'not_run'}
            require(isinstance(probabilities,dict) and set(probabilities)==allowed, '선택 점수의 항목이 일치하지 않습니다.')
            require(all(type(value) in (int,float) and math.isfinite(value) and 0<=value<=1 for value in probabilities.values()), '선택 점수가 올바르지 않습니다.')
            require(abs(sum(probabilities.values())-1)<=0.0001, '선택 점수의 합이 올바르지 않습니다.')
            require(probabilities[decision.choice]==max(probabilities.values()), '선택은 최대 점수 항목이어야 합니다.')
            require(decision.probability_semantics=='model_option_distribution', '선택 점수의 의미가 올바르지 않습니다.')
        require(decision.evidence_semantics=='supplied_input_only', '선택 모델 입력을 인과 근거로 표시할 수 없습니다.')
    require(bool(decision.reason_codes) and all(isinstance(r, str) and r for r in decision.reason_codes), "reason codes are required")
    require(all(isinstance(r, str) and r for r in decision.evidence_refs), "evidence refs must be strings")
    if decision.choice not in {"unknown", "not_run"}:
        require(bool(decision.evidence_refs), "known choices need input evidence refs")
    roots = {"persona": {"raw": job.persona.raw}, "product": job.product, "scenario": job.scenario, "assumptions": job.assumptions, "assessments":job.assessments or {}}
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
    require(job.scenario.get('id') in {'product-decision-v1','product-survey-v1','product-survey-v2'} or decision.diagnostic_error is None, '이전 판단 계약에 후속 분류 오류를 추가할 수 없습니다.')
