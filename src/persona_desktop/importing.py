"""Read editable settings without loading exported run state or external resources."""
import copy
import uuid

from persona_lab.contracts import require, validate_experiment
from persona_lab.responses import SURVEY_V2_SCENARIO_ID, SURVEY_V3_SCENARIO_ID, SURVEY_V4_SCENARIO_ID
from .documents import (
    MAX_DOCUMENT_CHARS, item_name, price_from_document, pricing_fields,
    validate_pricing, valuation_fields, valuation_from_fields,
)


UNSUPPORTED_WORKFLOW = '이전 버전의 실험 방식은 설정을 가져올 수 없습니다. 현재 상품 설문 실험 설정을 선택하세요.'


def _workflow(value):
    require(isinstance(value, str) and value in {SURVEY_V2_SCENARIO_ID, SURVEY_V3_SCENARIO_ID, SURVEY_V4_SCENARIO_ID}, UNSUPPORTED_WORKFLOW)
    return value


def _title(value):
    require(isinstance(value, str) and 0 < len(value.strip()) and len(value) <= 120,
            '실험 이름은 1~120자로 입력하세요.')
    return value.strip()


def _panel(value, seed, frozen=False):
    require(isinstance(value, dict), '대상 설정 형식을 확인하세요.')
    panel = copy.deepcopy(value)
    if frozen and 'selected_uuids' in panel:
        selected = panel.pop('selected_uuids')
        require(isinstance(selected, list) and bool(selected)
                and all(isinstance(identifier, str) and identifier for identifier in selected),
                '고정된 대상 목록 형식을 확인하세요.')
        require(len(set(selected)) == len(selected), '고정된 대상 목록에 중복된 식별자가 있습니다.')
        require(panel.get('selection', 'random') == 'random', '고정된 대상은 무작위 추출 설정이어야 합니다.')
        panel.setdefault('selection', 'random')
        panel.setdefault('sample_size', len(selected))
        require(type(panel['sample_size']) is int and len(selected) <= panel['sample_size'],
                '고정된 대상 수가 추출 인원보다 많습니다.')
        panel.setdefault('sample_seed', seed)
    return panel


def _item(value, ordinal):
    require(isinstance(value, dict) and set(value) <= {'id', 'name', 'document', 'pricing', 'valuation'},
            f'아이템 {ordinal} 설정 형식을 확인하세요.')
    document = value.get('document')
    require(isinstance(document, str) and len(document) <= MAX_DOCUMENT_CHARS,
            f'아이템 {ordinal} 문서는 {MAX_DOCUMENT_CHARS:,}자까지 사용할 수 있습니다.')
    name = value.get('name', item_name(document, f'아이템 {ordinal}'))
    require(isinstance(name, str) and len(name) <= 120, f'아이템 {ordinal} 상품명은 120자까지 입력하세요.')
    pricing = copy.deepcopy(value.get('pricing', pricing_fields(price_from_document(document))))
    validate_pricing(pricing, allow_empty=True)
    valuation = copy.deepcopy(value.get('valuation', valuation_fields({
        'valuation_unit': {key: pricing[key] for key in ('currency', 'billing')},
    })))
    valuation_from_fields(valuation)
    return {'id': uuid.uuid4().hex, 'name': name, 'document': document,
            'pricing': pricing, 'valuation': valuation}


def _draft(value, workflow=None, frozen=False):
    require(isinstance(value, dict), '실험 설정은 JSON 객체여야 합니다.')
    workflow = _workflow(value.get('workflow', workflow or SURVEY_V4_SCENARIO_ID))
    items, settings = value.get('items'), value.get('settings')
    require(isinstance(items, list) and 1 <= len(items) <= 5, '아이템은 1~5개까지 가져올 수 있습니다.')
    require(isinstance(settings, dict) and set(settings) == {'seed', 'repeats'}
            and type(settings['seed']) is int and type(settings['repeats']) is int,
            '실험 시드와 반복 횟수는 정수로 입력하세요.')
    require(settings['repeats'] > 0, '반복 횟수는 1 이상이어야 합니다.')
    return {'title': _title(value.get('title')), 'workflow': workflow,
            'items': [_item(item, index) for index, item in enumerate(items, 1)],
            'panel': _panel(value.get('panel'), settings['seed'], frozen),
            'settings': copy.deepcopy(settings)}


def _spec(value):
    require(isinstance(value, dict), '실험 실행 설정 형식을 확인하세요.')
    scenario = value.get('scenario')
    require(isinstance(scenario, dict), '실험 방식 설정을 확인하세요.')
    workflow = _workflow(scenario.get('id'))
    spec = copy.deepcopy(value)
    spec['panel'] = _panel(spec.get('panel'), spec.get('seed'), frozen=True)
    validate_experiment(spec)
    items = []
    for ordinal, product in enumerate(spec['products'], 1):
        document = product.get('document', product['intro'])
        price = product.get('price')
        pricing = pricing_fields(price)
        if 'price_state' in product:
            require(product['price_state'] == pricing['state'], f'아이템 {ordinal} 판매가격 상태와 금액이 일치하지 않습니다.')
        items.append(_item({'name': product['name'], 'document': document,
                            'pricing': pricing, 'valuation': valuation_fields(product)}, ordinal))
    return {'title': _title(value.get('title', '가져온 실험')), 'workflow': workflow,
            'items': items, 'panel': spec['panel'],
            'settings': {'seed': spec['seed'], 'repeats': spec['repeats']}}


def normalize_settings(value):
    """Return only editable fields from a draft, replay snapshot or current spec."""
    require(isinstance(value, dict), '설정 파일은 JSON 객체여야 합니다.')
    if 'draft' in value:
        workflow = None
        if 'spec' in value:
            spec = value['spec']
            require(isinstance(spec, dict) and isinstance(spec.get('scenario'), dict), '실험 방식 설정을 확인하세요.')
            workflow = _workflow(spec['scenario'].get('id'))
        return _draft(value['draft'], workflow, frozen=True)
    if 'items' in value:
        return _draft(value)
    if 'spec' in value:
        return _spec(value['spec'])
    if 'products' in value:
        return _spec(value)
    require(False, '실험 설정을 찾을 수 없습니다. 설정 JSON 또는 재실행 설정 파일을 선택하세요.')
