import copy,io,json,sqlite3,unittest
from dataclasses import asdict,replace
from unittest.mock import patch
import test_product as fixtures
from persona_lab.backends import FixtureBackend,LocalLLMBackend
from persona_lab.contracts import Decision,JudgmentQualityError,ContractError,validate_decision
from persona_lab.evaluation import evidence_items,request_body,parse_answer
from persona_lab.runner import jobs,run
from persona_lab.responses import LINKED_SCENARIO_ID,LINKED_QUESTIONS,QUESTIONS

class EvaluationTests(unittest.TestCase):
    setUp=fixtures.ProductTests.setUp
    finish=fixtures.ProductTests.finish

    def configure(self,items=1,repeats=1):
        draft=self.app.create();item=draft['items'][0]
        item.update(name='메모 도구',document='## 주요 기능\n\n검색과 태그로 메모를 정리합니다.\n\n가격: 900 JPY',pricing={'state':'paid','amount':'2000','currency':'JPY','billing':'one_time'})
        draft['items']=[{**copy.deepcopy(item),'id':format(i+10,'032x')} for i in range(items)]
        draft['settings']['repeats']=repeats;draft=self.app.save(draft['id'],draft)
        spec=self.app.make_spec(draft)
        spec['scenario']['id']=LINKED_SCENARIO_ID;spec['questions']=copy.deepcopy(LINKED_QUESTIONS)
        return draft,spec

    def answer(self,job,choice='unknown',amount=None):
        domain=job.question['domain'];body=request_body(job,'test');payload=json.loads(body['messages'][1]['content'])
        result={'assessment':{'choice':choice,'amount_minor':amount},'evidence_ids':{key:value[:2 if key=='assessments' else 1] for key,value in payload['evidence_groups'].items()},'missing_information':['value_basis' if domain=='fair_price' else 'usage_goal'] if choice=='unknown' else [],'reason':'사용 목적과 개인의 현재 도구 정보가 없어 판단하기 어렵습니다.' if choice=='unknown' else '검색과 태그 기능의 활용 가치를 고려한 조건부 추정 금액은 1,000 JPY입니다.'}
        if domain=='purchase':result['tradeoff']=''
        return result

    def test_price_blind_numeric_request_and_original_evidence(self):
        draft,spec=self.configure();planned=list(jobs(self.app.data_path,self.source,spec));job=planned[1]
        body=request_body(job,'test');payload=json.loads(body['messages'][1]['content'])
        self.assertNotIn('900',json.dumps(payload,ensure_ascii=False));self.assertNotIn('price_0',json.dumps(payload));self.assertNotIn('2,000',json.dumps(payload))
        self.assertEqual(body,request_body(replace(job,question={**job.question,'choices':list(reversed(job.question['choices']))}),'test'))
        answer=self.answer(job,'estimate',1000);decision=parse_answer(job,answer);validate_decision(decision,job)
        self.assertEqual(decision.choice,'price_1');self.assertEqual(decision.valuation['amount_minor'],1000)
        self.assertTrue(all(evidence in evidence_items(job).values() for evidence in decision.evidence))
        answer['evidence_ids']['product']=['not-supplied']
        with self.assertRaises(JudgmentQualityError):parse_answer(job,answer)

    def test_unknown_quality_error_and_invalid_money_are_distinct(self):
        _,spec=self.configure();job=list(jobs(self.app.data_path,self.source,spec))[1]
        self.assertEqual(parse_answer(job,self.answer(job)).status,'insufficient_information')
        answer=self.answer(job,'estimate',-1)
        with self.assertRaisesRegex(JudgmentQualityError,'가격'):parse_answer(job,answer)
        answer=self.answer(job);answer['reason']='The model must explain this choice.'
        with self.assertRaisesRegex(JudgmentQualityError,'한국어'):parse_answer(job,answer)
        answer=self.answer(job);answer['missing_information']=[]
        with self.assertRaises(JudgmentQualityError):parse_answer(job,answer)

    def test_long_document_is_not_silently_truncated(self):
        _,spec=self.configure();job=next(jobs(self.app.data_path,self.source,spec))
        document='가'*20000;job=replace(job,product={**job.product,'document':document,'intro':document})
        fragments=[item['quote'] for item in evidence_items(job).values() if item['ref']=='product.document']
        self.assertEqual(''.join(fragments),document)
        with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps({'tokens':[1]*9000}).encode())):
            with self.assertRaisesRegex(ContractError,'입력 한도'):LocalLLMBackend(linked=True).preflight(job)

    def test_decimal_prices_and_version_numbers_remain_in_one_evidence_fragment(self):
        _,spec=self.configure();job=next(jobs(self.app.data_path,self.source,spec))
        raw={'persona':'macOS 14.0을 사용한다. 적정가격은 9.99 USD라고 명시했다.'}
        job=replace(job,persona=replace(job.persona,raw=raw))
        snippets=[item['quote'] for item in evidence_items(job).values() if item['ref']=='persona.raw.persona']
        self.assertEqual(snippets,['macOS 14.0을 사용한다.','적정가격은 9.99 USD라고 명시했다.'])

    def test_linked_jobs_resume_and_match_person_item_repeat(self):
        draft,spec=self.configure(items=2,repeats=2);store=self.app.directory(draft['id'])/'run.sqlite'
        class Observe(FixtureBackend):
            observed=[]
            def decide(inner,job):
                inner.observed.append(job)
                return super().decide(job)
        backend=Observe();self.assertEqual(run(self.app.data_path,self.source,spec,store,backend,max_batches=2)['cursor'],2)
        self.assertEqual(run(self.app.data_path,self.source,spec,store,backend)['cursor'],48)
        with sqlite3.connect(store) as db:records=[json.loads(row[0]) for row in db.execute('SELECT payload FROM results')]
        by_id={record['job_id']:record for record in records}
        for record in records:
            if record['domain']!='purchase':self.assertIsNone(record['assessments']);continue
            self.assertEqual(set(record['assessments']),{'usage','fair_price'})
            for earlier in record['assessments'].values():
                linked=by_id[earlier['job_id']]
                for key in ('persona_id','product_id','repeat'):self.assertEqual(linked[key],record[key])

    def test_raw_attempts_survive_quality_failure_and_dependency_retry(self):
        draft,spec=self.configure();backend=LocalLLMBackend(linked=True);self.app.test_backend=backend;fail=True
        frozen={**draft,'workflow':LINKED_SCENARIO_ID};frozen.pop('run',None);frozen.pop('legacy_items',None)
        (self.app.directory(draft['id'])/'run.json').write_text(json.dumps({'draft':frozen,'source':self.source,'spec':spec}))
        def reply(request,**kwargs):
            payload=json.loads(json.loads(request.data)['messages'][1]['content']);task=payload['task']
            domain='fair_price' if '선택할 가격대 목록' in task else 'purchase' if '최종 선택' in task else 'usage'
            answer={'assessment':{'choice':'unknown','amount_minor':None},'evidence_ids':{kind:ids[:2 if kind=='assessments' else 1] for kind,ids in payload['evidence_groups'].items()},'missing_information':['value_basis' if domain=='fair_price' else 'usage_goal'],'reason':'현재 사용하는 도구와 구체적인 개인 활용 목적의 정보가 부족합니다.'}
            if domain=='purchase':answer['tradeoff']=''
            if domain=='fair_price' and fail:answer['evidence_ids']['product']=['fabricated']
            return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer,ensure_ascii=False)}}]}).encode())
        with patch('urllib.request.urlopen',side_effect=reply):
            self.app.start(draft['id']);self.finish(draft['id']);self.assertEqual(self.app.status(draft['id'])['backend_errors'],8)
            with sqlite3.connect(self.app.directory(draft['id'])/'run.sqlite') as db:
                normal=db.execute("SELECT job_id,payload FROM results WHERE status!='backend_error'").fetchall()
                self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls WHERE finished_at IS NOT NULL AND response IS NOT NULL').fetchone()[0],8)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM results WHERE json_extract(payload,'$.backend_error.type')='JudgmentQualityError'").fetchone()[0],4)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM results WHERE json_extract(payload,'$.backend_error.type')='DependencyError'").fetchone()[0],4)
            fail=False;self.app.start(draft['id'],retry=True);self.finish(draft['id']);self.assertEqual(self.app.status(draft['id'])['backend_errors'],0)
        with sqlite3.connect(self.app.directory(draft['id'])/'run.sqlite') as db:
            for job,payload in normal:self.assertEqual(db.execute('SELECT payload FROM results WHERE job_id=?',(job,)).fetchone()[0],payload)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0],16)
        detail=self.app.detail(draft['id'],normal[0][0]);self.assertEqual(len(detail['model_calls']),1)
        exported=json.loads(self.app.export(draft['id'],'json')[0]);self.assertEqual(len(exported['model_calls']),16)

    def test_frozen_v1_resumes_without_rewriting_existing_decisions(self):
        draft,spec=self.configure();spec['scenario']['id']='product-response-v1';spec['questions']=QUESTIONS
        directory=self.app.directory(draft['id']);store=directory/'run.sqlite'
        draft={**draft,'workflow':'product-response-v1'};draft.pop('run',None);draft.pop('legacy_items',None)
        (directory/'run.json').write_text(json.dumps({'draft':draft,'source':self.source,'spec':spec}))
        run(self.app.data_path,self.source,spec,store,FixtureBackend(),max_batches=1)
        with sqlite3.connect(store) as db:before=db.execute('SELECT job_id,payload FROM results').fetchall()
        run(self.app.data_path,self.source,spec,store,FixtureBackend())
        with sqlite3.connect(store) as db:
            for job,payload in before:self.assertEqual(db.execute('SELECT payload FROM results WHERE job_id=?',(job,)).fetchone()[0],payload)
        self.assertEqual(self.app.get(draft['id'])['workflow'],'product-response-v1');self.assertEqual(self.app.responses(draft['id'])['workflow'],'product-response-v1')
