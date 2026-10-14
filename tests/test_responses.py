import copy
import io
import json
import sqlite3
import threading
import unittest
from unittest.mock import patch

import test_product as fixtures
from persona_lab.backends import FixtureBackend, LocalLLMBackend
from persona_lab.contracts import ContractError, Decision, validate_decision
from persona_lab.finite_decision import ClefBackend
from persona_lab.responses import SURVEY_V2_SCENARIO_ID as SCENARIO_ID, QUESTIONS
from persona_lab.runner import jobs, run


class ResponseTests(unittest.TestCase):
    setUp=fixtures.ProductTests.setUp
    finish=fixtures.ProductTests.finish

    def configure(self, pricing='free', repeats=1, items=1):
        self.draft=self.app.create()
        item=self.draft['items'][0]
        item.update(name='메모 도구',document='## 주요 기능\n\n검색과 태그로 메모를 정리합니다.\n\n가격: 900 JPY 일시불',pricing={'state':pricing,'amount':'2000' if pricing=='paid' else '', 'currency':'JPY','billing':'one_time'})
        item['valuation']={'currency':'JPY','billing':'one_time','boundaries':['1000','2000','3000']}
        self.draft['items']=[{**copy.deepcopy(item),'id':format(i+10,'032x')} for i in range(items)]
        self.draft['settings']['repeats']=repeats
        self.draft=self.app.save(self.draft['id'],self.draft)
        return self.app.make_spec(self.draft)

    def test_independent_inputs_free_refusal_and_missing_price(self):
        spec=self.configure()
        self.assertEqual(spec['scenario']['id'],SCENARIO_ID)
        self.assertEqual(spec['assumptions'],{})
        planned=list(jobs(self.app.data_path,self.source,spec))
        for job in planned:
            if job.question['domain']!='purchase':
                self.assertIsNone(job.product['price'])
                self.assertNotIn('900',job.product['document'])
                self.assertNotIn('price_state',job.product)
            else:self.assertEqual(job.product['price']['amount_minor'],0)
        class Decline(FixtureBackend):
            def decide(inner,job):
                if job.question['domain']=='usage':return Decision('use','ok',('profile_fit',),('product.document',),reason='검색 기능을 활용할 수 있습니다.',evidence_semantics='supplied_input_only',option_probabilities={key:float(key=='use') for key in job.question['choices']},probability_semantics='model_option_distribution')
                if job.question['domain']=='purchase':return Decision('decline','ok',('onboarding_friction',),('product.document',),reason='무료여도 기존 메모를 옮기는 데 드는 시간이 부담입니다.',evidence_semantics='supplied_input_only',option_probabilities={key:float(key=='decline') for key in job.question['choices'] if key!='not_run'},probability_semantics='model_option_distribution')
                return super().decide(job)
        self.app.test_backend=Decline();self.app.start(self.draft['id']);status=self.finish(self.draft['id'])
        self.assertEqual((status['cursor'],status['backend_errors']),(40,0))
        response=self.app.responses(self.draft['id'])
        self.assertEqual(response['count'],4)
        self.assertTrue(all(p['items'][0]['usage']['choice']=='use' and p['items'][0]['purchase']['choice']=='decline' for p in response['people']))
        detail=self.app.detail(self.draft['id'],response['people'][0]['items'][0]['usage']['job_id'])
        self.assertIsNone(detail['product']['price'])
        self.assertEqual(detail['offered_product']['price']['amount_minor'],0)
        self.assertIn('900',self.app.snapshot(self.draft['id'])['spec']['products'][0]['document'])
        self.configure('unset')
        self.app.start(self.draft['id']);self.finish(self.draft['id'])
        self.assertTrue(all(p['items'][0]['purchase']['choice']=='not_run' for p in self.app.responses(self.draft['id'])['people']))
        self.assertTrue(any(p['items'][0]['usage']['choice']=='use' for p in self.app.responses(self.draft['id'])['people']))

    def test_repeats_and_items_join_without_duplicate_people_or_hidden_pending(self):
        spec=self.configure('paid',repeats=2,items=5)
        store=self.app.directory(self.draft['id'])/'run.sqlite'
        run(self.app.data_path,self.source,spec,store,FixtureBackend(),max_batches=1)
        partial=self.app.responses(self.draft['id'])
        self.assertEqual((partial['count'],len(partial['products'])),(4,5))
        self.assertTrue(any(item['fair_price']['choice']=='pending' for p in partial['people'] for item in p['items']))
        self.assertEqual(run(self.app.data_path,self.source,spec,store,FixtureBackend())['cursor'],400)
        first=self.app.responses(self.draft['id'],0);second=self.app.responses(self.draft['id'],1)
        self.assertEqual(first['count'],second['count'])
        self.assertEqual({p['persona_id'] for p in first['people']},{p['persona_id'] for p in second['people']})
        self.assertEqual(len(first['people'][0]['items']),5)
        with self.assertRaises(ContractError):self.app.responses(self.draft['id'],2)

    def test_unknown_and_error_are_independent_and_retries_only_errors(self):
        spec=self.configure()
        class Fault(FixtureBackend):
            failed=True
            def decide(inner,job):
                if job.question['domain']=='fair_price' and inner.failed:raise ContractError('형식이 올바르지 않은 평가 응답')
                if job.question['domain']=='usage':return Decision('unknown','insufficient_information',('missing_context',),(),reason='현재 메모를 사용하는 목적이 없습니다.',missing_information=('메모 활용 목적과 사용 빈도',),evidence_semantics='supplied_input_only',option_probabilities={key:float(key=='unknown') for key in job.question['choices']},probability_semantics='model_option_distribution')
                return super().decide(job)
        backend=Fault();self.app.test_backend=backend;self.app.start(self.draft['id']);status=self.finish(self.draft['id'])
        self.assertEqual(status['backend_errors'],4)
        people=self.app.responses(self.draft['id'])['people']
        self.assertTrue(all(p['items'][0]['usage']['choice']=='unknown' and p['items'][0]['fair_price']['choice']=='error' for p in people))
        self.assertTrue(all(p['items'][0]['usage']['missing_information'] for p in people))
        backend.failed=False;self.app.start(self.draft['id'],retry=True);self.finish(self.draft['id'])
        self.assertEqual(self.app.status(self.draft['id'])['backend_errors'],0)
        self.assertTrue(all(p['items'][0]['usage']['choice']=='unknown' for p in self.app.responses(self.draft['id'])['people']))
        job=next(j for j in jobs(self.app.data_path,self.source,spec) if j.question['domain']=='usage')
        with self.assertRaisesRegex(ContractError,'확인 항목'):validate_decision(Decision('unknown','insufficient_information',('missing_context',),(),reason='정보 부족',evidence_semantics='supplied_input_only',option_probabilities={key:float(key=='unknown') for key in job.question['choices']},probability_semantics='model_option_distribution'),job)

    def test_new_model_request_contains_only_supplied_price_context(self):
        spec=self.configure('paid');spec.pop('inference_protocol',None);spec['scenario']['id']='product-response-v1';spec['questions']=QUESTIONS
        planned=list(jobs(self.app.data_path,self.source,spec));requests=[]
        def reply(request,**kwargs):
            body=json.loads(request.data);requests.append(body)
            properties=body['response_format']['json_schema']['schema']['oneOf'][0]['properties']
            answer={'choice':properties['choice']['enum'][0],'reason_code':properties['reason_code']['enum'][0],'evidence_refs':['product.document'],'missing_information':[]}
            return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer)}}]}).encode())
        with patch('urllib.request.urlopen',side_effect=reply):
            for job in planned[:3]:validate_decision(LocalLLMBackend(response=True).decide(job),job)
        inputs=[json.loads(r['messages'][1]['content']) for r in requests]
        self.assertNotIn('price',inputs[0]['product']);self.assertNotIn('price',inputs[1]['product'])
        self.assertEqual(inputs[2]['product']['price']['amount_minor'],2000)
        self.assertEqual(inputs[1]['product']['valuation_unit']['currency'],'JPY')
        self.assertEqual(len(inputs[1]['product']['valuation_bands']),4)
        self.assertNotIn('not_run',inputs[2]['question']['choices'])
        self.assertEqual(inputs[2]['choice_meanings']['decline'],'제시 조건으로 구매하지 않겠음')
        self.assertNotIn('missing_context',requests[2]['response_format']['json_schema']['schema']['oneOf'][0]['properties']['reason_code']['enum'])

    def test_delete_restore_and_fixed_snapshot_metadata(self):
        self.configure('paid');self.app.start(self.draft['id']);self.finish(self.draft['id'])
        identifier=self.draft['id'];directory=self.app.directory(identifier)
        original=(directory/'run.json').read_bytes()
        changed=json.loads((directory/'draft.json').read_text());changed['items'][0]['pricing']['amount']='99'
        (directory/'draft.json').write_text(json.dumps(changed))
        self.assertEqual(self.app.get(identifier)['items'][0]['pricing']['amount'],'2000')
        self.app.remove(identifier)
        self.assertIn(identifier,{item['id'] for item in self.app.state()['deleted']})
        with self.assertRaises(ContractError):self.app.get(identifier)
        self.app.restore(identifier)
        self.assertEqual((self.app.directory(identifier)/'run.json').read_bytes(),original)
        self.assertEqual(self.app.responses(identifier)['count'],4)

    def test_long_model_input_is_rejected_before_freezing_the_draft(self):
        self.configure('paid');self.draft['items'][0]['document']='가'*20000
        self.draft=self.app.save(self.draft['id'],self.draft)
        self.app.test_backend=ClefBackend(survey_version=SCENARIO_ID)
        def tokenize(request,**kwargs):
            self.assertTrue(request.full_url.endswith('/tokenize'))
            return io.BytesIO(json.dumps({'tokens':[1]*9000}).encode())
        with patch('urllib.request.urlopen',side_effect=tokenize):
            with self.assertRaisesRegex(ContractError,'입력 한도'):self.app.start(self.draft['id'])
        self.assertIsNone(self.app.status(self.draft['id']))
        self.assertFalse((self.app.directory(self.draft['id'])/'run.json').exists())

    def test_active_experiment_cannot_be_deleted(self):
        self.configure();entered=threading.Event();release=threading.Event()
        class Slow(FixtureBackend):
            def decide(inner,job):entered.set();release.wait(2);return super().decide(job)
        self.app.test_backend=Slow();self.app.start(self.draft['id'])
        self.assertTrue(entered.wait(1))
        try:
            with self.assertRaisesRegex(ContractError,'먼저 중단'):self.app.remove(self.draft['id'])
        finally:release.set()
        self.finish(self.draft['id'])

    def test_old_unrun_drafts_use_current_flow_without_rewriting_the_file(self):
        self.configure('paid');path=self.app.directory(self.draft['id'])/'draft.json'
        old=json.loads(path.read_text());old.pop('workflow');old['items']=[{'id':old['items'][0]['id'],'document':fixtures.DOCUMENT}];old['settings']['budget']=1500
        path.write_text(json.dumps(old));original=path.read_bytes()
        reopened=self.app.get(self.draft['id'])
        self.assertEqual(reopened['workflow'],SCENARIO_ID)
        self.assertEqual(reopened['items'][0]['pricing']['amount'],'2000')
        self.assertNotIn('budget',reopened['settings'])
        self.assertEqual(path.read_bytes(),original)
        reopened['items'][0]['document']=reopened['items'][0]['document'].replace('2000','900')
        self.app.save(reopened['id'],reopened);self.app.start(reopened['id']);self.finish(reopened['id'])
        self.assertEqual(self.app.snapshot(reopened['id'])['spec']['products'][0]['price']['amount_minor'],2000)

    def test_structured_unknown_names_gaps_and_invalid_reason_is_an_error(self):
        spec=self.configure('paid');spec.pop('inference_protocol',None);spec['scenario']['id']='product-response-v1';spec['questions']=QUESTIONS;job=next(j for j in jobs(self.app.data_path,self.source,spec) if j.question['domain']=='fair_price')
        answer={'choice':'unknown','reason_code':'missing_context','evidence_refs':[],'missing_information':['license_scope','current_method']}
        def reply(request,**kwargs):return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer)}}]}).encode())
        with patch('urllib.request.urlopen',side_effect=reply):
            decision=LocalLLMBackend(response=True).decide(job);validate_decision(decision,job)
            self.assertIn('라이선스',decision.reason);self.assertEqual(len(decision.missing_information),2)
            self.assertIn('missing.license_scope',decision.reason_codes)
            answer.update(choice='price_0',missing_information=[],evidence_refs=['product.document'])
            with self.assertRaisesRegex(ContractError,'맞지 않는 근거'):LocalLLMBackend(response=True).decide(job)

    def test_model_reads_major_currency_units_in_band_and_offer_labels(self):
        self.configure('paid');self.draft['items'][0]['pricing'].update(amount='9.99',currency='USD',billing='monthly')
        self.draft=self.app.save(self.draft['id'],self.draft);self.draft['workflow']='product-response-v1';spec=self.app.make_spec(self.draft)
        planned=list(jobs(self.app.data_path,self.source,spec));backend=LocalLLMBackend(response=True)
        price_job=next(j for j in planned if j.question['domain']=='fair_price');offer_job=next(j for j in planned if j.question['domain']=='purchase')
        price_payload=json.loads(backend.request_body(price_job)[0]['messages'][1]['content']);offer_payload=json.loads(backend.request_body(offer_job)[0]['messages'][1]['content'])
        self.assertEqual(price_payload['choice_meanings']['price_0'],'10 USD 미만 · 월간')
        self.assertEqual(offer_payload['offered_terms'],'9.99 USD · 월간')
        self.assertEqual(offer_payload['product']['price']['amount_minor'],999)


if __name__=='__main__':unittest.main()
