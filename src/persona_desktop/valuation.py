"""Bounded finite-choice price exploration, separate from the measured panel.

Candidate amounts are code-generated survey conditions, never model-generated
estimates. Stored pilot decisions choose a useful scale; they are not results of
the subsequent survey and are never supplied to its independent questions.
"""

import copy
import math
from collections import Counter
from dataclasses import asdict

from persona_lab.contracts import Job, digest, require, validate_decision, validate_valuation_bands
from persona_lab.responses import SURVEY_V2_SCENARIO_ID, input_product
from persona_lab.runner import matches, selected_personas
from persona_lab.survey import SURVEY_V2_QUESTIONS


ALGORITHM_VERSION = 'auto-price-v1'
MAX_PILOTS = 12
MAX_SCALE_ROUNDS = 3
MAX_ROUNDS = MAX_SCALE_ROUNDS + 1
MIN_VALID = 4
EXTREME_SHARE = .75
MAX_MINOR = 9223372036854775807
SCENARIO = {'id': SURVEY_V2_SCENARIO_ID, 'initial_state_id': 'initial-v1', 'events': []}
QUESTION = next(question for question in SURVEY_V2_QUESTIONS if question['domain'] == 'fair_price')


def bands_from_boundaries(boundaries):
    lows = [0, *boundaries]
    return validate_valuation_bands([
        {'id': f'price_{index}', 'low_minor': low,
         'high_minor': boundaries[index] - 1 if index < 3 else None}
        for index, low in enumerate(lows)
    ])


def initial_boundaries(unit):
    # Nominal units, not exchange rates, product classifications or offer prices.
    base = 1000 if unit['currency'] == 'KRW' else 100
    if unit['billing'] == 'monthly':
        base //= 10
    return [base, base * 100, base * 10000]


def _input_key(product):
    supplied = input_product(product, 'fair_price')
    return digest({'name': supplied['name'], 'document': supplied.get('document', supplied['intro']),
                   'unit': product['valuation_unit']})


def _round(boundaries, phase):
    return {'phase': phase, 'bands': bands_from_boundaries(boundaries), 'cursor': 0, 'outcomes': []}


def _counts(round_state):
    return Counter(outcome['decision']['choice'] for outcome in round_state['outcomes']
                   if outcome['kind'] == 'decision' and outcome['decision']['status'] == 'ok'
                   and outcome['decision']['choice'].startswith('price_'))


def _summary(entry):
    result = {'mode': 'auto', 'status': 'ready' if entry['status'] == 'resolved' else 'unavailable',
              'reason': entry['reason'], 'pilot_count': len(entry['pilot_uuids']),
              'valid_count': entry.get('valid_count', 0), 'algorithm_version': ALGORITHM_VERSION}
    if entry.get('reused_from'):
        result['reused_from'] = entry['reused_from']
    return result


def _resolved(products, state):
    result = copy.deepcopy(products)
    for product in result:
        entry = state['products'].get(product['id'])
        if entry is not None:
            product['valuation_bands'] = copy.deepcopy(entry.get('final_bands', []))
            product['valuation_calibration'] = _summary(entry)
    return result


def _update_progress(state):
    entries = [entry for entry in state['products'].values() if not entry.get('reused_from')]
    state['completed'] = sum(round_state['cursor'] for entry in entries for round_state in entry['rounds'])
    state['total'] = sum(len(entry['pilot_uuids']) * max(1, len(entry['rounds']))
                         for entry in entries if entry['status'] not in {'unavailable'} or entry['rounds'])
    state['complete'] = all(entry['status'] in {'resolved', 'unavailable'} for entry in state['products'].values())
    if state['complete']:
        state['total'] = state['completed']


def calibrate(products, people, panel, backend, experiment_id, seed, state=None,
              cancelled=lambda: False, checkpoint=lambda state: None):
    """Return (products with frozen grids, serializable state, preparation complete).

    The caller saves each checkpoint atomically and may attach an independent
    request journal to backend.audit. Cancellation leaves the next pilot cursor
    intact. Terminal grids (including unavailable) are never explored again.
    """
    people = list(people)
    eligible = [person for person in people if matches(person, panel)]
    by_uuid = {person.uuid: person for person in eligible}
    require(len(by_uuid) == len(eligible), '가격대 탐색 인물 식별자가 중복됩니다.')
    source_fingerprint = digest(sorted((person.uuid, person.content_hash, digest(person.source)) for person in eligible))
    automatic = [product for product in products if product.get('valuation_mode') == 'auto']
    input_keys = {product['id']: _input_key(product) for product in automatic}
    identity = {'algorithm_version': ALGORITHM_VERSION, 'backend_id': backend.backend_id,
                'experiment_id': experiment_id, 'seed': seed, 'source_fingerprint': source_fingerprint,
                'panel_fingerprint': digest(panel), 'input_keys': input_keys}
    if state is None:
        main_ids = {person.uuid for person in selected_personas(people, panel)}
        state = {**identity, 'source': [{'source_id': value['source_id'], 'version': value['version']}
                                      for value in {digest(person.source): person.source for person in eligible}.values()
                                      if 'source_id' in value and 'version' in value],
                 'products': {}, 'completed': 0, 'total': 0,
                 'maximum': MAX_PILOTS * MAX_ROUNDS * len(set(input_keys.values())), 'complete': False}
        first_by_key = {}
        for product in automatic:
            key = input_keys[product['id']]
            ranked = sorted(eligible, key=lambda person: (person.uuid in main_ids,
                            digest([ALGORITHM_VERSION, seed, source_fingerprint, key, person.persona_id]), person.uuid))
            pilots = ranked[:MAX_PILOTS]
            entry = {'input_key': key, 'name': product['name'], 'unit': copy.deepcopy(product['valuation_unit']), 'status': 'pending',
                     'pilot_uuids': [person.uuid for person in pilots],
                     'overlap_uuids': [person.uuid for person in pilots if person.uuid in main_ids],
                     'rounds': [], 'reason': '', 'valid_count': 0}
            if key in first_by_key:
                entry['reused_from'] = first_by_key[key]
            else:
                first_by_key[key] = product['id']
            state['products'][product['id']] = entry
        _update_progress(state)
        checkpoint(copy.deepcopy(state))
    else:
        require(all(state.get(key) == value for key, value in identity.items()),
                '저장된 가격대 탐색의 인물·상품·모델 조건이 다릅니다.')
        require(set(state['products']) == set(input_keys), '저장된 가격대 탐색 상품이 다릅니다.')

    def save():
        _update_progress(state)
        checkpoint(copy.deepcopy(state))

    def finish(entry, bands, reason, status='resolved'):
        entry.update(status=status, final_bands=copy.deepcopy(bands), reason=reason)
        save()

    for product in automatic:
        entry = state['products'][product['id']]
        if entry['status'] in {'resolved', 'unavailable'}:
            continue
        if cancelled():
            return _resolved(products, state), state, False
        if entry.get('reused_from'):
            prior = state['products'][entry['reused_from']]
            require(prior['status'] in {'resolved', 'unavailable'}, '공유 가격대 탐색이 완료되지 않았습니다.')
            entry.update(status=prior['status'], final_bands=copy.deepcopy(prior['final_bands']),
                         reason=prior['reason'], valid_count=prior['valid_count'])
            save()
            continue
        if len(entry['pilot_uuids']) < MIN_VALID:
            finish(entry, [], '필터에 맞는 사전 평가 인물이 4명보다 적습니다.', 'unavailable')
            continue
        if not entry['rounds']:
            entry['status'] = 'exploring'
            entry['rounds'].append(_round(initial_boundaries(entry['unit']), 'broad'))
            save()

        while entry['status'] == 'exploring':
            round_index = len(entry['rounds']) - 1
            current = entry['rounds'][-1]
            supplied = {**input_product(product, 'fair_price'), 'valuation_bands': current['bands']}
            while current['cursor'] < len(entry['pilot_uuids']):
                if cancelled():
                    return _resolved(products, state), state, False
                cursor = current['cursor']
                persona = by_uuid[entry['pilot_uuids'][cursor]]
                job_id = digest([ALGORITHM_VERSION, experiment_id, entry['input_key'], persona.persona_id,
                                 round_index, current['bands'], seed])
                job = Job(cursor, job_id, persona, supplied, copy.deepcopy(QUESTION), 0, seed,
                          copy.deepcopy(SCENARIO), {})
                outcome = {'uuid': persona.uuid, 'job_id': job_id}
                try:
                    decision = backend.decide(job)
                    outcome['raw_decision'] = asdict(decision) if hasattr(decision, '__dataclass_fields__') else repr(decision)[:2000]
                    validate_decision(decision, job)
                except Exception as error:
                    outcome.update(kind='error', error={'type': type(error).__name__, 'message': str(error)[:1000]})
                else:
                    if decision.diagnostic_error is not None:
                        outcome.update(kind='error', error=decision.diagnostic_error, decision=asdict(decision))
                    else:
                        outcome.update(kind='decision', decision=asdict(decision))
                current['outcomes'].append(outcome)
                current['cursor'] += 1
                save()  # No subsequent request may run before this persisted outcome.

            counts = _counts(current)
            valid = sum(counts.values())
            entry['valid_count'] = valid
            current['valid_count'] = valid
            current['choice_counts'] = dict(counts)
            required = max(MIN_VALID, math.ceil(len(entry['pilot_uuids']) / 2))
            if valid < required:
                unknown = sum(outcome['kind'] == 'decision' and outcome['decision']['choice'] == 'unknown'
                              for outcome in current['outcomes'])
                errors = sum(outcome['kind'] == 'error' for outcome in current['outcomes'])
                finish(entry, [], f'유효 응답이 {valid}명으로 필요한 {required}명에 못 미칩니다. '
                                 f'판단 불가 {unknown}명, 오류 {errors}명.', 'unavailable')
                break

            boundaries = [band['low_minor'] for band in current['bands'][1:]]
            extreme = 'price_3' if counts['price_3'] / valid >= EXTREME_SHARE else (
                      'price_0' if counts['price_0'] / valid >= EXTREME_SHARE else None)
            if current['phase'] != 'refinement' and extreme:
                if extreme == 'price_0' and boundaries[0] == 1:
                    finish(entry, current['bands'], '최소 금액 단위까지 탐색한 구간입니다.')
                    break
                if round_index + 1 >= MAX_SCALE_ROUNDS:
                    finish(entry, [], '응답이 끝 가격대에 계속 집중되어 제한된 사전 평가에서 범위를 확정하지 못했습니다.', 'unavailable')
                    break
                if extreme == 'price_3':
                    if boundaries[-1] > MAX_MINOR // 100:
                        finish(entry, [], '금액 입력 한도 안에서 가격 범위를 확장하지 못했습니다.', 'unavailable')
                        break
                    candidate = [value * 100 for value in boundaries]
                else:
                    candidate = [max(index + 1, value // 100) for index, value in enumerate(boundaries)]
                entry['rounds'].append(_round(candidate, 'expand' if extreme == 'price_3' else 'contract'))
                save()
                continue

            # Subdivide a single dominant finite interval geometrically. This
            # changes resolution, not the response distribution or its weights.
            dominant = max(('price_1', 'price_2'), key=lambda key: counts[key])
            if current['phase'] != 'refinement' and counts[dominant] / valid >= EXTREME_SHARE:
                index = int(dominant[-1])
                low, high = boundaries[index - 1], boundaries[index]
                midpoint = math.isqrt(low * high)
                candidate = [low, midpoint, high]
                if low < midpoint < high and candidate != boundaries:
                    entry['rounds'].append(_round(candidate, 'refinement'))
                    save()
                    continue
            finish(entry, current['bands'], '사전 평가의 선택 구간을 바탕으로 확정했습니다.')
    return _resolved(products, state), state, True
