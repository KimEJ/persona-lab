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
from persona_lab.finite_decision import PRICE_HISTORY_PROTOCOL
from persona_lab.responses import SURVEY_V2_SCENARIO_ID, SURVEY_V3_SCENARIO_ID, SURVEY_V4_SCENARIO_ID, input_product
from persona_lab.runner import matches, selected_personas
from persona_lab.survey import SURVEY_V2_QUESTIONS, SURVEY_V3_QUESTIONS, SURVEY_V4_QUESTIONS


ALGORITHM_VERSION = 'auto-price-v3'
PREVIOUS_ALGORITHM_VERSION = 'auto-price-v2'
LEGACY_ALGORITHM_VERSION = 'auto-price-v1'
HISTORY_ALGORITHM_VERSION = 'auto-wtp-v3'
WTP_ALGORITHM_VERSION = HISTORY_ALGORITHM_VERSION
PREVIOUS_WTP_ALGORITHM_VERSION = 'auto-wtp-v2'
LEGACY_WTP_ALGORITHM_VERSION = 'auto-wtp-v1'
PERSON_CONSISTENCY_ALGORITHMS = {ALGORITHM_VERSION, WTP_ALGORITHM_VERSION, PREVIOUS_WTP_ALGORITHM_VERSION}
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


def _input_key(product, scenario_id=SURVEY_V2_SCENARIO_ID):
    supplied = input_product(product, 'fair_price')
    value = {'name': supplied['name'], 'document': supplied.get('document', supplied['intro']),
             'unit': product['valuation_unit']}
    if scenario_id in {SURVEY_V3_SCENARIO_ID, SURVEY_V4_SCENARIO_ID}:
        value['valuation_semantics'] = 'maximum_willingness_to_pay_v1'
    return digest(value)


def _round(boundaries, phase):
    return {'phase': phase, 'bands': bands_from_boundaries(boundaries), 'cursor': 0, 'outcomes': []}


def _counts(round_state):
    return Counter(outcome['decision']['choice'] for outcome in round_state['outcomes']
                   if outcome['kind'] == 'decision' and outcome['decision']['status'] == 'ok'
                   and outcome['decision']['choice'].startswith('price_'))


def _summary(entry, algorithm_version):
    result = {'mode': 'auto', 'status': 'ready' if entry['status'] == 'resolved' else 'unavailable',
              'reason': entry['reason'], 'pilot_count': len(entry['pilot_uuids']),
              'valid_count': entry.get('valid_count', 0), 'algorithm_version': algorithm_version}
    if entry.get('reused_from'):
        result['reused_from'] = entry['reused_from']
    return result


def _resolved(products, state):
    result = copy.deepcopy(products)
    for product in result:
        entry = state['products'].get(product['id'])
        if entry is not None:
            product['valuation_bands'] = copy.deepcopy(entry.get('final_bands', []))
            product['valuation_calibration'] = _summary(entry, state['algorithm_version'])
    return result


def _update_progress(state):
    entries = [entry for entry in state['products'].values() if not entry.get('reused_from')]
    state['completed'] = sum(round_state['cursor'] for entry in entries for round_state in entry['rounds'])
    state['total'] = sum(len(entry['pilot_uuids']) * max(1, len(entry['rounds']))
                         for entry in entries if entry['status'] not in {'unavailable'} or entry['rounds'])
    state['complete'] = all(entry['status'] in {'resolved', 'unavailable'} for entry in state['products'].values())
    if state['complete']:
        state['total'] = state['completed']


def _extreme(counts):
    valid = sum(counts.values())
    if not valid:
        return None
    return 'price_3' if counts['price_3'] / valid >= EXTREME_SHARE else (
           'price_0' if counts['price_0'] / valid >= EXTREME_SHARE else None)


def _dominant_band(round_state):
    counts = _counts(round_state)
    valid = sum(counts.values())
    if not valid:
        return None
    choice = max(counts, key=counts.get)
    if counts[choice] / valid < EXTREME_SHARE:
        return None
    return next(band for band in round_state['bands'] if band['id'] == choice)


def _disjoint(first, second):
    return ((first['high_minor'] is not None and first['high_minor'] < second['low_minor']) or
            (second['high_minor'] is not None and second['high_minor'] < first['low_minor']))


def _incompatible_pilots(previous, current):
    def chosen_bands(round_state):
        bands = {band['id']: band for band in round_state['bands']}
        return {outcome['uuid']: bands[outcome['decision']['choice']]
                for outcome in round_state['outcomes']
                if outcome['kind'] == 'decision' and outcome['decision']['status'] == 'ok'
                and outcome['decision']['choice'] in bands}

    before, after = chosen_bands(previous), chosen_bands(current)
    incompatible = []
    for identifier in before.keys() & after.keys():
        if _disjoint(before[identifier], after[identifier]):
            incompatible.append(identifier)
    return sorted(incompatible)


def _conflicting_rounds(history, current):
    # In one dimension, pairwise overlap is equivalent to a nonempty total
    # intersection. Check every earlier response, not only the adjacent round.
    return [{'round': index, 'uuids': incompatible}
            for index, previous in enumerate(history)
            if (incompatible := _incompatible_pilots(previous, current))]


def _decision_history(entry, persona, round_index):
    """Recorded same-person judgments, never facts or inferred exact amounts."""
    records = []
    for index, previous in enumerate(entry['rounds'][:round_index]):
        outcomes = [outcome for outcome in previous['outcomes'] if outcome['uuid'] == persona.uuid]
        require(len(outcomes) == 1, '이전 가격대 탐색의 인물 응답이 없거나 중복됩니다.')
        outcome = outcomes[0]
        record = {'round': index, 'phase': previous['phase'], 'job_id': outcome['job_id']}
        if outcome['kind'] == 'error':
            record['status'] = 'error'
        else:
            require(outcome['kind'] == 'decision', '이전 가격대 탐색의 응답 종류를 지원하지 않습니다.')
            response = outcome['decision']
            if response['status'] == 'ok':
                chosen = [band for band in previous['bands'] if band['id'] == response['choice']]
                require(len(chosen) == 1, '이전 가격대 탐색의 선택 구간이 잘못되었습니다.')
                record.update(status='ok', interval={key: chosen[0][key] for key in ('low_minor', 'high_minor')})
            else:
                require(response['choice'] == 'unknown', '이전 가격대 탐색의 판단 불가 응답이 잘못되었습니다.')
                record['status'] = 'unknown'
        records.append(record)
    if not records:
        return None
    return {'protocol': PRICE_HISTORY_PROTOCOL, 'persona_id': persona.persona_id,
            'valuation_unit': copy.deepcopy(entry['unit']), 'records': records}


def calibrate(products, people, panel, backend, experiment_id, seed, state=None,
              cancelled=lambda: False, checkpoint=lambda state: None, scenario_id=SURVEY_V2_SCENARIO_ID):
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
    require(scenario_id in {SURVEY_V2_SCENARIO_ID, SURVEY_V3_SCENARIO_ID, SURVEY_V4_SCENARIO_ID}, '가격대 탐색의 평가 방식을 지원하지 않습니다.')
    input_keys = {product['id']: _input_key(product, scenario_id) for product in automatic}
    wtp = scenario_id in {SURVEY_V3_SCENARIO_ID, SURVEY_V4_SCENARIO_ID}
    current_algorithm = WTP_ALGORITHM_VERSION if wtp else ALGORITHM_VERSION
    algorithm_version = current_algorithm if state is None else state.get('algorithm_version')
    supported_algorithms = {WTP_ALGORITHM_VERSION, PREVIOUS_WTP_ALGORITHM_VERSION, LEGACY_WTP_ALGORITHM_VERSION} if wtp else {ALGORITHM_VERSION, PREVIOUS_ALGORITHM_VERSION, LEGACY_ALGORITHM_VERSION}
    require(algorithm_version in supported_algorithms,
            '저장된 가격대 탐색의 알고리즘 버전을 지원하지 않습니다.')
    scenario = {'id': scenario_id, 'initial_state_id': 'initial-v1', 'events': []}
    question = next(value for value in (SURVEY_V4_QUESTIONS if scenario_id == SURVEY_V4_SCENARIO_ID else SURVEY_V3_QUESTIONS if scenario_id == SURVEY_V3_SCENARIO_ID else SURVEY_V2_QUESTIONS)
                    if value['domain'] == 'fair_price')
    identity = {'algorithm_version': algorithm_version, 'backend_id': backend.backend_id,
                'experiment_id': experiment_id, 'seed': seed, 'source_fingerprint': source_fingerprint,
                'panel_fingerprint': digest(panel), 'input_keys': input_keys}
    if scenario_id == SURVEY_V4_SCENARIO_ID:
        identity['scenario_id'] = scenario_id
    uses_history = algorithm_version == HISTORY_ALGORITHM_VERSION
    if uses_history:
        identity['history_protocol'] = PRICE_HISTORY_PROTOCOL
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
                            digest([algorithm_version, seed, source_fingerprint, key, person.persona_id]), person.uuid))
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

    def next_round(entry, candidate, phase):
        if algorithm_version != LEGACY_ALGORITHM_VERSION:
            visited = [tuple(band['low_minor'] for band in previous['bands'][1:])
                       for previous in entry['rounds']]
            if tuple(candidate) in visited:
                finish(entry, [], '이미 평가한 가격 범위로 돌아가므로 탐색을 중단했습니다.', 'unavailable')
                return False
        entry['rounds'].append(_round(candidate, phase))
        save()
        return True

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
                history = _decision_history(entry, persona, round_index) if uses_history else None
                job_identity = [algorithm_version, experiment_id, entry['input_key'], persona.persona_id,
                                round_index, current['bands'], seed]
                if uses_history:
                    job_identity.append({'protocol': PRICE_HISTORY_PROTOCOL, 'history': history})
                if scenario_id == SURVEY_V4_SCENARIO_ID:
                    job_identity.append({'scenario_id': scenario_id, 'evaluation_phase': 'price_calibration'})
                job_id = digest(job_identity)
                assumptions = {'evaluation_phase': 'price_calibration'} if scenario_id == SURVEY_V4_SCENARIO_ID else {}
                job = Job(cursor, job_id, persona, supplied, copy.deepcopy(question), 0, seed,
                          copy.deepcopy(scenario), assumptions, calibration_history=history)
                outcome = {'uuid': persona.uuid, 'job_id': job_id}
                if uses_history:
                    outcome['calibration_history'] = copy.deepcopy(history)
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
            extreme = _extreme(counts)
            if algorithm_version != LEGACY_ALGORITHM_VERSION and round_index > 0:
                conflicts = []
                if algorithm_version in PERSON_CONSISTENCY_ALGORITHMS:
                    conflicts = _conflicting_rounds(entry['rounds'][:round_index], current)
                else:
                    # Preserve the recorded policy and request identities when
                    # resuming preparations made with an earlier algorithm.
                    previous = entry['rounds'][-2]
                    before, after = _dominant_band(previous), _dominant_band(current)
                    if before and after and _disjoint(before, after):
                        incompatible = _incompatible_pilots(previous, current)
                        if incompatible:
                            conflicts = [{'round': round_index - 1, 'uuids': incompatible}]
                if conflicts:
                    incompatible = sorted({identifier for conflict in conflicts for identifier in conflict['uuids']})
                    prior_index = conflicts[0]['round']
                    previous = entry['rounds'][prior_index]
                    current['incompatible_uuids'] = incompatible
                    current['incompatible_with_round'] = prior_index
                    if algorithm_version in PERSON_CONSISTENCY_ALGORITHMS:
                        current['incompatible_rounds'] = conflicts
                    if _extreme(_counts(previous)) and extreme:
                        prefix = '가격 범위 조정 방향이 뒤집혔으며'
                    elif current['phase'] == 'refinement':
                        prefix = '세분화한 가격 범위를 벗어났으며'
                    else:
                        prefix = '가격 범위를 조정한 뒤'
                    finish(entry, [], f'{prefix}, 같은 사전 평가 인물 '
                                      f'{len(incompatible)}명의 선택 가격대가 이전 응답과 겹치지 않습니다. '
                                      '일관된 가격 범위를 확정하지 못했습니다.', 'unavailable')
                    break
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
                if not next_round(entry, candidate, 'expand' if extreme == 'price_3' else 'contract'):
                    break
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
                    if not next_round(entry, candidate, 'refinement'):
                        break
                    continue
            finish(entry, current['bands'], '사전 평가의 선택 구간을 바탕으로 확정했습니다.')
    return _resolved(products, state), state, True
