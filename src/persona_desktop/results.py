"""One frozen cohort and one repeat, read from one SQLite snapshot."""
import json
import re
import sqlite3
from collections import Counter
from itertools import combinations

from persona_lab.acceptance import ACCEPTANCE_QUESTION, derive_acceptance
from persona_lab.contracts import require
from persona_lab.reports import summarize
from persona_lab.responses import RESPONSE_SCENARIO_IDS, SURVEY_V2_SCENARIO_ID, SURVEY_V3_SCENARIO_ID, SURVEY_V4_SCENARIO_ID
from persona_lab.runner import selected_personas, sex_code
from persona_lab.survey import question_info
from persona_lab.tags import tag_metadata, tag_source_labels


EXCLUDED = ('unknown', 'error', 'pending', 'not_run', 'not_applicable')


def demographics(raw):
    age = raw.get('age')
    age = age if type(age) is int and 0 <= age <= 150 else None
    group = '미제공' if age is None else '18세 미만' if age < 18 else '18–29세' if age < 30 else '30–39세' if age < 40 else '40–49세' if age < 50 else '50–59세' if age < 60 else '60세 이상'
    sex = {'female': '여성', 'male': '남성', 'unknown': '미제공', 'other': '기타'}[sex_code(raw.get('sex'))]
    return {'age': age, 'age_group': group, 'sex': sex}


def document_summary(document):
    lines = [re.sub(r'^[#>*\-\s]+', '', line).strip() for line in document.splitlines()]
    text = ' '.join(line for line in lines if line)
    return text[:240] + ('…' if len(text) > 240 else '')


def _tag_labels(panel, people):
    metadata = {identifier: tag_metadata(identifier) for identifier in panel.get('tags', [])}
    missing = {identifier for identifier, value in metadata.items()
               if ':source/' in identifier and not value['aliases']}
    if missing:
        for identifier, label in tag_source_labels(people, missing).items():
            metadata[identifier] = tag_metadata(identifier, source_label=label)
    return {identifier: value['labels'] for identifier, value in metadata.items()}


def _context(spec, source, backend_id, backend_kind, count, status, repeat, snapshot, people=()):
    frozen = snapshot or {}
    draft = frozen.get('draft', {})
    products = [{**product, 'document': product.get('document', product.get('intro', '')),
                 'summary': document_summary(product.get('document', product.get('intro', '')))}
                for product in spec['products']]
    return {'experiment_id': spec['experiment_id'], 'title': draft.get('title') or '제품 설문',
            'created_at': frozen.get('created_at', draft.get('created_at', '')),
            'panel': spec['panel'],
            'tag_labels': _tag_labels(spec['panel'], people),
            'source': {**source, 'name': source.get('name', source['source_id'])},
            'model': {'backend_id': backend_id, 'backend_kind': backend_kind,
                      'name': backend_id.split(':')[1] if backend_id.startswith('llama-cpp:') else backend_id},
            'scenario': spec['scenario'], 'scenario_id': spec['scenario'].get('id'),
            'repeat': repeat, 'repeats': spec['repeats'], 'selected_count': count,
            'status': status, 'run_status': status, 'products': products,
            **({'price_calibration': frozen['price_calibration']} if 'price_calibration' in frozen else {})}


def _empty_cell(domain, product, scenario_id):
    missing = '판매가격' if domain == 'purchase' and product.get('price') is None else '평가 가격대' if domain == 'fair_price' and scenario_id in {SURVEY_V2_SCENARIO_ID, SURVEY_V3_SCENARIO_ID, SURVEY_V4_SCENARIO_ID} and not product.get('valuation_bands') else None
    calibration = product.get('valuation_calibration', {})
    automatic_unavailable = missing == '평가 가격대' and calibration.get('mode') == 'auto'
    reason = (calibration.get('reason') or '가격대 탐색에서 평가 구간을 확정하지 못했습니다.') if automatic_unavailable else missing + '이 입력되지 않았습니다.' if missing else ''
    return {'job_id': None, 'choice': 'not_run' if missing else 'pending',
            'status': 'not_run' if missing else 'pending', 'reason': reason,
            'missing_information': [missing] if missing and not automatic_unavailable else [], 'diagnostic_error': None,
            'evidence': [], 'evidence_semantics': None, 'option_probabilities': None,
            'probability_semantics': 'not_provided', 'valuation': None, 'error': None,
            'review': {'marked': False, 'note': '', 'revision': 0}}


def _response_report(db, people, repeat=0, reviews=None, snapshot=None):
    row = db.execute('SELECT spec,cursor,total,status,source,backend_id,backend_kind FROM run WHERE id=1').fetchone()
    require(row is not None, '판단 결과를 준비 중입니다.')
    spec = json.loads(row[0])
    people = list(people)
    scenario_id = spec['scenario'].get('id')
    require(scenario_id in RESPONSE_SCENARIO_IDS, '이전 실험은 기존 결과 화면에서 확인하세요.')
    require(type(repeat) is int and 0 <= repeat < spec['repeats'], '반복 번호를 확인하세요.')
    cells = {}
    for person, product, domain, payload in db.execute('SELECT persona_id,product_id,domain,payload FROM results WHERE repeat=? ORDER BY ordinal', (repeat,)):
        record = json.loads(payload)
        decision = record['decision']
        error = record.get('backend_error')
        cell = {'job_id': record['job_id'], 'choice': decision['choice'] if decision else 'error',
                'status': decision['status'] if decision else 'backend_error',
                'reason': decision.get('reason', '') if decision else (error or {}).get('message', ''),
                'missing_information': decision.get('missing_information', []) if decision else [],
                'diagnostic_error': decision.get('diagnostic_error') if decision else None,
                'evidence': decision.get('evidence', []) if decision else [],
                'evidence_semantics': decision.get('evidence_semantics', 'backend_cited_input') if decision else None,
                'option_probabilities': decision.get('option_probabilities') if decision else None,
                'probability_semantics': decision.get('probability_semantics', 'not_provided') if decision else 'not_provided',
                'valuation': decision.get('valuation') if decision else None, 'error': error,
                'review': (reviews or {}).get(record['job_id'], {'marked': False, 'note': '', 'revision': 0})}
        cell.update({key: record[key] for key in ('survey_history', 'survey_history_hash', 'logical_job_id', 'stage', 'inference_protocol', 'invalidated', 'execution') if key in record})
        cells[person, product, domain] = cell
    selected = list(selected_personas(people, spec['panel']))
    domains = [question['domain'] for question in spec['questions']]
    cases = [{'persona_id': person.persona_id, 'uuid': person.uuid, 'name': f'인물 {index + 1:03d}',
              **demographics(person.raw), 'profile': {key: person.raw[key] for key in ('occupation', 'prefecture', 'persona') if isinstance(person.raw.get(key), str)}, 'items': [{'product_id': product['id'], **{
                  domain: cells.get((person.persona_id, product['id'], domain), _empty_cell(domain, product, scenario_id))
                  for domain in domains}} for product in spec['products']]}
             for index, person in enumerate(selected)]
    products = [{key: product[key] for key in ('id', 'name', 'price', 'price_state', 'valuation_unit', 'valuation_bands', 'valuation_calibration', 'document') if key in product} for product in spec['products']]
    for product in products:
        product['summary'] = document_summary(product.get('document', ''))
        product['description'] = product['summary']
    questions = [{**question, 'title': question_info(question['domain'], scenario_id)['title'],
                  'labels': question_info(question['domain'], scenario_id)['choices']} for question in spec['questions']]
    if scenario_id in {SURVEY_V3_SCENARIO_ID, SURVEY_V4_SCENARIO_ID}:
        questions.append(dict(ACCEPTANCE_QUESTION))
        for person in cases:
            for item in person['items']:
                product = next(product for product in products if product['id'] == item['product_id'])
                item['acceptance'] = derive_acceptance(product, item['usage'], item['fair_price'])
    count = len(cases)
    context = _context(spec, json.loads(row[4]), row[5], row[6], count, row[3], repeat, snapshot, people)
    response = {'workflow': scenario_id, 'questions': questions, 'repeat': repeat, 'repeats': spec['repeats'],
                'products': products, 'people': cases, 'count': count, 'cursor': row[1], 'total': row[2],
                'status': row[3], 'report_context': context, 'context': context}
    response.update(_statistics(response))
    return response


def _statistics(response):
    people, products, questions, n = (response[key] for key in ('people', 'products', 'questions', 'count'))
    by_person = {person['persona_id']: {item['product_id']: item for item in person['items']} for person in people}
    statistics = []
    for product in products:
        for question in questions:
            domain = question['domain']
            counts = Counter(by_person[person['persona_id']][product['id']][domain]['choice'] for person in people)
            counts = {choice: counts.get(choice, 0) for choice in dict.fromkeys([*question['choices'], *EXCLUDED, *counts])}
            excluded = {choice: counts[choice] for choice in EXCLUDED}
            if question.get('derived'):
                excluded['uncertain'] = counts.get('uncertain', 0)
            statistics.append({'product_id': product['id'], 'domain': domain, 'denominator': n,
                               'counts': counts, 'shares': {choice: value / n if n else 0 for choice, value in counts.items()},
                               'evaluated': n - sum(excluded.values()), 'excluded': excluded})
            if question.get('derived'):
                cells = [by_person[person['persona_id']][product['id']][domain] for person in people]
                statistics[-1].update(derived=True, calculation_semantics=question['calculation_semantics'],
                                      reason_counts=dict(Counter(cell['reason_code'] for cell in cells)),
                                      input_job_ids=list(dict.fromkeys(job for cell in cells for job in cell['input_job_ids'])))
    paired = []
    invalid = {'error', 'pending', 'not_run', 'not_applicable'}
    for first, second in combinations(products, 2):
        for question in questions:
            domain = question['domain']
            pairs = Counter((items[first['id']][domain]['choice'], items[second['id']][domain]['choice']) for items in by_person.values()
                            if items[first['id']][domain]['choice'] not in invalid and items[second['id']][domain]['choice'] not in invalid)
            included = sum(pairs.values())
            price_context = {'comparison_semantics': 'product_specific_price_bands',
                             'comparable_price_grid': first.get('valuation_unit') == second.get('valuation_unit') and first.get('valuation_bands') == second.get('valuation_bands'),
                             'from_price_grid': {'unit': first.get('valuation_unit'), 'bands': first.get('valuation_bands', [])},
                             'to_price_grid': {'unit': second.get('valuation_unit'), 'bands': second.get('valuation_bands', [])}} if domain == 'fair_price' else {}
            paired.append({'from_product': first['id'], 'to_product': second['id'], 'domain': domain,
                           'denominator': n, 'paired_count': included, 'excluded_count': n - included,
                           'transitions': [{'from': a, 'to': b, 'count': value} for (a, b), value in sorted(pairs.items())], **price_context})
    joint = []
    domains = {question['domain'] for question in questions}
    if {'usage', 'purchase'} <= domains:
        for product in products:
            pairs = Counter((items[product['id']]['usage']['choice'], items[product['id']]['purchase']['choice']) for items in by_person.values()
                            if items[product['id']]['usage']['choice'] not in invalid and items[product['id']]['purchase']['choice'] not in invalid)
            included = sum(pairs.values())
            joint.append({'product_id': product['id'], 'denominator': n, 'paired_count': included, 'excluded_count': n - included,
                          'cells': [{'usage': usage, 'purchase': purchase, 'count': value} for (usage, purchase), value in sorted(pairs.items())]})
    groups = {}
    for product in products:
        original = next(item for item in response['report_context']['products'] if item['id'] == product['id'])
        price = product.get('price')
        if price is None:
            continue
        key = json.dumps({k: v for k, v in original.items() if k not in {'id', 'price', 'price_state', 'price_origin', 'summary', 'valuation_calibration'}}, sort_keys=True, ensure_ascii=False)
        groups.setdefault(key, []).append(product)
    price_points = []
    stats = {(item['product_id'], item['domain']): item for item in statistics}
    price_domain, price_choice = ('acceptance', 'accept') if 'acceptance' in domains else ('purchase', 'buy')
    for group in groups.values():
        units = {(p['price']['currency'], p['price']['billing']) for p in group}
        if len(group) < 2 or len(units) != 1 or len({p['price']['amount_minor'] for p in group}) < 2:
            continue
        currency, billing = next(iter(units))
        if price_domain not in domains:
            continue
        price_points.append({'name': group[0]['name'], 'currency': currency, 'billing': billing,
                             **({'domain': price_domain, 'calculation_semantics': ACCEPTANCE_QUESTION['calculation_semantics']} if price_domain == 'acceptance' else {}),
                             'points': [{'product_id': p['id'], 'amount_minor': p['price']['amount_minor'],
                                         'count': stats[(p['id'], price_domain)]['counts'].get(price_choice, 0),
                                         'denominator': n, 'share': stats[(p['id'], price_domain)]['shares'].get(price_choice, 0),
                                         'excluded': stats[(p['id'], price_domain)]['excluded']} for p in sorted(group, key=lambda p: p['price']['amount_minor'])]})
    return {'statistics': statistics, 'paired_comparisons': paired, 'usage_purchase': joint, 'price_points': price_points,
            'denominator_semantics': 'frozen_selected_people_in_one_repeat_including_all_response_states'}


def response_report(path, people, repeat=0, reviews=None, snapshot=None):
    with sqlite3.connect(path) as db:
        db.execute('BEGIN')
        return _response_report(db, people, repeat, reviews, snapshot)


def experiment_report(path, people, repeat=0, reviews=None, snapshot=None, include_calls=False):
    """Core metadata, response counts and optional calls share one read transaction."""
    with sqlite3.connect(path) as db:
        db.execute('BEGIN')
        report = summarize(path, connection=db)
        response = _response_report(db, people, repeat, reviews, snapshot)
        report.update(responses=response, report_context=response['report_context'], reviews=reviews or {})
        if include_calls:
            keys = ('id', 'job_id', 'started_at', 'request', 'response', 'error', 'finished_at')
            report['model_calls'] = [dict(zip(keys, row)) for row in db.execute('SELECT ' + ','.join(keys) + ' FROM model_calls ORDER BY id')] if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_calls'").fetchone() else []
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_call_jobs'").fetchone():
                report['model_call_jobs'] = [{'call_id': call_id, 'job_id': job_id} for call_id, job_id in
                                            db.execute('SELECT call_id,job_id FROM model_call_jobs ORDER BY call_id,job_id')]
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='result_revisions'").fetchone():
                report['result_revisions'] = [{'id': identifier, 'ordinal': ordinal, 'job_id': job_id,
                                              'choice': choice, 'status': status, 'record': json.loads(payload),
                                              'reason': reason, 'saved_at': saved_at}
                                             for identifier, ordinal, job_id, choice, status, payload, reason, saved_at in
                                             db.execute('SELECT id,ordinal,job_id,choice,status,payload,reason,saved_at FROM result_revisions ORDER BY id')]
        return report
