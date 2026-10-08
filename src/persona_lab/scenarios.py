"""Versioned, one-step scenarios. No generated cognition or agent actions."""

from .contracts import Decision, Job, require, validate_valuation_bands
from .responses import RESPONSE_SCENARIO_IDS, FINITE_SCENARIO_IDS, SURVEY_SCENARIO_ID, SURVEY_V2_SCENARIO_ID, price_bands

SCENARIO_ID = "independent-choice-v2"
SCENARIO_IDS = {"independent-choice-v1", SCENARIO_ID, *RESPONSE_SCENARIO_IDS}
EVENTS = {"repeated_crash", "unexpected_permission", "price_increase"}
CHOICES = {
    "need": {"now", "later", "none", "unknown"},
    "understanding": {"clear", "confused", "unknown"},
    "alternatives": {"offered_product", "current_method", "do_nothing", "unknown"},
    "purchase": {"buy", "defer", "decline", "unknown", "not_run"},
    "usage": {"use", "not_use", "unknown"},
    "fair_price": {"price_0", "price_1", "price_2", "price_3", "unknown"},
    "trust": {"accept", "request_evidence", "reject", "unknown"},
    "onboarding": {"proceed", "seek_help", "stop", "unknown"},
    "churn": {"stay", "reduce", "leave", "unknown"},
}


def validate_scenario(spec: dict) -> None:
    scenario = spec["scenario"]
    # Existing snapshots retain their original contract and backend fingerprint.
    if "id" not in scenario:
        require(all(q['domain'] not in {'usage','fair_price'} for q in spec['questions']), 'legacy scenarios retain the original domains')
        return
    require(scenario["id"] in SCENARIO_IDS, "unsupported scenario version")
    require(set(scenario) == {"id", "initial_state_id", "events"}, "unsupported scenario fields")
    require(scenario["initial_state_id"] == "initial-v1", "unsupported initial state")
    if scenario['id'] in RESPONSE_SCENARIO_IDS:
        from .contracts import CURRENCIES, BILLINGS
        require(spec['assumptions']=={} and scenario['events']==[], 'response questions do not accept a shared budget or post-use events')
        from .survey import SURVEY_DOMAINS, SURVEY_V2_DOMAINS
        expected=list(SURVEY_V2_DOMAINS) if scenario['id']==SURVEY_V2_SCENARIO_ID else list(SURVEY_DOMAINS) if scenario['id']==SURVEY_SCENARIO_ID else ['usage','fair_price','purchase']
        require([q['domain'] for q in spec['questions']]==expected, 'response questions must retain their ordered stages')
        for product in spec['products']:
            unit=product.get('valuation_unit')
            require(isinstance(unit,dict) and set(unit)=={'currency','billing'} and isinstance(unit['currency'],str)
                    and unit['currency'] in CURRENCIES and isinstance(unit['billing'],str) and unit['billing'] in BILLINGS, 'invalid valuation unit')
            if scenario['id']==SURVEY_V2_SCENARIO_ID:
                validate_valuation_bands(product.get('valuation_bands'))
            else:
                require(product.get('valuation_bands')==price_bands(unit['currency']), 'invalid valuation bands')
    codes = []
    for event in scenario["events"]:
        require(set(event) <= {"code", "origin"} and event["code"] in EVENTS, "unsupported scenario event")
        require(event.get("origin") == "user_explicit_scenario", "event must be an explicit condition")
        codes.append(event["code"])
    require(len(codes) == len(set(codes)), "duplicate scenario event")
    for question in spec["questions"]:
        if scenario['id'] not in RESPONSE_SCENARIO_IDS:require(question['domain'] not in {'usage','fair_price'}, 'legacy scenarios retain the original domains')
        if scenario['id']==SURVEY_V2_SCENARIO_ID:
            from .survey import question_info
            allowed=set(question_info(question['domain'], SURVEY_V2_SCENARIO_ID)['choices'])
            require(set(question['choices']) == allowed, 'survey questions must retain their versioned choices')
        else:
            require(question['domain'] in CHOICES, 'unsupported question domain for this scenario')
            allowed=CHOICES[question['domain']] if scenario['id'] in RESPONSE_SCENARIO_IDS else CHOICES[question['domain']]-{'not_run'}
        require(set(question["choices"]) <= allowed, "scenario has an unlisted choice")


def budget_context(assumptions, uuid, scenario):
    if scenario.get('id')==SCENARIO_ID:
        return assumptions.get('purchase_budget'), 'assumptions.purchase_budget'
    amount=assumptions.get('fixture_budget_jpy_minor_by_uuid',{}).get(uuid,assumptions.get('purchase_budget_jpy_minor'))
    ref=f'assumptions.fixture_budget_jpy_minor_by_uuid.{uuid}' if uuid in assumptions.get('fixture_budget_jpy_minor_by_uuid',{}) else 'assumptions.purchase_budget_jpy_minor'
    return ({'amount_minor':amount,'currency':'JPY','billing':'one_time'} if amount is not None else None),ref


def context_gate(job: Job) -> Decision | None:
    if job.scenario.get('id') in RESPONSE_SCENARIO_IDS:
        if job.scenario.get('id')==SURVEY_V2_SCENARIO_ID and job.question['domain']=='fair_price' and job.product.get('valuation_bands')==[]:
            return Decision('not_run','not_run',('missing_valuation_grid',),(),reason='평가 가격대가 입력되지 않았습니다.',missing_information=('평가 가격대',),evidence_semantics='supplied_input_only')
        if job.question['domain']=='purchase' and job.product.get('price') is None:
            return Decision('not_run','not_run',('missing_price_context',),(),reason='판매가격이 입력되지 않았습니다.',missing_information=('판매가격',),evidence_semantics='supplied_input_only' if job.scenario.get('id') in FINITE_SCENARIO_IDS else 'backend_cited_input')
        return None
    if job.question["domain"] == "purchase":
        if job.scenario.get('id')==SCENARIO_ID and job.product.get('price_state')=='free':return None
        budget,_=budget_context(job.assumptions,job.persona.uuid,job.scenario)
        if budget is None:
            return Decision("unknown", "insufficient_information", ("missing_purchase_context",), ())
        if job.product.get("price") is None:
            return Decision("unknown", "insufficient_information", ("missing_price_context",), ())
        if any(job.product['price'][key]!=budget[key] for key in ('currency','billing')):
            reason='purchase_units_mismatch' if job.scenario.get('id')==SCENARIO_ID else 'unsupported_budget_currency_or_billing'
            return Decision("unknown", "insufficient_information", (reason,), ())
    if job.question["domain"] == "churn" and not job.scenario["events"]:
        return Decision("unknown", "insufficient_information", ("missing_post_use_event",), ())
    return None


def execution_record(job: Job, decision: Decision | None, backend_error: dict | None) -> dict:
    gate = context_gate(job)
    ruled = decision is not None and gate is not None and decision == gate
    terminal = "failed" if backend_error else "not_run" if decision.status == 'not_run' else "undecidable" if decision.choice == "unknown" else "decided"
    return {
        "scenario_id": job.scenario.get("id", "legacy-independent-v0.1"),
        "initial_state_id": job.scenario["initial_state_id"],
        "question_id": job.question["id"],
        "stage": job.question["domain"],
        "allowed_choices": job.question["choices"],
        "max_steps": 1,
        "transition": {"from": "initial", "to": terminal},
        "origin": "backend_error" if backend_error else "context_rule" if ruled else "backend",
        "rules_applied": list(gate.reason_codes) if ruled else [],
    }
