"""Price acceptance derived from frozen survey answers, without model calls."""

CALCULATION_SEMANTICS = 'usage_and_max_willingness_to_pay_v1'
ACCEPTANCE_LABELS = {
    'accept': '수용 가능', 'reject': '수용하지 않음', 'defer': '보류',
    'uncertain': '상한 구간 내 판정 불가', 'unknown': '판단 불가',
    'error': '오류', 'pending': '대기', 'not_run': '미실시',
}
ACCEPTANCE_QUESTION = {
    'id': 'price-acceptance-v1', 'domain': 'acceptance', 'title': '가격 수용',
    'choices': list(ACCEPTANCE_LABELS), 'labels': ACCEPTANCE_LABELS,
    'prompt': '사용 의향, 최대 지불 의향 가격대와 판매가격을 비교하여 계산합니다.',
    'derived': True, 'calculation_semantics': CALCULATION_SEMANTICS,
}


def response_cell(record):
    """Read the fields needed for derivation from a stored model record."""
    decision = record.get('decision')
    error = record.get('backend_error')
    return {'job_id': record.get('job_id'),
            'choice': decision['choice'] if decision else 'error',
            'status': decision['status'] if decision else 'backend_error',
            'error': error, 'reason': decision.get('reason', '') if decision else (error or {}).get('message', '')}


def derive_acceptance(product, usage, willingness):
    """Compare integer minor units; an interval never supplies an exact maximum."""
    inputs = {'usage': {'job_id': usage.get('job_id'), 'choice': usage.get('choice', 'pending')}}

    def result(choice, code, reason, missing=()):
        return {'job_id': None, 'choice': choice, 'status': choice,
                'reason_code': code, 'reason': reason, 'derived': True,
                'calculation_semantics': CALCULATION_SEMANTICS,
                'input_job_ids': [value['job_id'] for value in inputs.values() if value.get('job_id')],
                'inputs': dict(inputs), 'selling_price': product.get('price'),
                'missing_information': list(missing), 'diagnostic_error': None,
                'evidence': [], 'evidence_semantics': 'frozen_inputs_and_code_rule',
                'option_probabilities': None, 'probability_semantics': 'not_provided',
                'valuation': None, 'error': None,
                'review': {'marked': False, 'note': '', 'revision': 0}}

    def unavailable(cell, source):
        choice = cell.get('choice', 'pending')
        if choice == 'error' or cell.get('status') == 'backend_error':
            return result('error', source + '_error', ('사용 의향' if source == 'usage' else '최대 지불 의향 가격대') + ' 평가에 오류가 있습니다.')
        if choice in {'pending', 'not_run', 'unknown'}:
            state = {'pending': '대기 중입니다.', 'not_run': '실시되지 않았습니다.', 'unknown': '판단 불가입니다.'}[choice]
            return result(choice, source + '_' + choice, ('사용 의향' if source == 'usage' else '최대 지불 의향 가격대') + ' 평가가 ' + state)
        return None

    if usage.get('choice') == 'not_use':
        return result('reject', 'no_usage_intention', '사용할 의향이 없습니다.')
    blocked = unavailable(usage, 'usage')
    if blocked:
        return blocked
    if usage.get('choice') not in {'use', 'consider'}:
        return result('unknown', 'unsupported_usage_choice', '사용 의향 응답을 확인할 수 없습니다.')
    price = product.get('price')
    if price is None:
        return result('not_run', 'selling_price_missing', '판매가격이 입력되지 않았습니다.', ('판매가격',))
    amount = price.get('amount_minor')
    if type(amount) is not int or amount < 0:
        return result('unknown', 'selling_price_invalid', '판매가격을 비교할 수 없습니다.')
    if amount == 0:
        return result('accept' if usage['choice'] == 'use' else 'defer',
                      'free_with_usage_intention' if usage['choice'] == 'use' else 'free_with_usage_consideration',
                      '무료 조건에서 사용 의향이 있습니다.' if usage['choice'] == 'use' else '무료 조건에서도 사용을 고려 중입니다.')

    inputs['fair_price'] = {'job_id': willingness.get('job_id'), 'choice': willingness.get('choice', 'pending')}
    blocked = unavailable(willingness, 'willingness')
    if blocked:
        return blocked
    unit = product.get('valuation_unit') or {}
    if any(price.get(key) != unit.get(key) for key in ('currency', 'billing')):
        return result('unknown', 'price_unit_mismatch', '판매가격과 최대 지불 의향 가격대의 통화 또는 결제 주기가 다릅니다.')
    band = next((band for band in product.get('valuation_bands', []) if band['id'] == willingness.get('choice')), None)
    if band is None:
        return result('unknown', 'willingness_band_missing', '최대 지불 의향 가격대의 구간을 확인할 수 없습니다.')
    low, high = band.get('low_minor'), band.get('high_minor')
    if type(low) is not int or low < 0 or (high is not None and (type(high) is not int or high < low)):
        return result('unknown', 'willingness_band_invalid', '최대 지불 의향 가격대의 구간을 비교할 수 없습니다.')
    inputs['fair_price']['band'] = {'low_minor': low, 'high_minor': high, **unit}
    if amount <= low:
        return result('accept' if usage['choice'] == 'use' else 'defer',
                      'price_at_or_below_willingness_lower_bound' if usage['choice'] == 'use' else 'usage_consideration_within_price_limit',
                      '판매가격이 지불상한 구간의 하한 이하입니다.' if usage['choice'] == 'use' else '판매가격은 지불상한 이내이지만 사용을 고려 중입니다.')
    if high is not None and amount > high:
        return result('reject', 'price_above_willingness_upper_bound', '판매가격이 지불상한 구간의 상한을 초과합니다.')
    return result('uncertain', 'price_within_willingness_interval', '판매가격이 지불상한 구간 안에 있어 수용 여부를 확정할 수 없습니다.')
