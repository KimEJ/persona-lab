"""Decision/TinyTroupe seam probe only; full runtime and model integration are excluded."""
import ast,copy,json,logging,sys
from dataclasses import asdict,replace
from pathlib import Path
from types import SimpleNamespace
from typing import List,Optional
from pydantic import BaseModel,ValidationError
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'src'))
from persona_lab.adapter import read_personas
from persona_lab.backends import context_gate,FixtureBackend
from persona_lab.contracts import Decision,ContractError,canonical,validate_decision
from persona_lab.runner import jobs
upstream=root/'.research/upstream/tinytroupe/tinytroupe'
tree=ast.parse((upstream/'agent/__init__.py').read_text())
names={'Action','CognitiveState','CognitiveActionModel'}
space={'BaseModel':BaseModel,'Optional':Optional,'List':List}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in names],type_ignores=[]),'pinned-tiny-schemas','exec'),space)
spec=json.loads((root/'assets/questions.json').read_text());spec['products']=spec['products'][:1];spec['assumptions']={'purchase_budget_jpy_minor':1500}
source=json.loads((root/'demo/data/packs/synthetic-fixture.json').read_text())
job=next(j for j in jobs(root/'demo/data/packs/synthetic-fixture.jsonl',source,spec) if j.question['domain']=='purchase')
expected=FixtureBackend().decide(job);validate_decision(expected,job)
try:space['CognitiveActionModel'].model_validate(asdict(expected));raise AssertionError('Decision unexpectedly accepted by stock schema')
except ValidationError as error:missing=[e['loc'][0] for e in error.errors()]
assert set(missing)=={'action','cognitive_state'}
# Execute only the actual upstream act function, with memory/render/retry facilities stubbed.
# This tests the generator/consumer seam, NOT the full TinyTroupe runtime or model behavior.
person_tree=ast.parse((upstream/'agent/tiny_person.py').read_text())
cls=next(n for n in person_tree.body if isinstance(n,ast.ClassDef) and n.name=='TinyPerson')
act=copy.deepcopy(next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='act'));act.decorator_list=[]
utils=SimpleNamespace(next_action_jaccard_similarity=lambda *a:0,first_non_none=lambda *a:next((v for v in a if v is not None),None))
context={'utils':utils,'logger':logging.getLogger('probe'),'TinyPerson':SimpleNamespace(MAX_ACTIONS_BEFORE_DONE=10,MAX_ACTION_SIMILARITY=None,MAX_IMAGE_STIMULI_TO_RECALL=0,communication_display=False),'repeat_on_error':lambda **kwargs:lambda fn:fn}
exec(compile(ast.fix_missing_locations(ast.Module(body=[act],type_ignores=[])),'pinned-tiny-act','exec'),context)
class DecisionGenerator:
    def __init__(self,backend,job):self.backend=backend;self.job=job;self.result=None
    def generate_next_actions(self,agent,current_messages):
        result=context_gate(self.job)
        if result is None:result=self.backend.decide(self.job)
        validate_decision(result,self.job);self.result=result
        actions=[{'type':'DECIDE','content':canonical(asdict(result)),'target':''},{'type':'DONE','content':'','target':''}]
        return actions,'assistant',{'actions':actions},[]
class Backend:
    def __init__(self,result=None,failure=None):self.calls=0;self.result=result;self.failure=failure
    def decide(self,job):
        self.calls+=1
        if self.failure:raise self.failure
        return self.result
class Actor:
    act=context['act']
    def __init__(self,generator):
        self.name='probe';self.action_generator=generator;self.actions_count=0;self._actions_buffer=[];self._mental_faculties=[];self.enable_basic_action_repetition_prevention=False
        self.current_messages=[];self.episodic_memory=SimpleNamespace(retrieve_recent=lambda:[]);self.memories=[];self.state={'goals':[],'context':[],'attention':None,'emotions':None}
    def reset_prompt(self):pass
    def store_in_memory(self,record):self.memories.append(record)
    def iso_datetime(self):return None
    def consolidate_episode_memories(self):pass
    def _update_cognitive_state(self,**kwargs):raise AssertionError('Decision path synthesized cognitive state')
backend=Backend(expected);actor=Actor(DecisionGenerator(backend,job));before=copy.deepcopy(actor.state);output=actor.act(return_actions=True)
assert backend.calls==1 and [x['action']['type'] for x in output]==['DECIDE','DONE']
assert json.loads(output[0]['action']['content'])==asdict(expected) or json.loads(output[0]['action']['content'])==json.loads(canonical(asdict(expected)))
assert actor.state==before and len(actor.memories)==2
# Missing context remains unknown and makes no backend call.
missing_job=replace(job,assumptions={});missing_backend=Backend(expected);missing_actor=Actor(DecisionGenerator(missing_backend,missing_job));missing_output=missing_actor.act(return_actions=True)
assert missing_actor.action_generator.result.choice=='unknown' and missing_backend.calls==0
# Reject unlisted choices before any action is recorded.
bad=Backend(Decision('unsupported','ok',('test',),('product.intro',)));invalid=Actor(DecisionGenerator(bad,job))
try:invalid.act(return_actions=True);raise AssertionError('Unlisted choice accepted')
except ContractError:assert invalid.memories==[] and invalid._actions_buffer==[]
# Keep a backend failure as an error; do not manufacture an unknown or DONE success.
failed=Actor(DecisionGenerator(Backend(failure=OSError('model failed')),job))
try:failed.act(return_actions=True);raise AssertionError('Backend error hidden')
except OSError:assert failed.memories==[]
receipt={'scope':'stock output schema and actual upstream act function isolated with mock DecisionBackend; memory, rendering, retry and import initialization stubbed; no full runtime, no inference, no TinyWorld or batch benchmark','upstream_commit':'a6244b358a1fe1c71bf751f7ba0f8dfa368ec5a4','stock_schema_rejects_direct_decision':missing,'custom_generator_single_mock_backend_call':backend.calls,'action_types':[x['action']['type'] for x in output],'choice':expected.choice,'cognitive_state_not_synthesized':True,'missing_context_returns_unknown_without_backend_call':True,'unlisted_choice_rejected_before_record':True,'backend_error_not_replaced_with_unknown':True,'dedicated_decision_model_integration':'not tested','full_tinytroupe_runtime':'not tested'}
(root/'.research/probes/tiny-decision.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt,ensure_ascii=False))
