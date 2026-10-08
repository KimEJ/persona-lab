"""Versioned finite questions for a pre-purchase product survey."""

from .responses import SURVEY_V2_SCENARIO_ID, choice_meanings


QUESTION_INFO = {
    'need': {
        'title': '필요성',
        'choices': {'now': '현재 해결할 필요가 있음', 'later': '나중에 검토할 필요가 있음',
                    'none': '해결할 필요가 없음', 'unknown': '판단 불가'},
        'missing': ('usage_goal', 'usage_frequency', 'current_method'),
    },
    'understanding': {
        'title': '이해도',
        'choices': {'clear': '용도와 사용방법이 명확함', 'confused': '설명이 불명확함', 'unknown': '판단 불가'},
        'missing': ('usage_goal', 'feature_scope', 'usage_environment'),
    },
    'usage': {
        'title': '사용 의향',
        'choices': {'use': '사용 의향 있음', 'not_use': '사용 의향 없음', 'unknown': '판단 불가'},
        'missing': ('usage_goal', 'usage_environment', 'current_method'),
    },
    'alternatives': {
        'title': '대안',
        'choices': {'offered_product': '이 상품을 선택', 'current_method': '현재 방식 유지',
                    'do_nothing': '추가 조치 없음', 'unknown': '판단 불가'},
        'missing': ('usage_goal', 'current_method', 'feature_scope', 'switching_effort'),
    },
    'trust': {
        'title': '신뢰',
        'choices': {'accept': '제시 내용을 수용', 'request_evidence': '추가 근거 요청',
                    'reject': '제시 내용을 거절', 'unknown': '판단 불가'},
        'missing': ('feature_scope', 'license_scope', 'privacy_terms'),
    },
    'onboarding': {
        'title': '도입 가능성',
        'choices': {'proceed': '도입 진행', 'seek_help': '도입 도움 요청', 'stop': '도입 중단', 'unknown': '판단 불가'},
        'missing': ('usage_environment', 'license_scope', 'privacy_terms', 'switching_effort'),
    },
    'fair_price': {
        'title': '적정가격',
        'choices': {'price_0': '가격대 1', 'price_1': '가격대 2', 'price_2': '가격대 3',
                    'price_3': '가격대 4', 'unknown': '판단 불가'},
        'missing': ('usage_goal', 'usage_frequency', 'current_method', 'feature_scope', 'license_scope', 'value_basis'),
    },
    'purchase': {
        'title': '최종 선택',
        'choices': {'buy': '선택', 'defer': '보류', 'decline': '거절', 'unknown': '판단 불가', 'not_run': '미실행'},
        'missing': ('usage_goal', 'usage_environment', 'current_method', 'feature_scope', 'license_scope', 'privacy_terms', 'switching_effort'),
    },
}

SURVEY_DOMAINS = tuple(QUESTION_INFO)
PREDECESSOR_DOMAINS = SURVEY_DOMAINS[:-1]
PROMPTS = (
    '이 인물에게 상품이 해결하는 문제가 현재 있는지, 이후 검토할 필요가 있는지 판단하세요. '
    '현재 필요와 이후 필요는 인물에 제공된 목적·빈도·현재 방식으로 구분하세요. 필요가 없다는 근거와 정보 부족을 구분하세요.',
    '이 인물이 제공된 상품 설명만 읽었다고 가정할 때 용도와 핵심 사용방법이 명확한지 판단하세요. '
    '읽거나 사용한 실제 경험을 만들지 말고, 제공된 설명과 인물 정보로 판단하세요.',
    '이 인물이 생활이나 업무에 이 상품을 사용하고 싶을지 판단하세요. '
    '제공된 목적, 현재 방식과 사용 환경을 고려하고 실제 사용 경험은 만들지 마세요.',
    '판매가격을 고려하지 않고 이 상품, 제공된 현재 방식 유지, 추가 조치를 하지 않음 중에서 '
    '이 인물이 택할 대안을 판단하세요. 현재 도구나 불편을 만들지 말고 비교 근거가 부족하면 판단 불가를 선택하세요.',
    '제공된 상품 설명·기능 범위·자료와 권한 조건을 이 인물이 수용할지, 추가 근거를 요구할지, '
    '거절할지 판단하세요. 실제 제품 품질이나 실증 결과를 확인했다고 가정하지 마세요.',
    '제공된 사용 환경·설치 조건·이전과 학습 절차에서 이 인물이 도입을 진행할지, '
    '도움을 요청할지, 중단할지 판단하세요. 실제 설치나 사용을 수행했다고 가정하지 마세요.',
    '판매가격 없이 이 인물이 상품에 적정하다고 생각할 가격대를 허용된 구간 중 하나로 선택하세요. '
    '통화와 결제 주기를 그대로 사용하고 소득, 예산이나 구매 이력을 만들지 마세요.',
    '같은 인물·아이템·회차의 일곱 선행 선택과 제시한 판매조건을 함께 보고 최종 선택 하나를 고르세요. '
    '선행 판단 불가를 확정 사실로 바꾸지 마세요. 무료여도 사용하지 않을 수 있으며 적정가격 구간은 구매 상한이 아닙니다.',
)
SURVEY_QUESTIONS = [
    {'id': f'{domain.replace("_", "-")}-survey-v1', 'domain': domain,
     'prompt': prompt, 'choices': list(QUESTION_INFO[domain]['choices'])}
    for domain, prompt in zip(SURVEY_DOMAINS, PROMPTS)
]


SURVEY_V2_INFO = {
    'relevance': {
        'title': '문제 관련성',
        'choices': {'relevant': '관련성이 높음', 'partly_relevant': '일부 관련 있음',
                    'not_relevant': '관련 없음', 'unknown': '판단 불가'},
        'missing': ('usage_goal', 'usage_frequency'),
    },
    'current_solution': {
        'title': '현재 해결 수준',
        'choices': {'sufficient': '현재 방법으로 충분히 해결', 'partial': '일부 해결',
                    'insufficient': '거의 해결하지 못함', 'no_current_method': '현재 방법 없음', 'unknown': '판단 불가'},
        'missing': ('usage_goal', 'current_method'),
    },
    'clarity': {
        'title': '설명 명확성',
        'choices': {'clear': '주된 목적이 명확함', 'partly_clear': '일부 불명확함',
                    'unclear': '주된 목적이 불명확함', 'unknown': '판단 불가'},
        'missing': ('usage_goal', 'feature_scope'),
    },
    'benefit': {
        'title': '개선 효익',
        'choices': {'better': '현재 방법보다 도움', 'similar': '현재 방법과 비슷함',
                    'worse': '현재 방법보다 불리함', 'not_applicable': '해당 없음', 'unknown': '판단 불가'},
        'missing': ('usage_goal', 'current_method', 'feature_scope'),
    },
    'differentiation': {
        'title': '차별성',
        'choices': {'distinct': '구분되는 이점이 뚜렷함', 'limited': '구분되는 이점이 일부 있음',
                    'not_distinct': '구분되는 이점이 없음', 'not_applicable': '해당 없음', 'unknown': '판단 불가'},
        'missing': ('alternatives_info', 'feature_scope'),
    },
    'credibility': {
        'title': '주장 신뢰성',
        'choices': {'supported': '제시 근거를 신뢰할 수 있음', 'partly_supported': '제시 근거를 일부 신뢰할 수 있음',
                    'unsupported': '제시 근거를 신뢰하기 어려움', 'unknown': '판단 불가'},
        'missing': ('feature_scope', 'claim_evidence'),
    },
    'switching': {
        'title': '전환 부담',
        'choices': {'low': '예상 부담이 낮음', 'moderate': '예상 부담이 중간', 'high': '예상 부담이 높음',
                    'not_applicable': '해당 없음', 'unknown': '판단 불가'},
        'missing': ('current_method', 'usage_environment', 'switching_effort'),
    },
    'usage': {
        'title': '사용 의향',
        'choices': {'use': '사용할 의향 있음', 'consider': '사용을 고려함', 'not_use': '사용할 의향 없음', 'unknown': '판단 불가'},
        'missing': ('usage_goal', 'usage_environment', 'current_method'),
    },
    'fair_price': {
        **QUESTION_INFO['fair_price'],
        'title': '적정가격 인식',
        'choices': {**QUESTION_INFO['fair_price']['choices'], 'not_run': '미실시'},
    },
    'purchase': {
        **QUESTION_INFO['purchase'],
        'title': '제시 조건 선택',
        'choices': {**QUESTION_INFO['purchase']['choices'], 'not_run': '미실시'},
    },
}
SURVEY_V2_DOMAINS = tuple(SURVEY_V2_INFO)
SURVEY_V2_PROMPTS = (
    '상품이 해결하는 문제는 이 인물에게 얼마나 관련 있습니까? 인물에 명시된 목적과 활동으로 관련성이 높음, 일부 있음, 없음 중에서 판단하세요. '
    '상품의 대상 고객 설명을 인물의 실제 필요로 바꾸지 말고, 관련성을 판단할 근거가 없으면 판단 불가를 선택하세요.',
    '이 인물은 현재 방법으로 상품이 해결하려는 문제를 얼마나 해결하고 있습니까? '
    '명시된 현재 방법과 해결 수준을 평가하세요. 현재 방법이 없다고 명시된 경우만 현재 방법 없음을 선택하고, 정보가 없으면 판단 불가를 선택하세요.',
    '이 인물이 상품 설명을 처음 읽는다고 가정할 때 제품의 주된 목적이 얼마나 명확합니까? '
    '설명으로 예상하는 명확성을 판단하고 실제 이해도 검사나 사용 경험을 수행했다고 가정하지 마세요.',
    '이 상품은 인물에게 명시된 현재 방법보다 문제 해결에 얼마나 도움이 됩니까? '
    '현재 방법보다 도움, 비슷함, 불리함을 비교하세요. 해결할 문제가 없거나 현재 방법이 없다고 명시되어 비교가 성립하지 않는 경우만 해당 없음을 선택하세요. '
    '현재 방법이나 비교 근거가 제공되지 않은 것은 판단 불가입니다.',
    '상품에 명시된 대안과 비교할 때 이 제품에 구분되는 이점이 있습니까? 제공된 대안의 기능과 조건만 비교하세요. '
    '이 상품에 비교 대상이 적용되지 않는다고 명시된 경우만 해당 없음을 선택하세요. 대안 정보가 없거나 부족하면 판단 불가를 선택하세요. '
    '상품 문서의 대안을 이 인물이 현재 사용한다고 가정하지 마세요.',
    '이 인물은 제시한 핵심 효과의 근거를 얼마나 신뢰할 수 있습니까? 제공된 주장과 근거에 대한 예상 신뢰성만 판단하세요. '
    '실제 효과를 검증했다고 가정하지 마세요. 근거를 신뢰하기 어렵다는 정보와 근거가 제공되지 않은 상황을 구분하고, 후자는 판단 불가를 선택하세요.',
    '현재 방법에서 이 상품으로 바꿀 때 명시된 이전과 학습 요구는 이 인물에게 어느 정도 부담입니까? 예상 노력만 판단하세요. '
    '현재 방법이 없거나 전환 절차가 필요 없다고 명시되어 전환이 적용되지 않는 경우만 해당 없음을 선택하세요. 현재 방법이나 요구 조건이 없으면 판단 불가를 선택하세요.',
    '제공된 사용 기회와 환경에서 이 인물이 상품을 사용할 의향이 있습니까? 사용 의향 있음, 사용을 고려함, 사용 의향 없음 중에서 판단하세요. '
    '중간 응답은 판단 불가가 아닙니다. 명시된 기회와 현재 방식으로 판단하고 부족한 사실이나 실제 사용 경험을 만들지 마세요.',
    '판매가격 없이 이 인물이 적정하다고 느끼는 가격대를 명시된 구간 중 하나로 선택하세요. '
    '통화와 결제 주기를 그대로 사용하세요. 선택한 구간은 지불할 최대가격이나 정확한 추정 금액이 아닙니다. 소득이나 예산을 만들지 말고 근거가 부족하면 판단 불가를 선택하세요.',
    '원문 인물·상품 정보와 제시한 판매조건만으로 구매·사용, 보류, 거절 중 하나를 선택하세요. '
    '다른 설문 답이나 적정가격 평가를 가정하지 마세요. 무료여도 사용하지 않을 수 있습니다. 소득, 예산, 현재 도구나 구매 이력을 만들지 말고 근거가 부족하면 판단 불가를 선택하세요.',
)
SURVEY_V2_QUESTIONS = [
    {'id': f'{domain.replace("_", "-")}-survey-v2', 'domain': domain,
     'prompt': prompt, 'choices': list(SURVEY_V2_INFO[domain]['choices'])}
    for domain, prompt in zip(SURVEY_V2_DOMAINS, SURVEY_V2_PROMPTS)
]


def question_info(domain, scenario_id=None):
    return (SURVEY_V2_INFO if scenario_id == SURVEY_V2_SCENARIO_ID else QUESTION_INFO)[domain]


def survey_meanings(job):
    if job.scenario.get('id') == SURVEY_V2_SCENARIO_ID:
        if job.question['domain'] in {'fair_price', 'purchase'}:
            return {**choice_meanings(job), 'not_run': '미실시'}
        return dict(question_info(job.question['domain'], SURVEY_V2_SCENARIO_ID)['choices'])
    if job.question['domain'] in {'usage', 'fair_price', 'purchase'}:
        return choice_meanings(job)
    return dict(QUESTION_INFO[job.question['domain']]['choices'])


def missing_fields(domain, scenario_id=None):
    return tuple(dict.fromkeys((*question_info(domain, scenario_id)['missing'], 'value_basis')))
