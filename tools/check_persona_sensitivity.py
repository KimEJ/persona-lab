"""Small explicit synthetic contrasts, preserving every output and order change."""
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from persona_lab import __version__
from persona_lab.adapter import normalize
from persona_lab.backends import JuliaBackend, LocalLLMBackend, FixtureBackend
from persona_lab.contracts import Job, digest, validate_decision

root = Path(__file__).resolve().parents[1]
source = json.loads((root / 'data/packs/synthetic-fixture.json').read_text())
source.update(source_id='persona-lab/controlled-sensitivity-fixture', version='controlled-v1', name='Explicit project-authored Japanese contrasts')
spec = json.loads((root / 'examples/experiment.json').read_text())
profiles = {
    'needs_product': {'uuid': 'controlled-needs-product', 'age': 35, 'country': '日本', 'persona': '仕事で毎日PCを使い、数百のメモから必要な情報を探すのに毎日30分を失っている。検索とタグ整理の道具を今必要としている。ローカル保存を好み、新しいメモ整理ツールを導入したい。'},
    'no_product_need': {'uuid': 'controlled-no-product-need', 'age': 35, 'country': '日本', 'persona': 'PCを所有せず使う予定もない。メモを使う仕事や趣味はなく、紙の予定表だけで困っていない。PC用メモ整理ツールに用途がなく、新しいソフトを導入する必要を感じていない。'},
}
product = spec['products'][0]
questions = [question for question in spec['questions'] if question['domain'] in {'need', 'purchase'}]
records = []
for name, backend in [('mock', FixtureBackend()), ('qwen', LocalLLMBackend()), ('julia', JuliaBackend())]:
    for profile_id, raw in profiles.items():
        for question in questions:
            for order in ('original', 'reversed'):
                rendered = {**question, 'choices': question['choices'] if order == 'original' else list(reversed(question['choices']))}
                job = Job(len(records), digest([name, profile_id, question['id'], order]), normalize(raw, source), product, rendered, 0, 17, spec['scenario'], {'purchase_budget_jpy_minor': 3000})
                try:
                    decision = backend.decide(job); validate_decision(decision, job)
                    output = {'decision': asdict(decision), 'error': None}
                except (ValueError, OSError) as error:
                    output = {'decision': None, 'error': {'type': type(error).__name__, 'message': str(error)}}
                records.append({'backend': name, 'backend_id': backend.backend_id, 'profile': profile_id, 'question': question['id'], 'option_order': order, 'choices': rendered['choices'], **output})
comparisons = []
for name in ('mock', 'qwen', 'julia'):
    for question in questions:
        rows = [row for row in records if row['backend'] == name and row['question'] == question['id']]
        lookup = {(row['profile'], row['option_order']): row['decision']['choice'] if row['decision'] else None for row in rows}
        comparisons.append({'backend': name, 'question': question['id'], 'original_choices': {profile: lookup[profile, 'original'] for profile in profiles}, 'contrasting_profiles_changed_choice': lookup['needs_product', 'original'] != lookup['no_product_need', 'original'], 'option_order_changed_profiles': [profile for profile in profiles if lookup[profile, 'original'] != lookup[profile, 'reversed']]})
receipt = {'verified_at': datetime.now(timezone.utc).isoformat(), 'engine': __version__, 'source': source, 'inputs': profiles, 'product': product, 'assumptions': {'purchase_budget_jpy_minor': 3000}, 'scenario': spec['scenario'], 'records': records, 'comparisons': comparisons, 'valid_outputs': sum(row['decision'] is not None for row in records), 'errors': sum(row['decision'] is None for row in records), 'limitations': ['These are deliberately contrasting project-authored synthetic profiles, not modified NVIDIA records.', 'Two profiles and two questions do not establish causal attribution, Japanese robustness or consumer accuracy.', 'Every original/reversed output is retained; changed options are a sensitivity observation, not corrected away.', 'Mock ignores persona needs and only uses its explicit budget rule.']}
(root / 'verification/persona-sensitivity.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'valid_outputs': receipt['valid_outputs'], 'errors': receipt['errors'], 'comparisons': comparisons}, ensure_ascii=False))
