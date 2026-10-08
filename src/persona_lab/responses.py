"""Finite response questions and price-blind inputs for new experiments."""
import re
from decimal import Decimal
from .contracts import CURRENCIES

SCENARIO_ID = 'product-response-v1'
LINKED_SCENARIO_ID = 'product-response-v2'
DECISION_SCENARIO_ID = 'product-decision-v1'
SURVEY_SCENARIO_ID = 'product-survey-v1'
SURVEY_V2_SCENARIO_ID = 'product-survey-v2'
FINITE_SCENARIO_IDS = {DECISION_SCENARIO_ID, SURVEY_SCENARIO_ID, SURVEY_V2_SCENARIO_ID}
LINKED_SCENARIO_IDS = {LINKED_SCENARIO_ID, DECISION_SCENARIO_ID, SURVEY_SCENARIO_ID}
RESPONSE_SCENARIO_IDS = {SCENARIO_ID, *LINKED_SCENARIO_IDS, *FINITE_SCENARIO_IDS}
REASON_PATTERN = r'^[가-힣][가-힣0-9 .,!?·:()-]{0,159}$'
MISSING_PATTERN = r'^[가-힣][가-힣0-9 .,!?·:()-]{0,79}$'
REASON_OPTIONS = {
    'usage': {
        'use': {'profile_fit':'인물의 활동과 상품 용도가 맞음','use_value':'상품 기능을 활용할 가치가 있음'},
        'not_use': {'low_need':'추가로 사용할 필요가 낮음','current_method_sufficient':'현재 방식으로 충분함'},
    },
    'fair_price': {choice:{'feature_value':'상품 기능의 활용 가치','feature_scope':'상품 제공 범위와 제약','alternative_value':'현재 대안과 비교한 추가 가치','profile_fit':'인물의 활동과 상품의 관련성'} for choice in ('price_0','price_1','price_2','price_3')},
    'purchase': {
        'buy': {'use_value':'상품의 활용 가치를 긍정적으로 평가함','acceptable_offer':'제시 조건을 수용할 수 있음'},
        'defer': {'compare_alternatives':'현재 대안과 더 비교하려는 선택','adoption_friction':'이전이나 학습 부담을 더 검토하려는 선택'},
        'decline': {'low_need':'추가 사용 필요가 낮음','current_method_sufficient':'현재 방식으로 충분함','adoption_friction':'이전이나 학습 부담이 큼','offer_mismatch':'제시 조건이나 제공 범위가 맞지 않음','privacy_concern':'자료 관리나 권한 조건이 부담됨'},
    },
}
MISSING_FIELDS = {
    'usage_goal':'구체적인 활용 목적','usage_environment':'사용 환경과 도입 가능 조건','usage_frequency':'사용 빈도와 중요도','current_method':'현재 사용하는 도구와 불편한 점','feature_scope':'주요 기능의 제공 범위','license_scope':'사용 가능한 기기와 라이선스 범위','value_basis':'개인 선호와 추가 가치의 판단 근거','privacy_terms':'자료 저장과 권한 조건','switching_effort':'자료 이전과 학습에 드는 노력',
}
MISSING_FIELDS.update(alternatives_info='비교할 대안의 기능과 조건', claim_evidence='핵심 효과에 대한 주장과 근거')
DOMAIN_MISSING = {'usage':['usage_goal','usage_environment','current_method'],'fair_price':['usage_goal','usage_frequency','current_method','feature_scope','license_scope','value_basis'],'purchase':['usage_goal','usage_environment','current_method','feature_scope','license_scope','privacy_terms','switching_effort']}


def reason_options(domain, choice):
    return {'missing_context':'판단에 필요한 정보가 부족함'} if choice=='unknown' else REASON_OPTIONS[domain][choice]


def money_label(value):
    amount=Decimal(value['amount_minor'])/(10**CURRENCIES[value['currency']])
    return f'{amount:,f} {value["currency"]} · '+{'one_time':'일시불','monthly':'월간','annual':'연간'}[value['billing']]


def choice_meanings(job):
    if job.question['domain']=='usage':return {'use':'활용할 의향이 있음','not_use':'추가로 사용할 의향이 없음','unknown':'관련 정보 부족으로 판단할 수 없음'}
    if job.question['domain']=='purchase':
        free=job.product['price']['amount_minor']==0
        return {'buy':'무료 상품을 사용하겠음' if free else '제시 가격으로 구매하겠음','defer':'선택을 보류하겠음','decline':'무료여도 사용하지 않겠음' if free else '제시 조건으로 구매하지 않겠음','unknown':'관련 정보 부족으로 판단할 수 없음'}
    unit=job.product['valuation_unit'];divisor=10**CURRENCIES[unit['currency']];period={'one_time':'일시불','monthly':'월간','annual':'연간'}[unit['billing']]
    labels={}
    for band in job.product['valuation_bands']:
        low=Decimal(band['low_minor'])/divisor;high=None if band['high_minor'] is None else Decimal(band['high_minor'])/divisor
        labels[band['id']]=(f'{low:,f} {unit["currency"]} 이상' if high is None else f'{(Decimal(band["high_minor"]+1)/divisor):,f} {unit["currency"]} 미만' if low==0 else f'{low:,f}–{high:,f} {unit["currency"]}')+' · '+period
    return {**labels,'unknown':'가격대를 판단할 근거가 부족함'}


def explain(domain, choice, code, missing, free=False):
    if choice=='unknown':
        title={'usage':'사용 의향','fair_price':'적정가격','purchase':'최종 선택'}[domain]
        return ', '.join(MISSING_FIELDS[field] for field in missing)+' 정보가 부족해 '+title+'을 판단하지 못했습니다.'
    if domain=='fair_price':
        return {'feature_value':'상품 기능의 활용 가치를 고려해 이 구간이 적정하다고 평가했습니다.','feature_scope':'상품의 제공 범위와 제약을 고려해 이 구간이 적정하다고 평가했습니다.','alternative_value':'현재 대안과 비교한 추가 가치를 고려해 이 구간이 적정하다고 평가했습니다.','profile_fit':'인물의 활동과 상품의 관련성을 고려해 이 구간이 적정하다고 평가했습니다.'}[code]
    if domain=='usage':
        return {'profile_fit':'인물의 활동과 상품 용도가 맞아 활용할 수 있다고 평가했습니다.','use_value':'상품 기능을 활용할 가치가 있어 사용 의향이 있다고 평가했습니다.','low_need':'추가로 사용할 필요가 낮아 사용 의향이 없다고 평가했습니다.','current_method_sufficient':'현재 방식으로 충분해 추가 사용 의향이 없다고 평가했습니다.'}[code]
    if choice=='buy':return '상품의 활용 가치를 긍정적으로 평가해 '+('사용을' if free else '구매를')+' 선택했습니다.' if code=='use_value' else '제시된 조건을 수용할 수 있다고 평가해 '+('사용을' if free else '구매를')+' 선택했습니다.'
    if choice=='defer':return '현재 대안과 더 비교하려는 판단으로 선택을 보류했습니다.' if code=='compare_alternatives' else '이전이나 학습에 드는 노력을 더 검토하려는 판단으로 선택을 보류했습니다.'
    action='사용하지 않음' if free else '구매하지 않음'
    return {'low_need':'추가 사용 필요가 낮다고 평가해 ','current_method_sufficient':'현재 방식으로 충분하다고 평가해 ','adoption_friction':'자료 이전이나 새 사용법 학습의 부담이 크다고 평가해 ','offer_mismatch':'제시 조건이나 제공 범위가 맞지 않는다고 평가해 ','privacy_concern':'자료 관리나 권한 조건이 부담된다고 평가해 '}[code]+action+'을 선택했습니다.'
QUESTIONS = [
    {'id':'usage-v1','domain':'usage','prompt':'이 상품을 자신의 생활이나 업무에 사용하고 싶을지 판단하세요. 판매가격은 제시되지 않았습니다. 상품의 용도, 현재 방식과 사용 환경을 근거로 사용 의향을 선택하세요. 실제 사용한 경험을 만들지 마세요.','choices':['use','not_use','unknown']},
    {'id':'fair-price-v1','domain':'fair_price','prompt':'이 인물이 상품에 적정하다고 생각할 가격대를 제시된 통화와 결제 주기에서 선택하세요. 판매가격이나 공통 구매 상한을 가정하지 마세요. 정보가 부족하면 구체적인 부족 정보를 적으세요.','choices':['price_0','price_1','price_2','price_3','unknown']},
    {'id':'choice-v1','domain':'purchase','prompt':'제시된 가격과 조건에서 이 상품을 선택할지 판단하세요. 무료여도 필요성, 이전 부담, 학습 시간, 개인정보와 현재 방식을 고려해 사용하지 않을 수 있습니다. 실제 구매나 사용 경험을 만들지 마세요.','choices':['buy','defer','decline','unknown','not_run']},
]
LINKED_QUESTIONS = [{**question,'id':question['id'].replace('-v1','-v2')} for question in QUESTIONS]
LINKED_QUESTIONS[1] = {**LINKED_QUESTIONS[1], 'prompt':'판매가격 없이 개인별 적정 금액과 그 근거를 평가하세요. 금액을 가격대로 묶는 처리는 코드가 수행합니다.'}
LINKED_QUESTIONS[2] = {**LINKED_QUESTIONS[2], 'prompt':'같은 인물·아이템·회차의 사용 의향과 가격평가, 제시한 판매조건을 함께 보고 최종 선택과 수용·거절 근거를 평가하세요.'}
DECISION_QUESTIONS = [{**question, 'id':question['id'].replace('-v1','-decision-v1')} for question in QUESTIONS]
DECISION_QUESTIONS[1] = {**DECISION_QUESTIONS[1], 'prompt':'판매가격 없이 이 인물이 상품에 적정하다고 생각할 가격대를 허용된 구간 중에서 선택하세요. 관련 근거가 부족하면 판단 불가를 선택하세요.'}
DECISION_QUESTIONS[2] = {**DECISION_QUESTIONS[2], 'prompt':'같은 인물·아이템·회차의 두 선행 선택과 제시한 판매조건을 함께 보고 허용된 최종 선택 하나를 고르세요.'}


def price_bands(currency):
    # Versioned scenario choices, not discovered precision or currency conversion.
    step = 10000 if currency == 'KRW' else 1000
    return [{'id':f'price_{i}','low_minor':i*step,'high_minor':(i+1)*step-1 if i<3 else None} for i in range(4)]


PRICE_LINE = re.compile(r'(?:JPY|KRW|USD|EUR|[¥￥$€₩])\s*\d|\d[\d,.]*\s*(?:JPY|KRW|USD|EUR|円|엔|원|달러)|(?:가격|価格|price|요금|料金|cost|결제 방식)\s*[:：]|(?:^|\s)(?:무료|유료|free|paid)(?:\s|$)', re.I)


def input_product(product, domain):
    if domain not in {'usage','fair_price'}:
        return dict(product)
    document = '\n'.join(line for line in product.get('document',product['intro']).splitlines() if not PRICE_LINE.search(line))
    return {key:value for key,value in {**product,'intro':document,'document':document,'price':None}.items() if key not in {'price_state','price_origin'}}
