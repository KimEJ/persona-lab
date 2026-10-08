import copy
import io
import json
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from persona_desktop.application import Application
from persona_desktop.documents import price_from_document, product_from_item
from persona_desktop.server import make_server
from persona_lab.backends import FixtureBackend, LocalLLMBackend
from persona_lab.contracts import ContractError, validate_experiment
from persona_lab.runner import run, read_status
from persona_lab.reports import summarize

ROOT=Path(__file__).resolve().parents[1]
DOCUMENT='# 메모 도구\n\n## 구매 조건\n- 가격: 2000 JPY\n- 결제 방식: 일시불\n'

def legacy_draft(app, draft):
    """These tests preserve the already shipped seven-question contracts."""
    path=app.directory(draft['id'])/'draft.json'
    stored=json.loads(path.read_text());stored['workflow']='legacy'
    path.write_text(json.dumps(stored,ensure_ascii=False));draft['workflow']='legacy'

class ProductTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)/'resources';(root/'assets/data').mkdir(parents=True)
        self.source=json.loads((ROOT/'demo/data/packs/synthetic-fixture.json').read_text())
        (root/'assets/data/nemotron-japan-sample.json').write_text(json.dumps(self.source))
        data=(ROOT/'demo/data/packs/synthetic-fixture.jsonl').read_bytes()
        import hashlib
        self.source['local_sha256']=hashlib.sha256(data).hexdigest()
        (root/'assets/data/nemotron-japan-sample.json').write_text(json.dumps(self.source))
        (root/'assets/data'/self.source['data_file']).write_bytes(data)
        (root/'assets/questions.json').write_bytes((ROOT/'assets/questions.json').read_bytes())
        self.app=Application(root,Path(self.temp.name)/'home',FixtureBackend())
        self.addCleanup(self.app.close)
        self.draft=self.app.create()
        legacy_draft(self.app,self.draft)

    def save(self,documents,**settings):
        candidate=copy.deepcopy(self.draft)
        legacy_draft(self.app,candidate)
        candidate['items']=[{'id':format(i+1,'032x'),'document':doc} for i,doc in enumerate(documents)]
        candidate['settings'].update(settings)
        self.draft=self.app.save(candidate['id'],candidate)
        return self.draft

    def finish(self,identifier):
        for _ in range(100):
            status=self.app.status(identifier)
            if not status['active']:return status
            time.sleep(.01)
        self.fail('experiment did not finish')

    def test_markdown_price_units_and_ambiguity(self):
        self.assertEqual(price_from_document(DOCUMENT),{'amount_minor':2000,'currency':'JPY','billing':'one_time'})
        self.assertEqual(price_from_document('**가격**: USD 9.99\n결제 방식: one-time')['amount_minor'],999)
        self.assertIsNone(price_from_document('가격: 2000 JPY'))
        self.assertIsNone(price_from_document('가격: 2000 JPY / 900 JPY\n일시불'))
        self.assertIsNone(price_from_document('가격: 2,00 JPY\n일시불'))
        self.assertIsNone(price_from_document('가격: 1.2 JPY\n일시불'))
        self.assertIsNone(price_from_document('가격: -2000 JPY\n일시불'))
        self.assertIsNone(price_from_document('가격: 1e3 JPY\n일시불'))
        product=product_from_item({'id':'one','document':'# 제목\n가격 미제공'},1)
        self.assertIsNone(product['price'])
        self.assertEqual(product['document'],'# 제목\n가격 미제공')

    def test_draft_revision_raw_markdown_and_five_item_boundary(self):
        old=copy.deepcopy(self.draft)
        self.save([DOCUMENT]*5)
        self.assertEqual(self.draft['items'][0]['document'],DOCUMENT)
        with self.assertRaises(ContractError):self.app.save(self.draft['id'],old)
        candidate=copy.deepcopy(self.draft);candidate['items'].append({'id':'a'*32,'document':DOCUMENT})
        with self.assertRaises(ContractError):self.app.save(self.draft['id'],candidate)
        self.assertEqual(len(self.app.get(self.draft['id'])['items']),5)

    def test_one_and_five_items_all_pairs_and_fixed_run_snapshot(self):
        self.save([DOCUMENT],budget=1500)
        self.app.start(self.draft['id']);self.assertEqual(self.finish(self.draft['id'])['cursor'],28)
        report=self.app.report(self.draft['id']);self.assertEqual(report['comparisons'],[])
        snapshot=self.app.snapshot(self.draft['id'])
        self.assertEqual(snapshot['spec']['products'][0]['document'],DOCUMENT)
        with self.assertRaises(ContractError):self.app.save(self.draft['id'],self.draft)
        clone=self.app.create(self.draft['id']);self.draft=clone
        self.save([DOCUMENT.replace('2000',str(price)) for price in (2000,900,500,1500,3100)],budget=1500)
        self.app.start(self.draft['id']);self.assertEqual(self.finish(self.draft['id'])['cursor'],140)
        report=self.app.report(self.draft['id'])
        self.assertEqual((len(report['products']),len(report['comparisons']),report['backend_errors']),(5,10,0))
        self.assertTrue(all(pair['paired_count']==4 for pair in report['comparisons']))
        self.assertEqual(report['comparisons'][0]['transitions'],[{'from':'decline','to':'buy','count':4}])
        for fmt in ('json','csv','md','spec'):self.assertTrue(self.app.export(self.draft['id'],fmt)[0])
        markdown=self.app.export(self.draft['id'],'md')[0]
        self.assertEqual(markdown.count('### '),10)
        self.assertIn(report['comparisons'][-1]['to_product'],markdown)
        detail=self.app.detail(self.draft['id'],report['examples'][0]['job_id'])
        self.assertEqual(detail['product']['document'],self.draft['items'][0]['document'])

    def test_empty_panel_does_not_freeze_editable_draft(self):
        self.save([DOCUMENT]);candidate=copy.deepcopy(self.draft);candidate['panel']={'selection':'filter','query':'impossible-match-zzzz'}
        self.draft=self.app.save(candidate['id'],candidate)
        with self.assertRaises(ContractError):self.app.start(self.draft['id'])
        self.assertIsNone(self.app.status(self.draft['id']))

    def test_home_lock_and_cross_writer_lock_precede_inference(self):
        with self.assertRaises(ValueError):Application(self.app.root,self.app.home,FixtureBackend())
        self.save([DOCUMENT]);spec=self.app.make_spec(self.draft);store=Path(self.temp.name)/'shared.sqlite'
        entered=threading.Event();release=threading.Event()
        class Slow(FixtureBackend):
            def decide(self,job):entered.set();release.wait(3);return super().decide(job)
        errors=[]
        def first():
            try:run(self.app.data_path,self.source,spec,store,Slow())
            except Exception as error:errors.append(error)
        thread=threading.Thread(target=first);thread.start();self.assertTrue(entered.wait(2))
        try:
            with self.assertRaisesRegex(ContractError,'another writer'):run(self.app.data_path,self.source,spec,store,FixtureBackend())
            self.assertEqual(read_status(store)['status'],'running')
        finally:release.set();thread.join(5)
        self.assertEqual(errors,[])
        self.assertEqual(read_status(store)['cursor'],28)

    def test_malformed_model_envelopes_are_item_errors(self):
        self.save([DOCUMENT]);spec=self.app.make_spec(self.draft)
        for i,envelope in enumerate(([],{'choices':[]},{'usage':None,'choices':[]})):
            with self.subTest(envelope=envelope):
                with patch('persona_lab.backends.urllib.request.urlopen',side_effect=lambda *args,**kwargs:io.BytesIO(json.dumps(envelope).encode())):
                    store=Path(self.temp.name)/f'bad-{i}.sqlite'
                    result=run(self.app.data_path,self.source,spec,store,LocalLLMBackend())
                self.assertEqual((result['cursor'],result['status']),(28,'completed_with_errors'))
                self.assertEqual(result['backend_errors'],20)

    def test_report_is_one_snapshot_while_writer_commits(self):
        self.save([DOCUMENT]);spec=self.app.make_spec(self.draft);store=Path(self.temp.name)/'snapshot.sqlite'
        run(self.app.data_path,self.source,spec,store,FixtureBackend(),max_batches=1)
        connect=sqlite3.connect;triggered=False
        class Reader(sqlite3.Connection):
            def execute(inner,sql,parameters=()):
                nonlocal triggered
                if not triggered and sql.startswith('SELECT product_id,question_id'):
                    triggered=True
                    with patch('persona_lab.reports.sqlite3.connect',connect):run(self.app.data_path,self.source,spec,store,FixtureBackend())
                return super().execute(sql,parameters)
        with patch('persona_lab.reports.sqlite3.connect',side_effect=lambda p:connect(p,factory=Reader)):
            report=summarize(store)
        self.assertEqual((report['completed_jobs'],report['valid_decisions']),(8,8))
        self.assertEqual(read_status(store)['cursor'],28)

    def test_loopback_http_flow_token_origin_and_export(self):
        server=make_server(self.app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_address[1]}'
        def call(path,body=None,headers=None):
            req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'X-Persona-Token':server.token,'Content-Type':'application/json',**(headers or {})})
            with urllib.request.urlopen(req,timeout=5) as response:return json.load(response)
        try:
            self.assertEqual(call('/api/state')['max_items'],5)
            for headers in ({'X-Persona-Token':'bad'},{'Origin':'https://outside.example'},{'Host':'outside.example'}):
                with self.assertRaises(urllib.error.HTTPError):call('/api/state',headers=headers) if 'Origin' not in headers else call('/api/experiments',{},headers)
            self.save([DOCUMENT],budget=1500)
            call('/api/experiments/'+self.draft['id']+'/start',{})
            self.assertEqual(self.finish(self.draft['id'])['cursor'],28)
            self.assertEqual(call('/api/experiments/'+self.draft['id']+'/report')['planned_jobs'],28)
            self.assertIn('document',call('/api/experiments/'+self.draft['id']+'/export',{'format':'spec'})['body'])
            with self.assertRaises(urllib.error.HTTPError):call('/api/experiments/'+self.draft['id']+'/export',{'format':'../../file'})
        finally:server.shutdown();server.server_close();thread.join(2)

if __name__=='__main__':unittest.main()
