import copy
import hashlib
import io
import json
import unittest
from unittest.mock import patch

import test_product as fixtures
from persona_desktop.documents import DOCUMENT_TEMPLATE, money_from_fields
from persona_lab.backends import FixtureBackend, LocalLLMBackend
from persona_lab.contracts import ContractError, Decision
from persona_lab.runner import jobs, run


class StructuredTests(unittest.TestCase):
    setUp=fixtures.ProductTests.setUp
    finish=fixtures.ProductTests.finish

    def configure(self, state='paid', amount='9.99', currency='USD', billing='monthly', budget='10.00'):
        fixtures.legacy_draft(self.app,self.draft)
        item=self.draft['items'][0]
        item.update(name='상품 이름',document='## 주요 기능\n\n메모를 검색합니다.',pricing={'state':state,'amount':amount,'currency':currency,'billing':billing})
        self.draft['settings']['budget']={'amount':budget,'currency':currency,'billing':billing}
        self.draft=self.app.save(self.draft['id'],self.draft)
        return item

    def test_reopen_empty_drafts_get_template_without_rewriting_saved_content(self):
        path=self.app.directory(self.draft['id'])/'draft.json'
        original=copy.deepcopy(self.draft);original.pop('run',None);original.pop('legacy_items',None)
        authored='\r\n# 작성한 문서\r\n\r\n본문 그대로 보존\r\n'
        pricing={'state':'paid','amount':'2000','currency':'JPY','billing':'one_time'}
        original['items']=[{'id':'a'*32,'document':''},{'id':'b'*32,'name':'기존 상품','document':' \n\t','pricing':pricing},{'id':'c'*32,'document':authored}]
        path.write_text(json.dumps(original,ensure_ascii=False));before=path.read_bytes()
        reopened=self.app.get(self.draft['id'])
        self.assertEqual([item['document'] for item in reopened['items']],[DOCUMENT_TEMPLATE,DOCUMENT_TEMPLATE,authored])
        self.assertEqual(reopened['items'][0]['pricing']['state'],'unset')
        self.assertEqual(reopened['items'][1]['name'],'기존 상품')
        self.assertEqual(reopened['items'][1]['pricing'],pricing)
        self.assertEqual(path.read_bytes(),before)
        with patch.object(self.app,'status',return_value={'status':'completed'}):
            self.assertEqual(self.app.get(self.draft['id'])['items'],original['items'])

    def test_template_validation_exact_money_and_authoritative_fields(self):
        self.assertEqual(self.draft['items'][0]['document'],DOCUMENT_TEMPLATE)
        self.draft['items'][0]['name']='작성 중'
        self.draft=self.app.save(self.draft['id'],self.draft)
        with self.assertRaises(ContractError):self.app.start(self.draft['id'])
        self.assertFalse((self.app.directory(self.draft['id'])/'run.json').exists())
        self.configure()
        self.draft['items'][0]['document']='# 본문에서 언급한 다른 이름\n\n다른 상품은 2000 JPY 일시불입니다.'
        spec=self.app.make_spec(self.draft)
        self.assertEqual(spec['products'][0]['name'],'상품 이름')
        self.assertEqual(spec['products'][0]['price'],{'amount_minor':999,'currency':'USD','billing':'monthly'})
        self.assertEqual(spec['assumptions']['purchase_budget']['amount_minor'],1000)
        self.assertEqual(spec['scenario']['id'],'independent-choice-v2')
        for amount,currency in [('0.01','JPY'),('9.999','USD'),('-1','KRW'),('1e3','USD'),('NaN','USD'),('9223372036854775808','JPY')]:
            with self.assertRaises(ContractError):money_from_fields({'amount':amount,'currency':currency,'billing':'monthly'})
        self.draft['items'][0]['pricing']['amount']=''
        self.draft=self.app.save(self.draft['id'],self.draft)
        with self.assertRaises(ContractError):self.app.start(self.draft['id'])
        self.assertFalse((self.app.directory(self.draft['id'])/'run.json').exists())

    def test_units_missing_free_frozen_metadata_and_exports(self):
        self.configure()
        for key,value in [('currency','KRW'),('billing','annual')]:
            candidate=copy.deepcopy(self.draft);candidate['settings']['budget'][key]=value
            if key=='currency':candidate['settings']['budget']['amount']='10'
            spec=self.app.make_spec(candidate);store=self.app.home/(key+'.sqlite')
            run(self.app.data_path,self.source,spec,store,FixtureBackend())
            import sqlite3
            with sqlite3.connect(store) as db:
                purchase=[json.loads(p) for (p,) in db.execute("SELECT payload FROM results WHERE domain='purchase'")]
            self.assertTrue(all(r['decision']['reason_codes']==['purchase_units_mismatch'] and r['execution']['origin']=='context_rule' for r in purchase))
        other=copy.deepcopy(self.draft['items'][0]);other['id']='f'*32;other['pricing']['amount']='12.50';self.draft['items'].append(other)
        self.draft=self.app.save(self.draft['id'],self.draft)
        self.app.start(self.draft['id']);self.finish(self.draft['id'])
        report=self.app.report(self.draft['id']);self.assertEqual(report['comparisons'][0]['paired_count'],4)
        self.assertEqual(report['comparisons'][0]['transitions'],[{'from':'buy','to':'decline','count':4}])
        snapshot=self.app.snapshot(self.draft['id']);before=hashlib.sha256((self.app.directory(self.draft['id'])/'run.json').read_bytes()).hexdigest()
        diff=self.app.compare_documents(self.draft['id'],self.draft['items'][0]['id'],other['id'])
        self.assertTrue(any(r['kind']=='add' and '12.50 USD' in r['text'] for r in diff['rows']))
        self.assertEqual(snapshot['spec']['products'][0]['price']['amount_minor'],999)
        for fmt in ('md','csv','json','spec'):
            exported=self.app.export(self.draft['id'],fmt)[0];self.assertIn('USD',exported);self.assertIn('monthly',exported)
        with self.assertRaises(ContractError):self.app.save(self.draft['id'],self.draft)
        self.assertEqual(hashlib.sha256((self.app.directory(self.draft['id'])/'run.json').read_bytes()).hexdigest(),before)
        self.draft=self.app.create();self.configure(state='unset',budget='10')
        self.assertIsNone(self.app.make_spec(self.draft)['products'][0]['price'])
        self.draft['items'][0]['pricing']['state']='free';self.draft['settings']['budget']['amount']=''
        self.draft=self.app.save(self.draft['id'],self.draft);self.app.start(self.draft['id']);self.finish(self.draft['id'])
        purchase=[r for r in self.app.report(self.draft['id'])['examples'] if r['domain']=='purchase']
        self.assertTrue(all(r['decision']['choice']=='buy' and r['execution']['origin']=='backend' for r in purchase))

    def test_budget_conflict_legacy_resume_and_versioned_model_prompt(self):
        self.configure(amount='12.50')
        class Buy(FixtureBackend):
            def decide(inner,job):
                return Decision('buy','ok',('test',),('product.price',)) if job.question['domain']=='purchase' else super().decide(job)
        self.app.test_backend=Buy();self.app.start(self.draft['id']);self.finish(self.draft['id'])
        self.assertEqual(self.app.report(self.draft['id'])['consistency_warnings']['purchase_above_explicit_budget'],4)
        self.draft=self.app.create();fixtures.legacy_draft(self.app,self.draft);self.draft['items']=[{'id':'a'*32,'document':fixtures.DOCUMENT}];self.draft['settings']['budget']=1500
        self.draft=self.app.save(self.draft['id'],self.draft);spec=self.app.make_spec(self.draft);self.assertEqual(spec['scenario']['id'],'independent-choice-v1')
        store=self.app.home/'legacy.sqlite';run(self.app.data_path,self.source,spec,store,FixtureBackend(),max_batches=1)
        self.assertEqual(run(self.app.data_path,self.source,spec,store,FixtureBackend())['cursor'],28)
        self.draft=self.app.create();self.configure();spec=self.app.make_spec(self.draft)
        job=next(j for j in jobs(self.app.data_path,self.source,spec) if j.question['domain']=='purchase')
        response={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'choice':'buy','reason_code':'price_constraint','evidence_refs':['product.price']})}}]}
        requests=[]
        def reply(request,**_):requests.append(json.loads(request.data));return io.BytesIO(json.dumps(response).encode())
        with patch('urllib.request.urlopen',side_effect=reply):LocalLLMBackend(structured=True).decide(job)
        self.assertIn('authoritative',requests[0]['messages'][0]['content'])
        self.assertEqual(json.loads(requests[0]['messages'][1]['content'])['product']['price']['amount_minor'],999)
        self.assertTrue(LocalLLMBackend().backend_id.endswith('v7-document'))
        self.assertTrue(LocalLLMBackend(structured=True).backend_id.endswith('v8-form'))

if __name__=='__main__':unittest.main()
