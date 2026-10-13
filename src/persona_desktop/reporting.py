"""Portable survey reports made only from stored counts and frozen inputs."""
import csv
import io
import json
from collections import Counter
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from html import escape

from persona_lab.contracts import CURRENCIES, require
from persona_lab.responses import SURVEY_V2_SCENARIO_ID
from persona_lab.tags import tag_metadata


STATE_LABELS = {'unknown': '판단 불가', 'error': '오류', 'pending': '대기', 'not_run': '미실시', 'not_applicable': '해당 없음'}
BILLING = {'one_time': '일시불', 'monthly': '월간', 'annual': '연간'}
STATE_COLORS = {'unknown': '#9298A1', 'error': '#B24338', 'pending': '#ACAFC1', 'not_run': '#CED2D1', 'not_applicable': '#9B8C7A'}
PRICE_COLORS = ('#CBDCE6', '#88B0C6', '#4D85A4', '#245C7A')
POSITIVE_CHOICES = {'use', 'buy', 'now', 'clear', 'offered_product', 'accept', 'proceed', 'relevant', 'better', 'distinct', 'supported', 'low', 'sufficient'}
HOLD_CHOICES = {'defer', 'later', 'request_evidence', 'seek_help', 'consider', 'partly_relevant', 'partial', 'partly_clear', 'similar', 'limited', 'partly_supported', 'moderate'}
# Geometry matches web/brand-mark.svg; inline SVG keeps exported reports portable.
BRAND_MARK = '<svg class="brand-mark" viewBox="0 0 200 200" fill="currentColor" aria-hidden="true"><path d="M36 8 H120 C133.255 8 144 18.745 144 32 V62 H90 C76.745 62 66 72.745 66 86 V165 H32 C18.745 165 8 154.255 8 141 V36 C8 20.536 20.536 8 36 8 Z"/><path d="M144 62 H168 C181.255 62 192 72.745 192 86 V168 C192 181.255 181.255 192 168 192 H104 C90.745 192 80 181.255 80 168 V148 C80 134.745 90.745 124 104 124 H120 C133.255 124 144 113.255 144 100 Z"/></svg>'
CSS = '''
@page { size: A4; margin: 16mm 15mm 17mm; }
* { box-sizing: border-box; } body { margin: 0; color: #182B38; background: #F4F3EF; font: 13px/1.6 -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", sans-serif; }
main { max-width: 900px; margin: 28px auto; padding: 42px 50px; background: #FFFEFA; }
h1 { margin: 8px 0 14px; font-size: 30px; line-height: 1.25; letter-spacing: -.7px; } h2 { margin: 0 0 16px; font-size: 23px; line-height: 1.3; } h3 { margin: 20px 0 10px; font-size: 16px; }
p { margin: 7px 0; } .muted, small { color: #586874; } .meta { padding: 10px 0 15px; border-bottom: 1px solid #CAD3D7; }
.page { margin-top: 45px; border-top: 2px solid #245C7A; padding-top: 22px; } .first { margin: 0; border: 0; padding: 0; } .columns { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
.facts { margin: 18px 0 24px; padding: 0 0 0 18px; } .facts li { margin: 7px 0; } .chart { display: block; width: 100%; height: auto; font: 12px -apple-system, "Apple SD Gothic Neo", sans-serif; } .chart text { fill: #182B38; }
.legend { display: flex; flex-wrap: wrap; gap: 3px 15px; margin: 5px 0 12px; font-size: 11px; } .legend span { display: inline-flex; align-items: baseline; gap: 5px; } .swatch { display: inline-block; width: 8px; height: 8px; flex: none; border-radius: 2px; }
.distribution { break-inside: avoid; margin: 12px 0 16px; } .distribution h3 { margin: 0 0 3px; } table { border-collapse: collapse; width: 100%; margin: 10px 0 18px; font-size: 11px; } th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid #CAD3D7; vertical-align: top; overflow-wrap: anywhere; } th { color: #586874; font-weight: 600; } thead { display: table-header-group; } tr { break-inside: avoid; } .numeric { text-align: right; font-variant-numeric: tabular-nums; } .heat th:first-child { width: 115px; } .heat th { word-break: keep-all; overflow-wrap: normal; } .joint { table-layout: fixed; } .joint th:first-child { width: 35%; } .joint th, .joint td { padding: 4px 3px; word-break: keep-all; overflow-wrap: normal; } .methods { table-layout: fixed; } .methods th { width: 100px; word-break: keep-all; overflow-wrap: normal; } .methods td { overflow-wrap: anywhere; } .heat td { text-align: right; font-variant-numeric: tabular-nums; } .product-summary { border-top: 1px solid #CAD3D7; padding-top: 10px; margin: 12px 0 20px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; margin: 8px 0 18px; } details { margin: 10px 0; } summary { color: #245C7A; cursor: pointer; } .note { font-size: 11px; color: #586874; } .case { border-top: 1px solid #CAD3D7; padding-top: 9px; break-inside: avoid; } .question { break-inside: avoid; margin: 12px 0; } .question strong { display: block; } .document { border-top: 1px solid #CAD3D7; padding-top: 12px; } .document + .document { break-before: page; } footer { display: flex; align-items: center; gap: 8px; border-top: 1px solid #CAD3D7; margin-top: 28px; padding-top: 10px; color: #586874; font-size: 10px; } .brand-mark { width: 22px; height: 22px; flex: none; color: #245C7A; } .wordmark { color: #182B38; font-weight: 600; } ::selection { background: #DFE8ED; color: #182B38; } summary:focus-visible { outline: 2px solid #245C7A; outline-offset: 3px; }
@media (max-width: 700px) { main { margin: 0; padding: 24px 20px; } .columns { grid-template-columns: 1fr; } table { font-size: 10px; } th, td { padding: 5px; } }
@media print { body { background: #FFFEFA; font-size: 10.5pt; line-height: 1.5; -webkit-print-color-adjust: exact; print-color-adjust: exact; } main { max-width: none; margin: 0; padding: 0; } h1 { font-size: 26px; } h2 { font-size: 21px; } h3 { font-size: 13px; } .page { break-before: page; margin: 0; border: 0; padding: 0; } .first { break-before: auto; } .columns { gap: 18px; } .legend { font-size: 8.5pt; } table { font-size: 9pt; } th, td { padding: 5px 6px; } details > summary { display: none; } details > *:not(summary) { display: block !important; } footer { font-size: 8pt; } }
'''


def pct(value, denominator):
    return f'{100 * value / denominator:.1f}%' if denominator else '0.0%'


def amount(value, currency):
    number = Decimal(value) / 10 ** CURRENCIES[currency]
    return f'{number:,.{CURRENCIES[currency]}f}'


def offer_label(product):
    price = product.get('price')
    if price is None:
        return '판매가격 미입력'
    return ('무료' if price['amount_minor'] == 0 else amount(price['amount_minor'], price['currency']) + ' ' + price['currency']) + ' · ' + BILLING[price['billing']]


def display_name(response, product):
    if sum(item['name'] == product['name'] for item in response['products']) > 1:
        index = next(index for index, item in enumerate(response['products']) if item['id'] == product['id'])
        return f'{index + 1} · {product["name"]}'
    return product['name']


def tag_condition(panel, tag_labels=None, locale='ko'):
    tags = panel.get('tags', [])
    if not tags:
        return ''
    metadata = tag_labels or {}
    labels = ' · '.join('#' + (metadata.get(tag, {}).get(locale) or
                              tag_metadata(tag, locale=locale)['label']) for tag in tags)
    return labels + ' · ' + ('모두' if panel.get('tag_mode') == 'all' else '하나 이상')


def panel_conditions(panel):
    return {key: value for key, value in panel.items()
            if key not in {'selected_uuids', 'tags', 'tag_mode'}}


def datetime_label(value):
    if not value:
        return '실행일 미기록'
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        moment = moment.astimezone(timezone(timedelta(hours=9)))
        return f'{moment.year}년 {moment.month}월 {moment.day}일 {moment:%H:%M} · 한국시간'
    except (TypeError, ValueError):
        return value


def status_label(value):
    return {'ready': '준비', 'running': '실행 중', 'paused': '중단', 'completed': '완료',
            'failed': '오류', 'stopping': '중단 중'}.get(value, value)


def document_groups(products):
    groups = {}
    for product in products:
        groups.setdefault(product['document'], []).append(product)
    return groups.items()


def label(response, product, domain, choice):
    if choice in STATE_LABELS:
        return STATE_LABELS[choice]
    if domain == 'fair_price' and choice.startswith('price_'):
        band = next((band for band in product.get('valuation_bands', []) if band['id'] == choice), None)
        if band:
            unit = product['valuation_unit']
            low, high, currency = band['low_minor'], band['high_minor'], unit['currency']
            text = amount(low, currency) + ' ' + currency + ' 이상' if high is None else amount(high + 1, currency) + ' ' + currency + ' 미만' if low == 0 else amount(low, currency) + '–' + amount(high, currency) + ' ' + currency
            return text + ' · ' + BILLING[unit['billing']]
    if domain == 'purchase':
        free = product.get('price') is not None and product['price']['amount_minor'] == 0
        return {'buy': '사용' if free else '구매', 'defer': '보류', 'decline': '사용하지 않음' if free else '구매하지 않음'}.get(choice, choice)
    question = next(question for question in response['questions'] if question['domain'] == domain)
    return question['labels'].get(choice, choice)


def valuation_condition(response, product):
    calibration = product.get('valuation_calibration', {})
    mode = '자동' if calibration.get('mode') == 'auto' else '수동'
    bands = product.get('valuation_bands', [])
    if not bands:
        if not calibration and response.get('workflow') != SURVEY_V2_SCENARIO_ID:
            return '이전 질문 계약'
        return mode + ' · 미실시 · ' + (calibration.get('reason') or '평가 가격대가 입력되지 않았습니다.')
    return mode + ' · ' + ' / '.join(label(response, product, 'fair_price', band['id']) for band in bands)


def color(choice):
    if choice in STATE_COLORS:
        return STATE_COLORS[choice]
    if choice in {'na', 'no_current_method'}:
        return STATE_COLORS['not_applicable']
    if choice in {'price_0', 'price_1', 'price_2', 'price_3'}:
        return PRICE_COLORS[int(choice[-1])]
    if choice == 'do_nothing':
        return PRICE_COLORS[0]
    if choice in POSITIVE_CHOICES:
        return '#2F6E63'
    if choice in HOLD_CHOICES:
        return '#AC792A'
    return '#647487'


def stat(response, product, domain):
    return next(item for item in response['statistics'] if item['product_id'] == product['id'] and item['domain'] == domain)


def distribution(response, product, domain):
    data = stat(response, product, domain)
    counts, n = data['counts'], data['denominator']
    offset, pieces, legend = 0, [], []
    for choice, count in counts.items():
        if not count:
            continue
        width = 640 * count / n if n else 0
        shade = color(choice)
        pieces.append(f'<rect x="{offset:.3f}" y="0" width="{width:.3f}" height="18" fill="{shade}"/>')
        offset += width
        text = f'{label(response, product, domain, choice)} {pct(count, n)} · {count}명'
        legend.append(f'<span><i class="swatch" style="background:{shade}"></i>{escape(text)}</span>')
    title = next(question['title'] for question in response['questions'] if question['domain'] == domain)
    aria = '; '.join(f'{label(response, product, domain, choice)} {count}명' for choice, count in counts.items() if count)
    return f'<div class="distribution"><h3>{escape(title)} <small>n={n}</small></h3><svg class="chart" viewBox="0 0 640 18" role="img" aria-label="{escape(aria, quote=True)}">{"".join(pieces)}</svg><div class="legend">{"".join(legend)}</div></div>'


def price_bars(response, product):
    data = stat(response, product, 'fair_price')
    bands = product.get('valuation_bands', [])
    if not bands:
        return distribution(response, product, 'fair_price')
    height, parts = 54 * len(bands) + 20, []
    for index, band in enumerate(bands):
        count = data['counts'].get(band['id'], 0)
        width = 270 * count / data['denominator'] if data['denominator'] else 0
        y = 18 + index * 54
        parts += [f'<text x="0" y="{y}">{escape(label(response, product, "fair_price", band["id"]))}</text>',
                  f'<rect x="0" y="{y + 8}" width="{width:.2f}" height="14" fill="{color(band["id"])}"/>',
                  f'<text x="{width + 7:.2f}" y="{y + 20}">{pct(count, data["denominator"])} · {count}명</text>']
    states = ' · '.join(f'{STATE_LABELS[key]} {data["counts"].get(key, 0)}명' for key in STATE_LABELS if data['counts'].get(key))
    return f'<svg class="chart" viewBox="0 0 420 {height}" role="img" aria-label="적정가격 분포, n={data["denominator"]}">{"".join(parts)}</svg>' + (f'<p class="note">{escape(states)}</p>' if states else '')


def joint_table(response, product):
    joint = next((item for item in response['usage_purchase'] if item['product_id'] == product['id']), None)
    if joint is None:
        return ''
    usages = next(question['choices'] for question in response['questions'] if question['domain'] == 'usage')
    purchases = [choice for choice in next(question['choices'] for question in response['questions'] if question['domain'] == 'purchase') if choice != 'not_run']
    counts = {(cell['usage'], cell['purchase']): cell['count'] for cell in joint['cells']}
    head = '<tr><th>사용 의향 / 최종 선택</th>' + ''.join(f'<th class="numeric">{escape(label(response, product, "purchase", choice))}</th>' for choice in purchases) + '</tr>'
    rows = ''.join('<tr><th>' + escape(label(response, product, 'usage', usage)) + '</th>' + ''.join(f'<td class="numeric">{counts.get((usage, choice), 0)}</td>' for choice in purchases) + '</tr>' for usage in usages)
    return f'<table class="joint"><thead>{head}</thead><tbody>{rows}</tbody></table><p class="note">인원 · 두 응답이 있는 {joint["paired_count"]}명 / 전체 {joint["denominator"]}명 · 제외 {joint["excluded_count"]}명</p>'


def summary_facts(response):
    n, product = response['count'], response['products'][0]
    facts = [f'{n}명의 같은 인물을 상품 {len(response["products"])}개에 적용했습니다. 회차 {response["repeat"] + 1}/{response["repeats"]}.']
    for domain, choice in (('usage', 'use'), ('purchase', 'buy')):
        data = stat(response, product, domain)
        known = sum(value for key, value in data['counts'].items() if key not in STATE_LABELS)
        if known:
            facts.append(f'{display_name(response, product)}: {label(response, product, domain, choice)} {data["counts"].get(choice, 0)}명 / {n}명 ({pct(data["counts"].get(choice, 0), n)}).')
        else:
            text = ', '.join(f'{STATE_LABELS[key]} {value}명' for key, value in data['excluded'].items() if value)
            facts.append(f'{display_name(response, product)}: {next(q["title"] for q in response["questions"] if q["domain"] == domain)} — {text or "응답 없음"}.')
    return facts[:3]


def comparison_table(response):
    products = response['products']
    header = '<tr><th>평가 항목</th>' + ''.join(f'<th>{escape(display_name(response, product))}<br><small>{escape(offer_label(product))}</small></th>' for product in products) + '</tr>'
    rows = ''
    for question in response['questions']:
        cells = []
        for product in products:
            data = stat(response, product, question['domain'])
            text = '<br>'.join(escape(label(response, product, question['domain'], choice)) + f' <strong>{pct(count, data["denominator"])}</strong> · {count}명' for choice, count in data['counts'].items() if count)
            cells.append('<td>' + (text or '응답 없음') + '</td>')
        rows += '<tr><th>' + escape(question['title']) + '</th>' + ''.join(cells) + '</tr>'
    return f'<table><thead>{header}</thead><tbody>{rows}</tbody></table>'


def price_points(response):
    chunks = []
    for group in response['price_points']:
        parts = ['<line x1="45" x2="600" y1="200" y2="200" stroke="#CAD3D7"/>']
        for percent, y in ((0, 200), (50, 120), (100, 40)):
            parts += [f'<line x1="45" x2="600" y1="{y}" y2="{y}" stroke="#DFE8ED"/>', f'<text x="35" y="{y + 4}" text-anchor="end">{percent}%</text>']
        minimum, maximum = min(p['amount_minor'] for p in group['points']), max(p['amount_minor'] for p in group['points'])
        for point in group['points']:
            x = 70 + 490 * (point['amount_minor'] - minimum) / (maximum - minimum)
            y = 200 - 160 * point['share']
            parts += [f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="#2F6E63"/>',
                      f'<text x="{x:.2f}" y="{y - 14:.2f}" text-anchor="middle">{pct(point["count"], point["denominator"])} · {point["count"]}/{point["denominator"]}명</text>',
                      f'<text x="{x:.2f}" y="224" text-anchor="middle">{escape(amount(point["amount_minor"], group["currency"]))}</text>']
        chunks.append(f'<h3>{escape(group["name"])} · 가격별 선택</h3><p class="note">{escape(group["currency"])} · {escape(BILLING[group["billing"]])}</p><svg class="chart" viewBox="0 0 640 240" role="img" aria-label="제시 가격별 가상 선택 비율">{"".join(parts)}</svg>')
    return ''.join(chunks)


def heatmap(response, product, key, title):
    people = response['people']
    choices = list(stat(response, product, 'fair_price')['counts'])
    choices = [choice for choice in choices if choice.startswith('price_') and product.get('valuation_bands') or any(next(item for item in person['items'] if item['product_id'] == product['id'])['fair_price']['choice'] == choice for person in people)]
    if not choices:
        return ''
    groups = list(dict.fromkeys(person[key] for person in people))
    header = '<tr><th>' + escape(title) + '</th>' + ''.join('<th>' + escape(label(response, product, 'fair_price', choice)) + '</th>' for choice in choices) + '</tr>'
    rows = []
    for group in sorted(groups):
        selected = [person for person in people if person[key] == group]
        counts = Counter(next(item for item in person['items'] if item['product_id'] == product['id'])['fair_price']['choice'] for person in selected)
        cells = []
        for choice in choices:
            share = counts[choice] / len(selected)
            shade = color(choice)
            rgb = ','.join(str(int(shade[index:index + 2], 16)) for index in (1, 3, 5))
            background = f'rgba({rgb},{share * .25:.3f})'
            cells.append(f'<td style="background:{background}">{pct(counts[choice], len(selected))}<br><small>{counts[choice]}명</small></td>')
        rows.append(f'<tr><th>{escape(str(group))}<br><small>n={len(selected)}</small></th>{"".join(cells)}</tr>')
    return f'<h3>{escape(title)} 적정가격</h3><table class="heat"><thead>{header}</thead><tbody>{"".join(rows)}</tbody></table>'


def selected_cases(response):
    # A deterministic audit sample, not a representative consumer testimonial.
    ranked = []
    for index, person in enumerate(response['people']):
        cells = [item[question['domain']] for item in person['items'] for question in response['questions']]
        priority = 0 if any(cell['choice'] == 'error' for cell in cells) else 1 if any(cell['choice'] == 'unknown' for cell in cells) else 2
        ranked.append((priority, index, person))
    return [person for _, _, person in sorted(ranked, key=lambda value: value[:2])[:3]]


def _html(report):
    response, context = report['responses'], report['report_context']
    first = response['products'][0]
    fragments = [f'<section class="page first"><h1>{escape(context["title"])}</h1>',
                 f'<p class="meta">{escape(datetime_label(context["created_at"]))} · {response["count"]}명 · 회차 {response["repeat"] + 1}/{response["repeats"]} · {escape(status_label(response["status"]))}</p>',
                 '<ul class="facts">' + ''.join('<li>' + escape(fact) + '</li>' for fact in summary_facts(response)) + '</ul>',
                 f'<h2>{escape(display_name(response, first))}</h2><p>{escape(offer_label(first))}</p><p class="product-summary">{escape(first.get("summary", ""))}</p>',
                 '<div class="columns"><div><h3>사용 의향 × 최종 선택</h3>' + joint_table(response, first) + '</div><div><h3>적정가격 분포</h3>' + price_bars(response, first) + '</div></div>',
                 '<p class="note">비율의 분모는 선택한 회차의 전체 대상입니다. 합성 인물의 가상 응답이며 실제 구매 확률을 뜻하지 않습니다.</p></section>']
    if len(response['products']) > 1:
        fragments.append('<section class="page"><h2>상품 비교</h2><p class="note">같은 인물 · 같은 회차 · n=' + str(response['count']) + '</p>' + comparison_table(response))
        paired = [pair for pair in response['paired_comparisons'] if pair['domain'] == 'purchase']
        fragments.append('<h2>같은 인물의 선택 비교</h2>')
        for pair in paired:
            a, b = (next(product for product in response['products'] if product['id'] == pair[key]) for key in ('from_product', 'to_product'))
            fragments.append(f'<h3>{escape(display_name(response, a))} ({escape(offer_label(a))}) → {escape(display_name(response, b))} ({escape(offer_label(b))})</h3><p class="note">비교 {pair["paired_count"]}명 · 제외 {pair["excluded_count"]}명</p><table><thead><tr><th>첫 상품</th><th>다음 상품</th><th class="numeric">인원</th></tr></thead><tbody>' + ''.join(f'<tr><td>{escape(label(response, a, "purchase", change["from"]))}</td><td>{escape(label(response, b, "purchase", change["to"]))}</td><td class="numeric">{change["count"]}</td></tr>' for change in pair['transitions']) + '</tbody></table>')
        fragments.append('</section>')
    for product in response['products']:
        fragments += [f'<section class="page"><h2>{escape(display_name(response, product))}</h2><p>{escape(offer_label(product))} · n={response["count"]}</p>',
                      f'<p class="product-summary">{escape(product.get("summary", ""))}</p>',
                      ''.join(distribution(response, product, question['domain']) for question in response['questions'] if question['domain'] != 'fair_price'), '</section>',
                      f'<section class="page"><h2>{escape(display_name(response, product))} · 가격·집단</h2><h3>적정가격 분포</h3>' + price_bars(response, product),
                      heatmap(response, product, 'age_group', '연령대'), heatmap(response, product, 'sex', '성별'), '</section>']
    points = price_points(response)
    if points:
        fragments.append('<section class="page"><h2>제시가격별 선택</h2>' + points + '<p class="note">상품 정보와 조건이 같고 가격만 다른 항목입니다. 측정한 점만 표시합니다.</p></section>')
    source, model = context['source'], context['model']
    conditions = panel_conditions(context['panel'])
    tags = tag_condition(context['panel'], context.get('tag_labels'), context.get('tag_locale', 'ko'))
    fragments += ['<section class="page"><h2>실행 조건</h2><table class="methods"><tbody>',
                  f'<tr><th>실험</th><td>{escape(context["experiment_id"])}</td></tr><tr><th>실행일·상태</th><td>{escape(context["created_at"])} · {escape(response["status"])}</td></tr><tr><th>질문 버전</th><td>{escape(str(context["scenario_id"]))}</td></tr>',
                  f'<tr><th>대상</th><td>{response["count"]}명 · 회차 {response["repeat"] + 1}/{response["repeats"]}</td></tr><tr><th>모델</th><td>{escape(model["backend_id"])}</td></tr>',
                  f'<tr><th>원천</th><td>{escape(source["source_id"])} · {escape(source["version"])}<br>{escape(source.get("url", ""))}</td></tr>',
                  f'<tr><th>라이선스</th><td>{escape(source.get("license_id", ""))}<br>{escape(source.get("license_url", ""))}</td></tr>',
                  f'<tr><th>원천 인원·귀속</th><td>{escape(str(source.get("record_count", "미기록")))}명<br>{escape(source.get("attribution", ""))}</td></tr>',
                  f'<tr><th>원천 SHA256</th><td>{escape(source.get("local_sha256", "미기록"))}</td></tr>',
                  f'<tr><th>추출 조건</th><td>{escape(json.dumps(conditions, ensure_ascii=False, sort_keys=True))}</td></tr>',
                  f'<tr><th>대상 태그</th><td>{escape(tags)}</td></tr>' if tags else '',
                  ''.join(f'<tr><th>적정가격</th><td>{escape(display_name(response, product))} · {escape(valuation_condition(response, product))}</td></tr>' for product in response['products']),
                  '</tbody></table>',
                  '<p class="note">질문별 분모는 전체 대상 인원입니다. 판단 불가·해당 없음·미실시·오류·대기를 각각 보존합니다. 반복 회차는 합산하지 않습니다. 교차표는 응답의 조합이며 인과 설명이 아닙니다.</p>',
                  '<p class="note">합성 인물 자료와 모델 선택은 실제 소비자 조사나 시장 예측으로 검증되지 않았습니다. 선택 점수는 소비자 확률이 아닙니다.</p></section>',
                  '<section class="page"><h2>질문과 선택지</h2>']
    for question in response['questions']:
        fragments.append(f'<div class="question"><strong>{escape(question["title"])} · {escape(question["id"])}</strong><p>{escape(question["prompt"])}</p><p class="note">' + ' / '.join(escape(question['labels'].get(choice, STATE_LABELS.get(choice, choice))) for choice in question['choices']) + '</p></div>')
    fragments += ['</section>', '<section class="page"><h2>확인할 사례</h2><p class="note">오류 → 판단 불가 → 저장된 인물 순서로 최대 3명을 선택했습니다. 대표 표본이나 인터뷰 인용문이 아닙니다.</p>']
    for person in selected_cases(response):
        fragments.append(f'<div class="case"><h3>{escape(person["name"])} · {escape(person["age_group"])} · {escape(person["sex"])}</h3><p class="note">{escape(person["uuid"])}</p><p>{escape(" · ".join(person.get("profile", {}).values()))}</p><table><thead><tr><th>상품</th><th>항목</th><th>선택</th><th>사유·부족 정보</th></tr></thead><tbody>')
        for item in person['items']:
            product = next(product for product in response['products'] if product['id'] == item['product_id'])
            for question in response['questions']:
                cell = item[question['domain']]
                detail = '; '.join(cell.get('missing_information') or [])
                if cell['choice'] in {'error', 'not_run'}:
                    detail = cell.get('reason') or STATE_LABELS[cell['choice']]
                fragments.append(f'<tr><td>{escape(display_name(response, product))}</td><td>{escape(question["title"])}</td><td>{escape(label(response, product, question["domain"], cell["choice"]))}</td><td>{escape(detail)}</td></tr>')
        fragments.append('</tbody></table></div>')
    fragments += ['</section>', '<section class="page"><h2>상품 원문</h2>']
    for document, products in document_groups(context['products']):
        covered = ''.join(f'<p>{escape(display_name(response, product))} · {escape(offer_label(product))}</p>' for product in products)
        fragments.append(f'<div class="document">{covered}<pre>{escape(document)}</pre></div>')
    fragments.append('</section><footer>' + BRAND_MARK + '<span><span class="wordmark">Paneloom</span> · 저장된 실행 결과 · 실험 ' + escape(context['experiment_id']) + '</span></footer>')
    return '<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src &apos;none&apos;; style-src &apos;unsafe-inline&apos;; img-src data:"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + escape(context['title']) + ' · Paneloom</title><style>' + CSS + '</style></head><body><main>' + ''.join(fragments) + '</main></body></html>'


def _csv(report):
    response = report['responses']
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['experiment_id', 'scenario_id', 'repeat', 'product_id', 'product_name', 'domain', 'question_id', 'choice', 'label', 'count', 'selected_people_denominator', 'share', 'price_amount_minor', 'price_currency', 'price_billing', 'backend_id', 'source_id', 'source_version', 'valuation_mode', 'valuation_status', 'valuation_reason', 'valuation_currency', 'valuation_billing', 'band_low_minor', 'band_high_minor'])
    products = {product['id']: product for product in response['products']}
    questions = {question['domain']: question for question in response['questions']}
    for data in response['statistics']:
        product = products[data['product_id']]
        price = product.get('price') or {}
        calibration, unit = product.get('valuation_calibration', {}), product.get('valuation_unit', {})
        question = questions[data['domain']]
        for choice, count in data['counts'].items():
            band = next((band for band in product.get('valuation_bands', []) if data['domain'] == 'fair_price' and band['id'] == choice), {})
            values = [report['experiment_id'], response['workflow'], response['repeat'], product['id'], product['name'], data['domain'], question['id'], choice, label(response, product, data['domain'], choice), count, data['denominator'], data['shares'][choice], price.get('amount_minor', ''), price.get('currency', ''), price.get('billing', ''), report['backend_id'], report['source']['source_id'], report['source']['version']]
            values += [calibration.get('mode', 'manual'), calibration.get('status', 'ready' if product.get('valuation_bands') else 'unavailable'), calibration.get('reason', ''), unit.get('currency', ''), unit.get('billing', ''), band.get('low_minor', ''), band.get('high_minor', '')]
            writer.writerow(["'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r')) else value for value in values])
    return output.getvalue()


def _markdown(report):
    response, context = report['responses'], report['report_context']
    esc = lambda value: escape(str(value), quote=False).replace('|', '\\|').replace('\n', ' ').replace('\r', '')
    lines = ['# ' + esc(context['title']), '', f'{esc(datetime_label(context["created_at"]))} · {response["count"]}명 · 회차 {response["repeat"] + 1}/{response["repeats"]} · {esc(status_label(response["status"]))}', '', '## 관찰', '']
    lines += ['- ' + esc(fact) for fact in summary_facts(response)]
    lines += ['', '## 상품·판매조건', '', '| 상품 | 판매조건 | 내용 |', '| --- | --- | --- |']
    lines += [f'| {esc(display_name(response, product))} | {esc(offer_label(product))} | {esc(product.get("summary", ""))} |' for product in response['products']]
    lines += ['', '## 질문별 응답', '', '| 상품 | 항목 | 선택 | 인원 | 전체 대상 | 비율 |', '| --- | --- | --- | ---: | ---: | ---: |']
    for data in response['statistics']:
        product = next(product for product in response['products'] if product['id'] == data['product_id'])
        question = next(question for question in response['questions'] if question['domain'] == data['domain'])
        lines += [f'| {esc(display_name(response, product))} | {esc(question["title"])} | {esc(label(response, product, data["domain"], choice))} | {count} | {data["denominator"]} | {pct(count, data["denominator"])} |' for choice, count in data['counts'].items() if count]
    lines += ['', '## 사용 의향 × 최종 선택', '', '| 상품 | 사용 의향 | 최종 선택 | 인원 |', '| --- | --- | --- | ---: |']
    for joint in response['usage_purchase']:
        product = next(product for product in response['products'] if product['id'] == joint['product_id'])
        lines += [f'| {esc(display_name(response, product))} | {esc(label(response, product, "usage", cell["usage"]))} | {esc(label(response, product, "purchase", cell["purchase"]))} | {cell["count"]} |' for cell in joint['cells']]
        lines.append(f'\n{esc(display_name(response, product))}: 비교 {joint["paired_count"]}명 · 제외 {joint["excluded_count"]}명 / 전체 {joint["denominator"]}명\n')
    if response['paired_comparisons']:
        lines += ['', '## 같은 인물의 상품 선택 비교', '', '| 첫 상품 | 다음 상품 | 첫 선택 | 다음 선택 | 인원 |', '| --- | --- | --- | --- | ---: |']
        for pair in response['paired_comparisons']:
            if pair['domain'] != 'purchase':
                continue
            first, second = (next(product for product in response['products'] if product['id'] == pair[key]) for key in ('from_product', 'to_product'))
            lines += [f'| {esc(display_name(response, first))} | {esc(display_name(response, second))} | {esc(label(response, first, "purchase", change["from"]))} | {esc(label(response, second, "purchase", change["to"]))} | {change["count"]} |' for change in pair['transitions']]
            lines.append(f'\n비교 {pair["paired_count"]}명 · 제외 {pair["excluded_count"]}명 / 전체 {pair["denominator"]}명\n')
    for group in response['price_points']:
        lines += ['', '## ' + esc(group['name']) + ' · 제시가격별 선택', '', '| 가격 | 선택 | 전체 대상 | 비율 |', '| --- | ---: | ---: | ---: |']
        lines += [f'| {esc(amount(point["amount_minor"], group["currency"]) + " " + group["currency"] + " · " + BILLING[group["billing"]])} | {point["count"]} | {point["denominator"]} | {pct(point["count"], point["denominator"])} |' for point in group['points']]
    lines += ['', '## 연령·성별 적정가격', '', '| 상품 | 구분 | 집단 | 가격대·상태 | 인원 | 집단 인원 | 비율 |', '| --- | --- | --- | --- | ---: | ---: | ---: |']
    for product in response['products']:
        for key, title in (('age_group', '연령대'), ('sex', '성별')):
            for group in sorted({person[key] for person in response['people']}):
                selected = [person for person in response['people'] if person[key] == group]
                counts = Counter(next(item for item in person['items'] if item['product_id'] == product['id'])['fair_price']['choice'] for person in selected)
                lines += [f'| {esc(display_name(response, product))} | {title} | {esc(group)} | {esc(label(response, product, "fair_price", choice))} | {count} | {len(selected)} | {pct(count, len(selected))} |' for choice, count in counts.items()]
    lines += ['', '## 확인할 사례', '', '오류 → 판단 불가 → 저장된 인물 순서로 최대 3명을 선택했습니다.', '', '| 인물 | 상품 | 항목 | 선택 | 사유·부족 정보 |', '| --- | --- | --- | --- | --- |']
    for person in selected_cases(response):
        for item in person['items']:
            product = next(product for product in response['products'] if product['id'] == item['product_id'])
            for question in response['questions']:
                cell = item[question['domain']]
                detail = cell.get('reason', '') if cell['choice'] in {'error', 'not_run'} else '; '.join(cell.get('missing_information') or [])
                lines.append(f'| {esc(person["name"])} | {esc(display_name(response, product))} | {esc(question["title"])} | {esc(label(response, product, question["domain"], cell["choice"]))} | {esc(detail)} |')
    lines += ['', '## 실행 조건', '', f'- 실험: {esc(context["experiment_id"])}', f'- 실행일·상태 원문: {esc(context["created_at"])} · {esc(response["status"])}', f'- 질문 버전: {esc(context["scenario_id"])}', f'- 모델: {esc(context["model"]["backend_id"])}', f'- 원천: {esc(context["source"]["source_id"])} @ {esc(context["source"]["version"])}', f'- 원천 URL: {esc(context["source"].get("url", ""))}', f'- 라이선스: {esc(context["source"].get("license_id", ""))}', f'- 추출 조건: {esc(json.dumps(panel_conditions(context["panel"]), ensure_ascii=False, sort_keys=True))}']
    tags = tag_condition(context['panel'], context.get('tag_labels'), context.get('tag_locale', 'ko'))
    if tags:
        lines.append('- 대상 태그: ' + esc(tags))
    lines += ['- 적정가격: ' + esc(display_name(response, product)) + ' · ' + esc(valuation_condition(response, product)) for product in response['products']]
    lines += ['', '비율의 분모는 선택한 회차의 전체 대상입니다. 판단 불가·해당 없음·미실시·오류·대기를 구분합니다. 반복 회차를 합산하지 않습니다. 합성 인물의 응답은 실제 구매 확률로 검증되지 않았습니다.', '', '## 질문', '']
    for question in response['questions']:
        lines += [f'### {esc(question["title"])} · {esc(question["id"])}', '', esc(question['prompt']), '', ' / '.join(esc(question['labels'].get(choice, STATE_LABELS.get(choice, choice))) for choice in question['choices']), '']
    lines += ['## 상품 원문', '']
    for document, products in document_groups(context['products']):
        lines += ['### ' + ' / '.join(esc(display_name(response, product)) for product in products), '']
        lines += ['- ' + esc(display_name(response, product)) + ' · ' + esc(offer_label(product)) for product in products]
        lines += ['', '<pre>' + escape(document) + '</pre>', '']
    return '\n'.join(lines) + '\n'


def render_report(report, format):
    require('responses' in report, '설문 보고서가 없습니다.')
    if format == 'html':
        return _html(report), 'text/html; charset=utf-8'
    if format == 'md':
        return _markdown(report), 'text/markdown; charset=utf-8'
    if format == 'csv':
        return _csv(report), 'text/csv; charset=utf-8'
    require(format == 'json', '보고서 형식을 확인하세요.')
    return json.dumps(report, ensure_ascii=False, indent=2), 'application/json'
