"""Markdown remains the input; price metadata is optional and never guessed."""
import re
from decimal import Decimal, InvalidOperation
from persona_lab.contracts import require, CURRENCIES, BILLINGS, validate_money

MAX_DOCUMENT_CHARS = 20000
DOCUMENT_TEMPLATE = "## 해결할 문제\n\n## 주요 기능\n\n## 현재 대안과의 차이\n\n## 효익의 근거\n\n## 사용 방법\n\n## 도입 조건·제약\n\n## 자료·권한 조건\n"


def money_from_fields(value, allow_empty=False):
    require(isinstance(value, dict) and set(value) == {'amount', 'currency', 'billing'}, '금액 입력 형식을 확인하세요.')
    currency, billing, amount = value['currency'], value['billing'], value['amount']
    require(isinstance(currency,str) and currency in CURRENCIES and isinstance(billing,str) and billing in BILLINGS, '통화와 결제 주기를 확인하세요.')
    require(isinstance(amount,str) and len(amount)<=24, '금액 형식을 확인하세요.')
    if not amount.strip() and allow_empty: return None
    require(re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', amount.strip()) is not None, '금액은 0 이상의 숫자로 입력하세요.')
    decimals=CURRENCIES[currency]
    require('.' not in amount or len(amount.rsplit('.',1)[1])<=decimals, f'{currency} 금액은 소수 {decimals}자리까지 입력하세요.')
    minor=Decimal(amount.strip()) * (10**decimals)
    return validate_money({'amount_minor':int(minor),'currency':currency,'billing':billing})


def validate_pricing(pricing, allow_empty=False):
    require(isinstance(pricing,dict) and set(pricing)=={'state','amount','currency','billing'}, '가격 입력 형식을 확인하세요.')
    require(isinstance(pricing['state'],str) and pricing['state'] in {'unset','free','paid'} and isinstance(pricing['amount'],str), '가격 상태와 금액을 확인하세요.')
    money={key:pricing[key] for key in ('amount','currency','billing')}
    if pricing['state']!='paid':money['amount']='0'
    value=money_from_fields(money,allow_empty)
    if pricing['state']=='unset':return None
    if pricing['state']=='paid' and value is not None:require(value['amount_minor']>0, '가격이 0이면 무료를 선택하세요.')
    return value


def has_document_content(document):
    return any(line.strip() and not re.fullmatch(r'\s*#{1,6}(?:\s+.*)?',line) for line in document.splitlines())


def pricing_fields(price):
    if price is None:return {'state':'unset','amount':'','currency':'JPY','billing':'one_time'}
    amount=str(Decimal(price['amount_minor'])/(10**CURRENCIES[price['currency']]))
    return {'state':'free' if price['amount_minor']==0 else 'paid','amount':amount,'currency':price['currency'],'billing':price['billing']}


def valuation_fields(product=None):
    product=product or {}
    unit=product.get('valuation_unit') or product.get('price') or {'currency':'JPY','billing':'one_time'}
    divisor=10**CURRENCIES[unit['currency']]
    bands=product.get('valuation_bands') or []
    mode=product.get('valuation_mode','manual' if 'valuation_bands' in product else 'auto')
    return {'mode':mode,**{key:unit[key] for key in ('currency','billing')},'boundaries':[str(Decimal(band['low_minor'])/divisor) for band in bands[1:]] if bands else ['','','']}


def valuation_from_fields(value):
    require(isinstance(value,dict) and set(value) in ({'currency','billing','boundaries'},{'mode','currency','billing','boundaries'}), '평가 가격대 형식을 확인하세요.')
    mode=value.get('mode','manual')
    require(isinstance(mode,str) and mode in {'auto','manual'}, '평가 가격대 방식을 확인하세요.')
    boundaries=value['boundaries']
    require(isinstance(boundaries,list) and len(boundaries)==3 and all(isinstance(amount,str) and len(amount)<=24 for amount in boundaries), '평가 가격대 경계값 3개를 확인하세요.')
    unit={key:value[key] for key in ('currency','billing')}
    money_from_fields({**unit,'amount':'0'})
    if mode=='auto':return unit,[]
    if not any(amount.strip() for amount in boundaries):return unit,[]
    require(all(amount.strip() for amount in boundaries), '평가 가격대 경계값 3개를 모두 입력하세요.')
    amounts=[money_from_fields({**unit,'amount':amount})['amount_minor'] for amount in boundaries]
    require(0<amounts[0]<amounts[1]<amounts[2], '평가 가격대는 0보다 큰 값부터 오름차순으로 입력하세요.')
    lows=[0,*amounts]
    return unit,[{'id':f'price_{index}','low_minor':low,'high_minor':amounts[index]-1 if index<3 else None} for index,low in enumerate(lows)]

def item_name(document, fallback='아이템'):
    match = re.search(r'^#{1,6}\s+(.+?)\s*#*\s*$', document, re.M)
    return (match.group(1).strip() if match else fallback)[:120]


def price_from_document(document):
    text = re.sub(r'[*_`]', '', document).replace('−', '-')
    matches = re.findall(r'(?i)(?<![\w.,])(?:\b(JPY|KRW|USD|EUR)\s*([+-]?[0-9][0-9,]*(?:\.[0-9]+)?)|([+-]?[0-9][0-9,]*(?:\.[0-9]+)?)\s*(JPY|KRW|USD|EUR|円|엔|원|달러))', text)
    prices = set()
    for before_currency, before_amount, after_amount, after_currency in matches:
        currency = (before_currency or after_currency).upper()
        currency = {'円': 'JPY', '엔': 'JPY', '원': 'KRW', '달러': 'USD'}.get(currency, currency)
        number = before_amount or after_amount
        if ',' in number and not re.fullmatch(r'[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?', number):
            return None
        try:
            amount = Decimal(number.replace(',', '')) * (100 if currency in {'USD','EUR'} else 1)
        except InvalidOperation:
            return None
        if amount != amount.to_integral_value() or not 0 <= amount <= 9223372036854775807:
            return None
        prices.add((currency, int(amount)))
    billings = set()
    for billing, pattern in (
        ('one_time', r'일시불|一括|買い切り|one[- ]time'),
        ('monthly', r'매월|월간|월\s*구독|月額|monthly|/month'),
        ('annual', r'매년|연간|年額|annual|yearly|/year'),
    ):
        if re.search(pattern, text, re.I): billings.add(billing)
    if len(prices) != 1 or len(billings) != 1:
        return None
    currency, amount = prices.pop()
    return {'amount_minor': amount, 'currency': currency, 'billing': billings.pop()}


def product_from_item(item, ordinal, allow_empty=False):
    document = item['document']
    require(len(document) <= MAX_DOCUMENT_CHARS, f'아이템 {ordinal} 문서는 {MAX_DOCUMENT_CHARS:,}자까지 사용할 수 있습니다.')
    if 'pricing' in item:
        require(isinstance(item.get('name'),str) and len(item['name'])<=120, '상품명은 120자까지 입력하세요.')
        require(allow_empty or bool(item['name'].strip()), f'아이템 {ordinal}의 상품명을 입력하세요.')
        require(allow_empty or has_document_content(document), f'아이템 {ordinal}의 상품 내용을 입력하세요.')
        price=validate_pricing(item['pricing'],allow_empty)
        return {'id':item['id'],'name':item['name'].strip() or f'아이템 {ordinal}','intro':document or '미작성 문서','document':document or '미작성 문서','features':[],'price':price,'price_state':item['pricing']['state'],'price_origin':'explicit_form','valuation_unit':{key:item['pricing'][key] for key in ('currency','billing')}}
    require(bool(document.strip()), f'아이템 {ordinal}의 문서를 입력하세요.')
    return {'id': item['id'], 'name': item_name(document, f'아이템 {ordinal}'), 'intro': document, 'document': document, 'features': [], 'price': price_from_document(document)}
