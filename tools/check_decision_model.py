"""Run real finite-choice controls against a local Clef server; never use a result cache.

Exit 1 means an engineering failure. Exit 2 means valid inference with a failed
behavior/order/repeatability control. These are fixture checks, not consumer accuracy.
Use --repeat-only after restarting the server, optionally with --baseline <first JSON>.
"""

import argparse
import copy
import hashlib
import itertools
import json
import math
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from persona_lab.adapter import normalize
from persona_lab.contracts import Job, digest, validate_decision
from persona_lab.responses import DECISION_QUESTIONS, DECISION_SCENARIO_ID, price_bands

TOLERANCE = 1e-6
SCENARIO = {'id': DECISION_SCENARIO_ID, 'initial_state_id': 'initial-v1', 'events': []}
SOURCE = {
    'schema_version': '0.1', 'source_id': 'decision-controls', 'version': 'v1',
    'url': 'local:project-authored', 'license_id': 'LicenseRef-Project-Fixture',
    'license_url': 'local:project-authored', 'origin': 'project_synthetic_fixture',
}
DOCUMENT = '''## 주요 기능

개인 메모를 검색하고 태그로 정리합니다. 메모는 기기에 저장하며 파일로 내보냅니다.

## 도입 조건·제약

macOS 14 이상에서만 사용합니다. Windows와 스마트폰은 지원하지 않습니다.
계정과 인터넷은 필요하지 않습니다. 동기화와 팀 공유 기능은 없습니다.'''
PROFILES = {
    'need': {
        'persona': '매일 macOS 14 PC에서 개인 메모를 작성한다. 메모 검색과 태그 분류 도구가 필요하며 이 상품을 사용하고 싶다고 명시했다. 이 상품의 적정가격은 일시불 1,000 JPY라고 생각한다. 무료 또는 일시불 500 JPY이면 사용하거나 구매하겠다고 명시했다. 일시불 2,000,000 JPY이면 구매하지 않겠다고 명시했다.',
        'occupation': '문서 편집자', 'operating_system': 'macOS 14',
        'current_method': '종이 메모에서 내용을 찾기 어렵다.',
    },
    'no_need': {
        'persona': '개인 메모를 전혀 작성하지 않는다. 새 메모 앱을 사용할 필요도 의향도 없으며 이 상품이 무료라도 사용하지 않겠다고 명시했다.',
        'occupation': '조리사',
    },
    'windows_only': {
        'persona': 'Windows PC와 Android 스마트폰만 사용한다. Mac을 구입하거나 빌릴 계획이 없고 macOS 전용 앱을 설치하거나 사용할 수 없다. 이 상품이 무료라도 사용하지 않겠다고 명시했다.',
        'operating_system': 'Windows와 Android',
    },
    'missing_context': {'age': 35, 'sex': '女'},
    'USD': {
        'persona': '매일 macOS 14 PC에서 개인 메모를 작성한다. 메모 검색과 태그 분류 기능이 필요하며 이 상품을 사용하고 싶다. 이 상품에 적정하다고 생각하는 가격은 일시불 9.99 USD라고 명시했다. 무료 또는 일시불 9.99 USD이면 사용하거나 구매하겠다고 명시했다.',
        'occupation': '문서 편집자', 'operating_system': 'macOS 14',
    },
}


def control_job(profile, domain, amount=2000, currency='JPY', assessments=None):
    """Fixed semantic identifiers keep cold-process requests comparable."""
    person = normalize({'uuid': 'decision-control-' + profile, **PROFILES[profile]}, SOURCE)
    question = copy.deepcopy(next(question for question in DECISION_QUESTIONS if question['domain'] == domain))
    question['choices'] = [choice for choice in question['choices'] if choice != 'not_run']
    product = {
        'id': 'decision-control-memo', 'name': '메모 도구', 'intro': DOCUMENT,
        'document': DOCUMENT, 'features': [],
        'price': {'amount_minor': amount, 'currency': currency, 'billing': 'one_time'},
        'valuation_unit': {'currency': currency, 'billing': 'one_time'},
        'valuation_bands': price_bands(currency),
    }
    return Job(0, digest([profile, domain, amount, currency]), person, product, question,
               0, 17, copy.deepcopy(SCENARIO), {}, assessments)


def probabilities(decision, choices):
    values = decision.get('option_probabilities')
    if not isinstance(values, dict) or set(values) != set(choices):
        raise ValueError('Option probabilities do not cover the exact finite choice set.')
    if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1 for value in values.values()):
        raise ValueError('Option probabilities must be finite values between zero and one.')
    if abs(sum(values.values()) - 1) > TOLERANCE:
        raise ValueError('Option probabilities do not sum to one.')
    return values


def compare_rows(rows, baseline=None):
    valid = [row for row in rows if row.get('decision') is not None and row.get('error') is None]
    reference = baseline or (valid[0] if valid else None)
    if reference is None or reference.get('error') is not None or reference.get('decision') is None or not valid:
        return {'passed': False, 'actual_calls': len(rows), 'error': 'No valid reference inference.'}
    reference_values = reference['decision']['option_probabilities']
    differences = []
    for row in valid:
        values = row['decision']['option_probabilities']
        if set(values) != set(reference_values):
            differences.append(None)
        else:
            differences.append(max(abs(values[key] - reference_values[key]) for key in values))
    request_identical = all(row['request_sha256'] == reference['request_sha256'] for row in valid)
    choices_identical = all(row['decision']['choice'] == reference['decision']['choice'] for row in valid)
    exact = all(difference == 0 for difference in differences)
    maximum = max(differences) if all(value is not None for value in differences) else None
    return {
        'actual_calls': len(rows), 'valid_calls': len(valid), 'reference_request_sha256': reference['request_sha256'],
        'request_identical': request_identical, 'choices_identical': choices_identical,
        'probabilities_exact': exact, 'max_abs_probability_difference': maximum,
        'probability_tolerance': TOLERANCE,
        'passed': len(valid) == len(rows) and request_identical and choices_identical and maximum is not None and maximum <= TOLERANCE,
    }


def summarize(checks, repeat_rows, seed_rows, order_rows, cold_baseline=None):
    failures = [row['case'] for row in checks if row['error'] is not None]
    behavioral = [row for row in checks if row['group'] == 'behavior']
    behavior_failures = [row['case'] for row in behavioral if row['error'] is None and row['decision']['choice'] not in row['expected']]
    repeatability = compare_rows(repeat_rows)
    seed_invariance = compare_rows(seed_rows, repeat_rows[0])
    order_changes = [row['case'] for row in order_rows if row['error'] is None and row['decision']['choice'] != row['baseline_choice']]
    cold = compare_rows(repeat_rows, cold_baseline) if cold_baseline else None
    metrics = {
        'engineering': {'passed': not failures, 'cases': len(checks), 'failures': failures,
                        'scope': 'Actual transport, token/response parsing, finite contract and probability validity; raw calls are retained.'},
        'same_input_repeatability': repeatability, 'seed_metadata_invariance': seed_invariance,
        'condition_adherence': {'performed': bool(behavioral), 'passed': not behavior_failures and all(row['error'] is None for row in behavioral),
                                'cases': len(behavioral), 'failures': behavior_failures},
        'option_order': {'performed': bool(order_rows), 'passed': not order_changes and all(row['error'] is None for row in order_rows),
                         'cases': len(order_rows), 'changed_choices': order_changes},
        'cold_process_comparison': cold,
    }
    ready = all(metrics[key]['passed'] for key in ('engineering', 'same_input_repeatability', 'seed_metadata_invariance', 'condition_adherence', 'option_order')) and (cold is None or cold['passed'])
    return metrics, ready


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('endpoint', 'model-id', 'revision', 'runtime-revision'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tag', default='local')
    parser.add_argument('--repeat-only', action='store_true')
    parser.add_argument('--baseline', type=Path, help='A previous report used as the cold-process reference.')
    args = parser.parse_args(argv)
    previous, cold_baseline = None, None
    if args.baseline:
        if args.baseline.resolve() == args.output.resolve():
            parser.error('--baseline and --output must be different files')
        previous = json.loads(args.baseline.read_text())
        cold_baseline = next(row for row in previous['checks'] if row['case'] == 'same_input_0')
    from persona_lab.finite_decision import ClefBackend
    backend = ClefBackend(args.endpoint, args.model_id, args.revision, args.runtime_revision, context_tokens=8192)
    checks, calls = [], []
    report = {
        'schema_version': '1', 'tag': args.tag, 'created_at': datetime.now(timezone.utc).isoformat(),
        'backend_id': backend.backend_id, 'backend_kind': backend.kind,
        'endpoint': args.endpoint, 'model_id': args.model_id,
        'revision': args.revision, 'runtime_revision': args.runtime_revision, 'context_tokens': 8192,
        'scope': 'Explicit synthetic preference fixtures. No result cache, generated amounts or rationale. This does not establish consumer prediction accuracy.',
        'repeat_only': args.repeat_only, 'ready_scope': 'repeatability_only' if args.repeat_only else 'full_control_suite',
        'checks': checks, 'model_calls': calls,
    }

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n')

    def audit(event, identifier, value):
        if event == 'start':
            calls.append({'job_id': identifier, **value, 'started_at': value.get('time')})
            save()
            return len(calls) - 1
        calls[identifier].update(value, finished_at=value.get('time'))
        save()

    backend.audit = audit

    def call(job, label, group, expected=None, baseline_choice=None):
        started, call_start = time.monotonic(), len(calls)
        request, answer, error, stage = None, None, None, 'request'
        try:
            request = backend.request_body(job)
            stage = 'inference'
            result = backend.decide(job)
            stage = 'contract'
            validate_decision(result, job)
            answer = asdict(result)
            probabilities(answer, job.question['choices'])
            if answer.get('valuation') is not None or (answer['choice'] != 'unknown' and answer.get('reason')):
                raise ValueError('Finite decisions must not generate numeric valuations or known-choice rationale.')
            if len(calls) == call_start or any(item.get('response') is None or item.get('error') for item in calls[call_start:]):
                raise ValueError('Every actual inference must retain its complete audited response.')
        except Exception as problem:
            error = {'stage': stage, 'type': type(problem).__name__, 'message': str(problem)}
        row = {
            'case': label, 'group': group, 'domain': job.question['domain'], 'job_id': job.job_id,
            'seed_metadata': job.seed, 'choice_order': job.question['choices'], 'request': request,
            'request_sha256': digest(request) if request is not None else None,
            'wire_request_sha256': hashlib.sha256(json.dumps(request, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest() if request is not None else None,
            'decision': answer, 'error': error, 'expected': sorted(expected) if expected is not None else None,
            'baseline_choice': baseline_choice, 'model_call_indices': list(range(call_start, len(calls))),
            'seconds': round(time.monotonic() - started, 3),
        }
        checks.append(row)
        save()
        print(json.dumps({key: row[key] for key in ('case', 'domain', 'error', 'seconds')} | {'choice': answer.get('choice') if answer else None}, ensure_ascii=False), flush=True)
        return row

    def chain(profile, usage, fair, offers, currency='JPY'):
        prior, answers = {}, {}
        for domain, expected in (('usage', usage), ('fair_price', fair)):
            job = control_job(profile, domain, currency=currency)
            row = call(job, profile + '_' + domain, 'behavior', expected)
            answers[domain] = row
            prior[domain] = {'job_id': job.job_id, **{key: row['decision'].get(key) for key in ('choice', 'reason', 'missing_information')}} if row['decision'] and not row['error'] else {'job_id': job.job_id, 'choice': 'error', 'error': row['error']}
        for amount, expected in offers:
            job = control_job(profile, 'purchase', amount, currency, prior)
            answers['purchase_' + str(amount)] = call(job, profile + '_purchase_' + str(amount), 'behavior', expected)
        return prior, answers

    need_prior = None
    if not args.repeat_only:
        need_prior, need_answers = chain('need', {'use'}, {'price_1'}, [(0, {'buy'}), (500, {'buy'}), (2000000, {'decline'})])
        chain('no_need', {'not_use'}, {'price_0', 'unknown'}, [(0, {'decline'})])
        chain('windows_only', {'not_use'}, {'price_0', 'unknown'}, [(0, {'decline'})])
        chain('missing_context', {'unknown'}, {'unknown'}, [(2000, {'unknown'})])
        chain('USD', {'use'}, {'price_0'}, [(0, {'buy'}), (999, {'buy'})], 'USD')

    repeated_job = control_job('need', 'usage')
    repeat_rows = [call(replace(repeated_job, job_id=digest(['actual-repeat', index])), 'same_input_' + str(index), 'repeat') for index in range(5)]
    seed_rows = [call(replace(repeated_job, job_id=digest(['seed-metadata']), seed=2147483646), 'different_seed_metadata', 'seed')]
    order_rows = []
    if not args.repeat_only:
        for domain, job, baseline in (
            ('usage', repeated_job, need_answers['usage']),
            ('fair_price', control_job('need', 'fair_price'), need_answers['fair_price']),
            ('purchase', control_job('need', 'purchase', 500, assessments=need_prior), need_answers['purchase_500']),
        ):
            orders = list(itertools.permutations(job.question['choices'])) if domain == 'usage' else [tuple(job.question['choices']), tuple(reversed(job.question['choices'])), tuple(job.question['choices'][1:] + job.question['choices'][:1])]
            for index, order in enumerate(orders):
                ordered = replace(job, job_id=digest(['actual-order', domain, index]), question={**job.question, 'choices': list(order)})
                order_rows.append(call(ordered, domain + '_order_' + str(index), 'order', baseline_choice=baseline['decision']['choice'] if baseline['decision'] else None))

    if args.baseline:
        report['baseline'] = str(args.baseline.resolve())
        report['baseline_model_metadata_matches'] = all(previous.get(key) == report[key] for key in ('model_id', 'revision', 'runtime_revision', 'context_tokens'))
    metrics, ready = summarize(checks, repeat_rows, seed_rows, order_rows, cold_baseline)
    metrics['engineering']['audited_requests'] = len(calls)
    report.update(metrics=metrics, ready=ready, backend_metrics=dict(backend.metrics))
    if args.baseline and not report['baseline_model_metadata_matches']:
        report['ready'] = False
    save()
    print(json.dumps({'tag': args.tag, 'ready': report['ready'], 'metrics': metrics}, ensure_ascii=False), flush=True)
    return 1 if not metrics['engineering']['passed'] else 0 if report['ready'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
