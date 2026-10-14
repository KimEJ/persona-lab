"""Atomic drafts, immutable run snapshots and the product API."""
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
import difflib
import tempfile
import unicodedata
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from persona_lab.adapter import read_personas
from persona_lab.contracts import canonical, require, validate_experiment, digest
from persona_lab.runner import matches, selected_personas, run, read_status, jobs, preflight_jobs
from persona_lab.reports import summarize, export, result_page
from persona_lab.scenarios import SCENARIO_ID
from persona_lab.responses import SURVEY_V4_SCENARIO_ID as RESPONSE_SCENARIO_ID, SURVEY_V3_SCENARIO_ID, SURVEY_V2_SCENARIO_ID, SURVEY_SCENARIO_ID, DECISION_SCENARIO_ID, FINITE_SCENARIO_IDS, LINKED_SCENARIO_ID, LINKED_SCENARIO_IDS, RESPONSE_SCENARIO_IDS, QUESTIONS, LINKED_QUESTIONS, DECISION_QUESTIONS, price_bands, input_product
from persona_lab.survey import SURVEY_QUESTIONS, SURVEY_V2_QUESTIONS, SURVEY_V3_QUESTIONS, SURVEY_V4_QUESTIONS, STAGED_PROTOCOL, question_info
from .results import response_report, experiment_report
from .documents import product_from_item, DOCUMENT_TEMPLATE, item_name, price_from_document, money_from_fields, pricing_fields, valuation_fields, valuation_from_fields
from .model import BundledModel
from .valuation import calibrate
from .importing import normalize_settings


APP_LOCALE = 'ko'
SURVEY_WORKFLOWS = {SURVEY_V2_SCENARIO_ID, SURVEY_V3_SCENARIO_ID, RESPONSE_SCENARIO_ID}


def now(): return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def random_panel(panel=None, seed=None):
    panel=panel or {}
    filters={key:panel[key] for key in ('prefecture','age_min','age_max','sex','query','tags','tag_mode') if key in panel}
    return {'selection':'random','sample_size':panel.get('sample_size',100),'sample_seed':panel.get('sample_seed',seed if seed is not None else uuid.uuid4().int & 0xffffffff),'sampling_version':'hash-rank-v1',**filters}


def question_catalog(questions, scenario_id=None):
    return [{**question,'title':question_info(question['domain'],scenario_id)['title'],'labels':question_info(question['domain'],scenario_id)['choices']} for question in questions]


class Application:
    def __init__(self, root: Path, home: Path, test_backend=None):
        self.root, self.home = root.resolve(), home.resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.home_lock = (self.home/'writer.lock').open('a')
        try: fcntl.flock(self.home_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.home_lock.close(); raise ValueError('다른 Paneloom 앱이 실행 중입니다.')
        self.experiments = self.home/'experiments'; self.experiments.mkdir(exist_ok=True)
        self.source = json.loads((self.root/'assets/data/nemotron-japan-sample.json').read_text())
        self.source_cache={}
        self.tag_catalog_cache=OrderedDict()
        self.data_path,self.people=self.source_pack(self.source)
        self.template = json.loads((self.root/'assets/questions.json').read_text())
        self.test_backend = test_backend
        self.model = None if test_backend is not None else BundledModel(self.root/'assets', self.home)
        self.workers = {}
        self.lock = threading.RLock()

    def source_pack(self, source):
        key=digest(source)
        if key not in self.source_cache:
            filename=source.get('data_file')
            require(isinstance(filename,str) and Path(filename).name==filename, 'invalid bundled data filename')
            path=self.root/'assets/data'/filename
            require(path.resolve().parent==(self.root/'assets/data').resolve(), 'invalid bundled data path')
            require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==source.get('local_sha256'), '실행에 필요한 고정 데이터 파일을 찾지 못했습니다.')
            # ponytail: bounded bundled pool in memory; use a catalog for million-row packs.
            people=list(read_personas(path,source))
            require(len(people)==source['record_count'] and len({person.uuid for person in people})==len(people), '패널의 인원 또는 UUID가 일치하지 않습니다.')
            self.source_cache[key]=(path,people)
        return self.source_cache[key]

    def directory(self, identifier):
        require(isinstance(identifier,str) and re.fullmatch('[a-f0-9]{32}',identifier) is not None, 'invalid experiment id')
        directory = self.experiments/identifier
        require((directory/'draft.json').is_file(), '실험을 찾을 수 없습니다.')
        return directory

    def get(self, identifier):
        directory = self.directory(identifier)
        draft = json.loads((directory/'draft.json').read_text())
        status = self.status(identifier)
        snapshot = self.snapshot(identifier) if status else None
        if snapshot: draft = snapshot['draft']
        if not status:
            if draft.get('workflow') in {None,'product-response-v1','product-response-v2',DECISION_SCENARIO_ID,SURVEY_SCENARIO_ID,SURVEY_V2_SCENARIO_ID,SURVEY_V3_SCENARIO_ID,'independent-choice-v1',SCENARIO_ID}:draft['workflow']=RESPONSE_SCENARIO_ID
            for item in draft['items']:
                if not item['document'].strip():
                    item['document']=DOCUMENT_TEMPLATE
                    if 'pricing' not in item:item.update(name='',pricing=pricing_fields(None))
                elif draft['workflow']==RESPONSE_SCENARIO_ID and 'pricing' not in item:
                    item.update(name=item_name(item['document']),pricing=pricing_fields(price_from_document(item['document'])))
                if draft['workflow']==RESPONSE_SCENARIO_ID:item.setdefault('valuation',valuation_fields({'valuation_unit':{key:item['pricing'][key] for key in ('currency','billing')},'valuation_bands':[]}))
            if draft['workflow']==RESPONSE_SCENARIO_ID:
                draft['settings']={key:draft['settings'][key] for key in ('seed','repeats')}
                draft['panel']=random_panel(draft['panel'],int(digest(['panel',identifier])[:8],16))
        draft['run'] = status
        if snapshot and snapshot['spec']['scenario'].get('id') in RESPONSE_SCENARIO_IDS:
            draft['question_catalog']=question_catalog(snapshot['spec']['questions'],snapshot['spec']['scenario']['id'])
        elif not status and draft.get('workflow')==RESPONSE_SCENARIO_ID:
            draft['question_catalog']=question_catalog(SURVEY_V4_QUESTIONS,RESPONSE_SCENARIO_ID)
        fixed = {product['id']:product for product in snapshot['spec']['products']} if snapshot else {}
        draft['legacy_items']={item['id']:{'name':fixed[item['id']]['name'] if item['id'] in fixed else item_name(item['document']),'pricing':pricing_fields(fixed[item['id']]['price'] if item['id'] in fixed else price_from_document(item['document']))} for item in draft['items'] if 'pricing' not in item}
        return draft

    def history(self):
        paths = sorted(self.experiments.glob('*/draft.json'), key=lambda p:p.stat().st_mtime, reverse=True)
        return [{'id':draft['id'],'title':draft['title'],'updated_at':draft['updated_at'],'item_count':len(draft['items']),'revision':draft['revision'],'run':draft['run']} for draft in (self.get(path.parent.name) for path in paths)]

    def model_status(self):
        return self.model.status() if self.model else {'phase':'ready','error':None,'info':{'name':'Mock · 테스트 전용','model_id':self.test_backend.backend_id,'license':'project fixture','url':''}}

    def state(self):
        deleted=[{'id':path.parent.name,'title':json.loads(path.read_text())['title']} for path in sorted((self.home/'deleted-experiments').glob('*/draft.json'),key=lambda p:p.parent.stat().st_mtime,reverse=True)]
        return {'version':'0.8.1','history':self.history(),'deleted':deleted,'source':self.source,'model':self.model_status(),'document_template':DOCUMENT_TEMPLATE,'max_items':5,'home':str(self.home),'prefectures':sorted({p.raw['prefecture'] for p in self.people if p.raw.get('prefecture')}),'survey_questions':question_catalog(SURVEY_V4_QUESTIONS,RESPONSE_SCENARIO_ID),'tag_locale':APP_LOCALE}

    def create(self, copy_from=None):
        with self.lock:
            identifier = uuid.uuid4().hex
            original = self.get(copy_from) if copy_from else None
            items = original['items'] if original else [{'id':uuid.uuid4().hex,'name':'','document':DOCUMENT_TEMPLATE,'pricing':{'state':'unset','amount':'','currency':'JPY','billing':'one_time'}}]
            if original:
                fixed={product['id']:product for product in self.snapshot(copy_from)['spec']['products']} if original['run'] else {}
                for item in items:
                    if 'pricing' not in item:item.update(original['legacy_items'][item['id']])
                    item.setdefault('valuation',valuation_fields(fixed.get(item['id'],{'valuation_unit':{key:item['pricing'][key] for key in ('currency','billing')}})))
            else:items[0]['valuation']=valuation_fields()
            draft = {'id':identifier,'title':(original['title']+' 복제') if original else '새 실험','workflow':RESPONSE_SCENARIO_ID,'revision':0,'updated_at':now(),'items':items,'panel':random_panel(original['panel'] if original else None),'settings':{key:original['settings'][key] for key in ('seed','repeats')} if original else {'seed':17,'repeats':1}}
            directory = self.experiments/identifier; directory.mkdir()
            atomic_json(directory/'draft.json',draft)
            return self.get(identifier)

    def import_settings(self, value):
        with self.lock:
            fields = normalize_settings(value)
            fields['workflow'] = RESPONSE_SCENARIO_ID
            identifier = uuid.uuid4().hex
            draft = {'id': identifier, **fields, 'revision': 0, 'updated_at': now()}
            self.make_spec(draft, allow_empty=True)
            if draft['panel']['selection'] != 'random':
                count = sum(matches(person, draft['panel']) for person in self.people)
                draft['panel'] = random_panel({**draft['panel'], 'sample_size': max(1, count)}, draft['settings']['seed'])
            self.make_spec(draft, allow_empty=True)
            # Publish only after validation and a complete atomic write.
            with tempfile.TemporaryDirectory(prefix='.settings-import-', dir=self.home) as staging:
                directory = Path(staging)
                atomic_json(directory/'draft.json', draft)
                directory.rename(self.experiments/identifier)
            return self.get(identifier)

    def remove(self, identifier):
        with self.lock:
            directory=self.directory(identifier)
            require(not self.status(identifier) or not self.status(identifier)['active'], '실험을 먼저 중단하세요.')
            trash=self.home/'deleted-experiments';trash.mkdir(exist_ok=True)
            require(not (trash/identifier).exists(), '이미 삭제된 실험입니다.')
            directory.rename(trash/identifier)
            os.utime(trash/identifier,None)
            return {'id':identifier}

    def restore(self, identifier):
        with self.lock:
            require(isinstance(identifier,str) and re.fullmatch('[a-f0-9]{32}',identifier) is not None,'invalid experiment id')
            directory=self.home/'deleted-experiments'/identifier
            require((directory/'draft.json').is_file() and not (self.experiments/identifier).exists(), '복원할 실험을 찾을 수 없습니다.')
            directory.rename(self.experiments/identifier)
            return self.get(identifier)

    def save(self, identifier, data):
        with self.lock:
            directory = self.directory(identifier)
            previous = self.get(identifier)
            require(previous['run'] is None, '실행한 문서는 고정됩니다. 복제해서 수정하세요.')
            require(data.get('revision') == previous['revision'], '저장 내용이 바뀌었습니다. 실험을 다시 열어 확인하세요.')
            title = data.get('title')
            require(isinstance(title,str) and 0 < len(title.strip()) <= 120, '실험 이름을 확인하세요.')
            items = data.get('items')
            require(isinstance(items,list) and 1 <= len(items) <= 5, '아이템은 1~5개까지 사용할 수 있습니다.')
            for item in items:
                require(isinstance(item,dict) and set(item) in ({'id','document'},{'id','name','document','pricing'},{'id','name','document','pricing','valuation'}) and isinstance(item['id'],str) and re.fullmatch('[a-f0-9]{32}',item['id']) is not None, '아이템 형식이 올바르지 않습니다.')
                require(isinstance(item['document'],str) and len(item['document']) <= 20000, '문서는 20,000자까지 사용할 수 있습니다.')
            require(len({item['id'] for item in items}) == len(items),'아이템 식별자가 중복됩니다.')
            panel, settings = data.get('panel'), data.get('settings')
            require(isinstance(panel,dict) and isinstance(settings,dict),'실행 조건을 확인하세요.')
            candidate = {**previous,'title':title.strip(),'items':items,'panel':panel,'settings':settings,'revision':previous['revision']+1,'updated_at':now()}
            candidate.pop('run',None)
            candidate.pop('legacy_items',None)
            candidate.pop('question_catalog',None)
            self.make_spec(candidate, allow_empty=True)
            atomic_json(directory/'draft.json',candidate)
            return self.get(identifier)

    def make_spec(self,draft,allow_empty=False):
        products=[]
        for index,item in enumerate(draft['items'],1):
            candidate=dict(item)
            if allow_empty and not candidate['document'].strip(): candidate['document']='미작성 문서'
            product=product_from_item(candidate,index,allow_empty)
            if draft.get('workflow') in SURVEY_WORKFLOWS:
                value=candidate.get('valuation',valuation_fields({**product,'valuation_bands':[]}))
                product['valuation_unit'],product['valuation_bands']=valuation_from_fields(value)
                if value.get('mode')=='auto':product['valuation_mode']='auto'
            products.append(product)
        settings=draft['settings']
        require(set(settings)<= {'seed','repeats','budget','event'},'지원하지 않는 실행 조건입니다.')
        require(type(settings.get('seed')) is int and type(settings.get('repeats')) is int,'실행 조건은 정수여야 합니다.')
        assumptions={}
        if draft.get('workflow') in RESPONSE_SCENARIO_IDS:
            require('selected_uuids' not in draft['panel'], '실행 전에는 고정된 추출 인물을 지정할 수 없습니다.')
            for product in products:
                product.setdefault('valuation_unit',{'currency':(product.get('price') or {}).get('currency','JPY'),'billing':(product.get('price') or {}).get('billing','one_time')})
                if draft['workflow'] not in SURVEY_WORKFLOWS:product['valuation_bands']=price_bands(product['valuation_unit']['currency'])
            linked=draft['workflow'] in LINKED_SCENARIO_IDS
            questions=SURVEY_V4_QUESTIONS if draft['workflow']==RESPONSE_SCENARIO_ID else SURVEY_V3_QUESTIONS if draft['workflow']==SURVEY_V3_SCENARIO_ID else SURVEY_V2_QUESTIONS if draft['workflow']==SURVEY_V2_SCENARIO_ID else SURVEY_QUESTIONS if draft['workflow']==SURVEY_SCENARIO_ID else DECISION_QUESTIONS if draft['workflow']==DECISION_SCENARIO_ID else LINKED_QUESTIONS if linked else QUESTIONS
            grouped=draft['workflow'] in SURVEY_WORKFLOWS
            spec={'schema_version':'0.1','experiment_id':draft['id'],'mode':'independent_comparison','panel':draft['panel'],'seed':settings['seed'],'repeats':settings['repeats'],'batch_size':7 if draft['workflow']==RESPONSE_SCENARIO_ID else len(questions) if grouped else 1 if linked else 8,'products':products,'questions':questions,'scenario':{'id':draft['workflow'],'initial_state_id':'initial-v1','events':[]},'assumptions':{}}
            if grouped:spec['inference_protocol']=STAGED_PROTOCOL if draft['workflow']==RESPONSE_SCENARIO_ID else 'survey-grouped-v2' if draft['workflow']==SURVEY_V3_SCENARIO_ID else 'survey-grouped-v1'
            return validate_experiment(spec)
        budget=settings.get('budget')
        structured=any('pricing' in item for item in draft['items']) or isinstance(budget,dict)
        if budget is not None:
            if isinstance(budget,dict):
                amount=money_from_fields(budget,allow_empty=True)
                if amount is not None:assumptions['purchase_budget']=amount
            else:
                require(type(budget) is int and budget>=0,'구매 상한은 0 이상의 정수 JPY로 입력하세요.')
                assumptions['purchase_budget' if structured else 'purchase_budget_jpy_minor']=({'amount_minor':budget,'currency':'JPY','billing':'one_time'} if structured else budget)
        event=settings.get('event','')
        require(event in {'','repeated_crash','unexpected_permission','price_increase'},'사용 후 사건을 확인하세요.')
        spec={'schema_version':'0.1','experiment_id':draft['id'],'mode':'independent_comparison','panel':draft['panel'],'seed':settings['seed'],'repeats':settings['repeats'],'batch_size':8,'products':products,'questions':self.template['questions'],'scenario':{'id':SCENARIO_ID if structured else 'independent-choice-v1','initial_state_id':'initial-v1','events':[{'code':event,'origin':'user_explicit_scenario'}] if event else []},'assumptions':assumptions}
        return validate_experiment(spec)

    def panel(self,panel,identifier=None):
        people=self.people
        if identifier and self.status(identifier):
            snapshot=self.snapshot(identifier)
            panel=snapshot['spec']['panel'];_,people=self.source_pack(snapshot['source'])
        spec=dict(self.template); spec['panel']=panel
        validate_experiment(spec)
        eligible=sum(matches(person,panel) for person in people)
        selected=list(selected_personas(people,panel))
        value={'count':len(selected),'sample_size':len(selected),'eligible_count':eligible,'requested_size':panel.get('sample_size',eligible)}
        if panel['selection']!='random':value['items']=[{'uuid':p.uuid,'raw':p.raw,'missing':p.missing} for p in selected[:20]]
        return value

    def panel_tags(self, panel, identifier=None, query='', locale=APP_LOCALE):
        from persona_lab.tags import canonical_tag_id, tag_catalog, tag_metadata, valid_tag_id
        require(isinstance(query, str) and len(query) <= 120, '태그 검색어는 120자까지 입력하세요.')
        require(isinstance(locale, str) and locale in {'ko', 'en', 'ja'}, '태그 언어는 한국어·영어·일본어 중에서 선택하세요.')
        query = unicodedata.normalize('NFKC', query).casefold().strip().lstrip('#').strip()
        query_id = canonical_tag_id(query) if valid_tag_id(query) else None
        with self.lock:
            people, source = self.people, self.source
            if identifier and self.status(identifier):
                snapshot = self.snapshot(identifier)
                panel, source = snapshot['spec']['panel'], snapshot['source']
                _, people = self.source_pack(source)
            spec = dict(self.template); spec['panel'] = panel
            validate_experiment(spec)
            filters = {key: panel[key] for key in ('prefecture', 'age_min', 'age_max', 'sex', 'query') if key in panel}
            base = {'selection': 'filter' if filters else 'all', **filters}
            source_key = digest(source)
            def cached_catalog(conditions):
                key = (source_key, canonical(conditions))
                catalog = self.tag_catalog_cache.get(key)
                if catalog is None:
                    catalog = sorted(tag_catalog(person for person in people if matches(person, conditions)),
                                     key=lambda tag: (-tag['count'], tag['id']))
                    self.tag_catalog_cache[key] = catalog
                    if len(self.tag_catalog_cache) > 64:
                        self.tag_catalog_cache.popitem(last=False)
                self.tag_catalog_cache.move_to_end(key)
                return catalog
            catalog = cached_catalog(base)
            kind_labels = {'skill': '기술 skill skills スキル 技術',
                           'interest': '관심사 interest interests 趣味 関心',
                           'occupation': '직업 occupation job 職業'}
            def matching(tag):
                if query_id == canonical_tag_id(tag['id']):
                    return True
                text = ' '.join((tag['id'], *tag.get('aliases', []),
                                 *tag.get('labels', {}).values(), tag['label'],
                                 kind_labels.get(tag['kind'], '')))
                return query in unicodedata.normalize('NFKC', text).casefold()
            selected = panel.get('tags', [])
            equivalents = {canonical_tag_id(identifier) for identifier in selected}
            source_labels, found = {}, []
            for tag in catalog:
                canonical_id = canonical_tag_id(tag['id'])
                if canonical_id in equivalents:
                    source_labels[canonical_id] = tag['label']
                elif not query or matching(tag):
                    found.append(tag)
            if filters and equivalents - source_labels.keys():
                for tag in cached_catalog({'selection': 'all'}):
                    canonical_id = canonical_tag_id(tag['id'])
                    if canonical_id in equivalents:
                        source_labels[canonical_id] = tag['label']
            return {'tags': [{**tag_metadata(tag['id'], locale, source_label=tag['label']), 'count': tag['count']}
                             for tag in found[:16]],
                    'selected': [tag_metadata(identifier, locale, source_label=source_labels.get(canonical_tag_id(identifier)))
                                 for identifier in selected],
                    'total': len(catalog), 'matched': len(found), 'tag_locale': locale}

    def status(self,identifier):
        with self.lock:
            return self._status(identifier)

    def _status(self,identifier):
        directory=self.directory(identifier)
        manifest=directory/'run.json'
        preparation=directory/'preparation.json'
        if not manifest.exists() and not preparation.exists(): return None
        worker=self.workers.get(identifier)
        active=bool(worker and worker[0].is_alive())
        value={'cursor':0,'total':None,'status':'preparing','error':None,'backend_errors':0}
        if not manifest.exists():
            state=json.loads(preparation.read_text()).get('price_calibration') or {}
            products=state.get('products',{})
            pending=next((item for item in products.values() if item.get('status') in {'pending','exploring'}),{})
            value.update(phase='price_calibration',status='calibrating' if active else 'paused' if worker and worker[1].is_set() else 'interrupted',
                         calibration={'completed':state.get('completed',0),'total':state.get('total',0),'product_name':pending.get('name','')})
        elif (directory/'run.sqlite').exists():
            try: value=read_status(directory/'run.sqlite')
            except (ValueError,sqlite3.OperationalError): pass
        if not active and value['status'] in {'running','retrying','preparing'}: value['status']='interrupted'
        if (directory/'error.txt').exists(): value.update(status='failed',error=(directory/'error.txt').read_text())
        return {**value,'active':active,'cancel_requested':bool(worker and worker[1].is_set())}

    def start(self,identifier,retry=False):
        with self.lock:
            require(not any(worker[0].is_alive() for worker in self.workers.values()),'다른 실험을 처리 중입니다. 먼저 일시 중단하세요.')
            directory=self.directory(identifier)
            manifest=directory/'run.json'
            preparation=directory/'preparation.json'
            if manifest.exists():
                snapshot=json.loads(manifest.read_text()); spec=snapshot['spec']
            elif preparation.exists():
                require(not retry,'먼저 실험을 완료하세요.')
                snapshot=json.loads(preparation.read_text());spec=snapshot['spec']
            else:
                require(not retry,'먼저 실험을 실행하세요.')
                draft=self.get(identifier); spec=self.make_spec(draft)
                selected=list(selected_personas(self.people,spec['panel']))
                require(bool(selected),'조건에 맞는 인물이 없습니다. 필터를 넓혀 주세요.')
                if spec['panel']['selection']=='random':spec['panel']={**spec['panel'],'selected_uuids':[person.uuid for person in selected]}
                frozen_draft={key:value for key,value in draft.items() if key not in {'run','legacy_items','question_catalog'}}
                frozen_draft['panel']=spec['panel']
                snapshot={'draft':frozen_draft,'spec':spec,'source':self.source,'created_at':now()}
            source=snapshot['source'];data_path,_=self.source_pack(source)
            backend=self.test_backend if self.test_backend is not None else self.model.backend(structured=spec['scenario'].get('id')==SCENARIO_ID,response=spec['scenario'].get('id')=='product-response-v1',linked=spec['scenario'].get('id')==LINKED_SCENARIO_ID,finite=spec['scenario'].get('id') in FINITE_SCENARIO_IDS,survey=spec['scenario'].get('id')==SURVEY_SCENARIO_ID,survey_version=spec['scenario']['id'] if spec['scenario'].get('id') in SURVEY_WORKFLOWS else None,inference_protocol=spec.get('inference_protocol'),survey_questions=spec['questions'] if spec.get('inference_protocol') else None)
            if backend.kind == 'dedicated_local_decision':
                saved_backend = (read_status(directory/'run.sqlite')['backend_id'] if (directory/'run.sqlite').is_file()
                                 else snapshot.get('price_calibration', {}).get('backend_id'))
                require(saved_backend is None or saved_backend == backend.backend_id,
                        '추론 런타임이 변경되어 이전 결과와 섞어 재개할 수 없습니다. 실험을 복제한 뒤 새로 실행하세요.')
            if not manifest.exists():
                preflight_jobs(backend,jobs(data_path,source,{**spec,'repeats':1}))
            calibrating=not manifest.exists() and any(product.get('valuation_mode')=='auto' for product in spec['products'])
            if not manifest.exists():atomic_json(preparation if calibrating else manifest,snapshot)
            if retry:
                status=self.status(identifier)
                require(status and status['cursor']==status['total'] and status['backend_errors']>0,'전체 실행 완료 후 오류 항목을 재시도하세요.')
            event=threading.Event()
            (directory/'error.txt').unlink(missing_ok=True)
            def work():
                try:
                    main_spec=spec
                    if calibrating:
                        _,people=self.source_pack(source)
                        def checkpoint(state):
                            snapshot['price_calibration']=state
                            atomic_json(preparation,snapshot)
                        previous_audit=getattr(backend,'audit',None)
                        with sqlite3.connect(directory/'price-calibration.sqlite') as journal:
                            journal.execute('CREATE TABLE IF NOT EXISTS model_calls (id INTEGER PRIMARY KEY,job_id TEXT,started_at TEXT,request TEXT,response TEXT,error TEXT,finished_at TEXT)')
                            def audit(action,identifier,value):
                                if action=='start':
                                    row=journal.execute('INSERT INTO model_calls(job_id,started_at,request) VALUES (?,?,?)',(identifier,value['time'],value.get('request_text',canonical(value['request']))))
                                    journal.commit();return row.lastrowid
                                journal.execute('UPDATE model_calls SET response=COALESCE(?,response),error=?,finished_at=? WHERE id=?',(value.get('response'),value.get('error'),value['time'],identifier));journal.commit()
                            if hasattr(backend,'audit'):backend.audit=audit
                            try:
                                products,state,complete=calibrate(spec['products'],people,spec['panel'],backend,identifier,spec['seed'],
                                                                 state=snapshot.get('price_calibration'),cancelled=event.is_set,checkpoint=checkpoint,scenario_id=spec['scenario']['id'])
                            finally:
                                if hasattr(backend,'audit'):backend.audit=previous_audit
                        checkpoint(state)
                        if not complete or event.is_set():return
                        main_spec=validate_experiment({**spec,'products':products})
                        if not preflight_jobs(backend,jobs(data_path,source,{**main_spec,'repeats':1}),cancelled=event.is_set):return
                        snapshot['spec']=main_spec
                        with self.lock:
                            atomic_json(manifest,snapshot)
                            preparation.unlink(missing_ok=True)
                    run(data_path,source,main_spec,directory/'run.sqlite',backend,cancelled=event.is_set,retry_errors=retry)
                except Exception as error: (directory/'error.txt').write_text(str(error)[:1000])
            thread=threading.Thread(target=work,name='experiment-'+identifier[:8],daemon=True)
            self.workers[identifier]=(thread,event);thread.start()
            return self.get(identifier)

    def cancel(self,identifier):
        self.directory(identifier)
        worker=self.workers.get(identifier)
        if worker:worker[1].set()
        return self.status(identifier)

    def tag_report_locale(self, report):
        responses = report.get('responses', {})
        for context in (report.get('report_context'), report.get('context'),
                        responses.get('report_context'), responses.get('context')):
            if isinstance(context, dict):
                context['tag_locale'] = APP_LOCALE
        return report

    def report(self,identifier,repeat=0,include_calls=False):
        directory=self.directory(identifier)
        require((directory/'run.sqlite').exists(),'판단 결과를 준비 중입니다.')
        snapshot=self.snapshot(identifier)
        if snapshot['spec']['scenario'].get('id') in RESPONSE_SCENARIO_IDS:
            _,people=self.source_pack(snapshot['source'])
            report=experiment_report(directory/'run.sqlite',people,repeat,self.reviews(identifier),snapshot,include_calls)
            if include_calls and snapshot.get('price_calibration') is not None:
                report['price_calibration']=snapshot['price_calibration']
                report['price_calibration_calls']=self.model_calls(directory,filename='price-calibration.sqlite')
            return self.tag_report_locale(report)
        return summarize(directory/'run.sqlite')

    def responses(self, identifier, repeat=0):
        path=self.directory(identifier)/'run.sqlite'
        require(path.is_file(), '판단 결과를 준비 중입니다.')
        snapshot=self.snapshot(identifier)
        _,people=self.source_pack(snapshot['source'])
        return self.tag_report_locale(response_report(path,people,repeat,self.reviews(identifier),snapshot))

    def results(self, identifier, **filters):
        directory = self.directory(identifier)
        require((directory/'run.sqlite').is_file(), '판단 결과를 준비 중입니다.')
        return result_page(directory/'run.sqlite', reviews=directory/'reviews.sqlite', **filters)

    def review(self, identifier, job):
        path = self.directory(identifier)/'reviews.sqlite'
        if path.is_file():
            db = sqlite3.connect(path)
            try:
                row = db.execute('SELECT revision,note,marked,updated_at FROM reviews WHERE job_id=?', (job,)).fetchone()
                if row:
                    return dict(zip(('revision','note','marked','updated_at'), (row[0],row[1],bool(row[2]),row[3])))
            finally: db.close()
        return {'revision':0,'note':'','marked':False,'updated_at':None}

    def save_review(self, identifier, job, data):
        require(isinstance(job,str) and re.fullmatch('[a-f0-9]{64}',job) is not None, 'invalid job id')
        require(set(data)=={'revision','note','marked'} and type(data['revision']) is int and type(data['marked']) is bool, '검토 기록 형식을 확인하세요.')
        require(isinstance(data['note'],str) and len(data['note'])<=2000, '메모는 2,000자까지 사용할 수 있습니다.')
        with self.lock:
            directory = self.directory(identifier)
            require((directory/'run.sqlite').is_file(), '판단 결과를 찾을 수 없습니다.')
            original = sqlite3.connect(directory/'run.sqlite')
            try: require(original.execute('SELECT 1 FROM results WHERE job_id=?', (job,)).fetchone() is not None, '판단을 찾을 수 없습니다.')
            finally: original.close()
            db = sqlite3.connect(directory/'reviews.sqlite')
            try:
                db.executescript('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS reviews(job_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, note TEXT NOT NULL, marked INTEGER NOT NULL, updated_at TEXT NOT NULL);')
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT revision FROM reviews WHERE job_id=?', (job,)).fetchone()
                revision = row[0] if row else 0
                require(data['revision']==revision, '메모가 바뀌었습니다. 판단 상세를 다시 열어 확인하세요.')
                db.execute('INSERT INTO reviews VALUES(?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET revision=excluded.revision,note=excluded.note,marked=excluded.marked,updated_at=excluded.updated_at', (job,revision+1,data['note'],int(data['marked']),now()))
                db.commit()
            finally: db.close()
            return self.review(identifier,job)

    def reviews(self, identifier):
        path = self.directory(identifier)/'reviews.sqlite'
        if not path.is_file(): return {}
        db = sqlite3.connect(path)
        try:
            return {job:{'revision':revision,'note':note,'marked':bool(marked),'updated_at':updated} for job,revision,note,marked,updated in db.execute('SELECT * FROM reviews ORDER BY updated_at,job_id')}
        finally: db.close()

    def compare_documents(self, identifier, baseline, item):
        draft = self.snapshot(identifier)['draft'] if self.status(identifier) else self.get(identifier)
        items = {entry['id']:entry for entry in draft['items']}
        require(baseline in items and item in items and baseline!=item, '비교할 아이템을 선택하세요.')
        def comparable(entry):
            if 'pricing' not in entry:return entry['document']
            p=entry['pricing'];price='미입력' if p['state']=='unset' else '무료' if p['state']=='free' else p['amount']+' '+p['currency']+' / '+{'one_time':'일시불','monthly':'월간','annual':'연간'}[p['billing']]
            return '상품명: '+entry['name']+'\n가격: '+price+'\n\n'+entry['document']
        left, right = comparable(items[baseline]), comparable(items[item])
        rows = []
        # At most 20k characters per side; stdlib owns the line diff.
        for line in list(difflib.unified_diff(left.splitlines(),right.splitlines(),n=3))[2:]:
            rows.append({'kind':'range' if line.startswith('@@') else 'remove' if line.startswith('-') else 'add' if line.startswith('+') else 'same','text':line[1:] if not line.startswith('@@') else line})
        return {'baseline':baseline,'item':item,'frozen':bool(self.status(identifier)),'rows':rows[:500],'total_rows':len(rows)}

    def snapshot(self,identifier):
        with self.lock:
            directory=self.directory(identifier)
            path=directory/'run.json'
            if not path.is_file():path=directory/'preparation.json'
            require(path.is_file(),'저장한 실행 조건이 없습니다.')
            return json.loads(path.read_text())

    def detail(self,identifier,job):
        require(isinstance(job,str) and re.fullmatch('[a-f0-9]{64}',job) is not None,'invalid job id')
        directory=self.directory(identifier)
        with sqlite3.connect(directory/'run.sqlite') as db:
            row=db.execute('SELECT payload FROM results WHERE job_id=?',(job,)).fetchone()
            require(row is not None,'판단을 찾을 수 없습니다.')
            record=json.loads(row[0])
            traces=self.model_calls(directory,job,db)
        snapshot=self.snapshot(identifier)
        _,people=self.source_pack(snapshot['source'])
        person=next((p for p in people if p.uuid==record['uuid']),None)
        require(person is not None and person.content_hash==record['persona_content_hash'] and snapshot['source']['source_id']==record['source_id'] and snapshot['source']['version']==record['source_version'] and snapshot['source']['license_id']==record['license_id'],'당시 인물 원문을 확인할 수 없습니다.')
        product=next(p for p in snapshot['spec']['products'] if p['id']==record['product_id'])
        scenario=snapshot['spec']['scenario'].get('id')
        domain='usage' if scenario in {*SURVEY_WORKFLOWS,SURVEY_SCENARIO_ID} and record['domain']!='purchase' else record['domain']
        supplied=input_product(product,domain) if scenario in RESPONSE_SCENARIO_IDS else product
        return {'record':record,'model_calls':traces,'review':self.review(identifier,job),'persona':{'raw':person.raw,'missing':person.missing},'product':supplied,'offered_product':product,'question':next(q for q in snapshot['spec']['questions'] if q['id']==record['question_id']),'conditions':{'assumptions':snapshot['spec']['assumptions'],'scenario':snapshot['spec']['scenario']}}

    @staticmethod
    def model_calls(directory,job=None,db=None,filename='run.sqlite'):
        if db is None:
            if not (directory/filename).is_file():return []
            with sqlite3.connect(directory/filename) as connection:return Application.model_calls(directory,job,connection)
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_calls'").fetchone():return []
        keys=('id','job_id','started_at','request','response','error','finished_at')
        where,parameters='',()
        if job:
            where,parameters=' WHERE job_id=?',(job,)
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_call_jobs'").fetchone():
                where+=' OR id IN (SELECT call_id FROM model_call_jobs WHERE job_id=?)'
                parameters=(job,job)
        return [dict(zip(keys,row)) for row in db.execute('SELECT '+','.join(keys)+' FROM model_calls'+where+' ORDER BY id',parameters)]

    def export(self,identifier,format,repeat=0):
        directory=self.directory(identifier)
        if format=='spec':return json.dumps(self.snapshot(identifier),ensure_ascii=False,indent=2),'application/json'
        notes=self.reviews(identifier)
        if format=='reviews':return json.dumps({'experiment_id':identifier,'reviews':notes},ensure_ascii=False,indent=2),'application/json'
        if self.snapshot(identifier)['spec']['scenario'].get('id') in RESPONSE_SCENARIO_IDS:
            from .reporting import render_report
            report=self.report(identifier,repeat,include_calls=format=='json')
            report['reviews']=notes
            return render_report(report,'html' if format=='pdf' else format)
        body,mime=export(directory/'run.sqlite',format)
        if format=='json':
            value=json.loads(body);value['reviews']=notes;body=json.dumps(value,ensure_ascii=False,indent=2)
            if self.snapshot(identifier)['spec']['scenario'].get('id') in RESPONSE_SCENARIO_IDS:
                value['responses']=self.responses(identifier);value['model_calls']=self.model_calls(directory);body=json.dumps(value,ensure_ascii=False,indent=2)
        elif format=='md' and notes:
            escape=lambda text:text.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('|','\\|').replace('\n','<br>').replace('\r','')
            body+='\n## Review notes\n\n| Job | Marked | Note |\n| --- | --- | --- |\n'
            body+=''.join(f"| {job} | {str(note['marked']).lower()} | {escape(note['note'])} |\n" for job,note in notes.items())
        return body,mime

    def close(self):
        for _,event in self.workers.values():event.set()
        if self.model:self.model.close()
        for thread,_ in self.workers.values():thread.join(timeout=5)
        self.home_lock.close()
