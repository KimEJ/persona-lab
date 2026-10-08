import copy
import hashlib
import json
import sqlite3
import unittest

import test_product as fixtures
from persona_lab.backends import FixtureBackend
from persona_lab.contracts import ContractError, Decision, validate_experiment
from persona_lab.runner import run


class WorkbenchTests(unittest.TestCase):
    setUp = fixtures.ProductTests.setUp
    save = fixtures.ProductTests.save
    finish = fixtures.ProductTests.finish

    def test_versioned_scenario_gates_before_backend_and_records_terminal_states(self):
        self.save([fixtures.DOCUMENT])
        class Count(FixtureBackend):
            def __init__(self): self.calls = []
            def decide(inner, job):
                inner.calls.append(job.question['domain'])
                return super().decide(job)
        backend = Count(); self.app.test_backend = backend
        self.app.start(self.draft['id']); self.finish(self.draft['id'])
        self.assertEqual(len(backend.calls),20)
        self.assertNotIn('purchase',backend.calls); self.assertNotIn('churn',backend.calls)
        records = self.app.report(self.draft['id'])['examples']
        gated = [r for r in records if r['domain'] in {'purchase','churn'}]
        self.assertEqual(len(gated),8)
        self.assertTrue(all(r['execution']['origin']=='context_rule' and r['execution']['transition']['to']=='undecidable' for r in gated))
        self.assertTrue(all(r['execution']['max_steps']==1 and 'cognitive_state' not in r for r in records))
        spec = self.app.make_spec(self.draft)
        for mutation in ('version','event','choice','cognition','new_domain'):
            bad = copy.deepcopy(spec)
            if mutation=='version':bad['scenario']['id']='unknown-version'
            if mutation=='event':bad['scenario']['events']=[{'code':'made-up','origin':'user_explicit_scenario'}]
            if mutation=='choice':bad['questions'][0]['choices'].append('invented')
            if mutation=='cognition':bad['scenario']['emotions']='happy'
            if mutation=='new_domain':bad['questions'][0].update(domain='usage',choices=['use','unknown'])
            with self.assertRaises(ContractError):validate_experiment(bad)

    def test_budget_conflict_is_not_a_hidden_rule_choice_and_legacy_resume_survives(self):
        self.save([fixtures.DOCUMENT],budget=1500)
        class Buy(FixtureBackend):
            backend_id='budget-conflict-probe'
            def decide(inner,job):
                return Decision('buy','ok',('test',),('product.price',)) if job.question['domain']=='purchase' else super().decide(job)
        self.app.test_backend=Buy();self.app.start(self.draft['id']);self.finish(self.draft['id'])
        report=self.app.report(self.draft['id'])
        self.assertEqual(report['consistency_warnings']['purchase_above_explicit_budget'],4)
        self.assertTrue(all(r['decision']['choice']=='buy' and r['execution']['origin']=='backend' for r in report['examples'] if r['domain']=='purchase'))
        spec=self.app.make_spec(self.draft);spec['scenario'].pop('id')
        store=self.app.home/'legacy.sqlite'
        run(self.app.data_path,self.source,spec,store,FixtureBackend(),max_batches=1)
        result=run(self.app.data_path,self.source,spec,store,FixtureBackend())
        self.assertEqual((result['cursor'],result['backend_errors']),(28,0))

    def test_case_filters_late_errors_reviews_and_original_decisions(self):
        self.save([fixtures.DOCUMENT.replace('2000',str(price)) for price in (2000,900,500,1500,3100)],budget=1500,repeats=2)
        last=self.app.people[-1].uuid
        class LateFault(FixtureBackend):
            def decide(inner,job):
                if job.persona.uuid==last and job.product['id']==format(5,'032x') and job.question['domain']=='trust':raise ContractError('late error')
                return super().decide(job)
        self.app.test_backend=LateFault();self.app.start(self.draft['id']);self.finish(self.draft['id'])
        identifier=self.draft['id'];store=self.app.directory(identifier)/'run.sqlite'
        db=sqlite3.connect(store)
        original=dict(db.execute('SELECT job_id,payload FROM results'))
        fingerprint=db.execute('SELECT fingerprint FROM run').fetchone()[0];db.close()
        snapshot_sha=hashlib.sha256((store.parent/'run.json').read_bytes()).hexdigest()
        all_rows=self.app.results(identifier,limit=100)
        self.assertEqual(all_rows['count'],56)
        changed=self.app.results(identifier,mode='changed',domain='purchase')
        self.assertEqual(changed['count'],8)
        self.assertTrue(all(len(row['cells'])==5 for row in changed['rows']))
        errors=self.app.results(identifier,mode='errors')
        self.assertEqual(errors['count'],2)
        self.assertTrue(all(row['ordinal']>28 for row in errors['rows']))
        self.assertEqual(self.app.results(identifier,mode='changed',domain='trust')['count'],0)
        self.assertEqual(self.app.results(identifier,mode='unknown')['count'],48)
        first=self.app.results(identifier,limit=7);second=self.app.results(identifier,offset=7,limit=7)
        self.assertFalse({r['ordinal'] for r in first['rows']}&{r['ordinal'] for r in second['rows']})
        cell=errors['rows'][0]['cells'][-1];job=cell['record']['job_id']
        saved=self.app.save_review(identifier,job,{'revision':0,'note':'원문은 보존 <script>','marked':True})
        self.assertEqual(saved['revision'],1)
        with self.assertRaises(ContractError):self.app.save_review(identifier,job,{'revision':0,'note':'stale','marked':False})
        self.assertEqual(self.app.results(identifier,mode='marked')['count'],1)
        self.assertEqual(self.app.detail(identifier,job)['review'],saved)
        db=sqlite3.connect(store)
        self.assertEqual(dict(db.execute('SELECT job_id,payload FROM results')),original)
        self.assertEqual(db.execute('SELECT fingerprint FROM run').fetchone()[0],fingerprint);db.close()
        self.assertEqual(hashlib.sha256((store.parent/'run.json').read_bytes()).hexdigest(),snapshot_sha)
        self.assertEqual(self.app.report(identifier)['completed_jobs'],280)
        self.assertIn(job,json.loads(self.app.export(identifier,'json')[0])['reviews'])
        self.assertIn('&lt;script&gt;',self.app.export(identifier,'md')[0])
        self.assertEqual(json.loads(self.app.export(identifier,'reviews')[0])['reviews'][job]['note'],saved['note'])
        for kwargs in ({'baseline':'missing'},{'mode':'invalid'},{'offset':-1},{'limit':101},{'query':'x'*121}):
            with self.assertRaises(ContractError):self.app.results(identifier,**kwargs)
        self.assertEqual(self.app.results(identifier,query="' OR 1=1 --")['count'],0)

    def test_document_comparison_uses_frozen_input(self):
        self.save([fixtures.DOCUMENT,fixtures.DOCUMENT.replace('2000','900')],budget=1500)
        identifier=self.draft['id'];a,b=[item['id'] for item in self.draft['items']]
        before=self.app.compare_documents(identifier,a,b)
        self.assertTrue(any(row['kind']=='remove' and '2000' in row['text'] for row in before['rows']))
        self.app.start(identifier);self.finish(identifier)
        directory=self.app.directory(identifier);draft=json.loads((directory/'draft.json').read_text());draft['items'][1]['document']='changed outside app';(directory/'draft.json').write_text(json.dumps(draft))
        after=self.app.compare_documents(identifier,a,b)
        self.assertEqual(after['rows'],before['rows']);self.assertTrue(after['frozen'])


if __name__=='__main__':unittest.main()
