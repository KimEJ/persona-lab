"""Isolated reference-code probes; requires the snapshots pinned in docs/archive/research/REFERENCE_SOURCES.json."""
import ast,hashlib,json,random,sqlite3,subprocess,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];review=root/".research";probes=review/"probes";probes.mkdir(exist_ok=True)
manifest=json.loads((root/'docs/archive/research/REFERENCE_SOURCES.json').read_text())
for record in manifest['repositories']:
    for evidence in record.get('reviewed_files',[]):
        file=root/record['local_path']/evidence['path']
        assert hashlib.sha256(file.read_bytes()).hexdigest()==evidence['sha256'],str(file)
# Only the inspected pure class/methods are executed; package imports and clients are excluded.
def methods(path,class_name,names=None):
    tree=ast.parse(path.read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==class_name)
    if names is not None:cls=ast.ClassDef(name=class_name,bases=[],keywords=[],body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names],decorator_list=[])
    module=ast.Module(body=[ast.ImportFrom(module="__future__",names=[ast.alias(name="annotations")],level=0),cls],type_ignores=[])
    space={"random":random};exec(compile(ast.fix_missing_locations(module),str(path),"exec"),space);return space[class_name]
randomizer=methods(review/"upstream/tinytroupe/tinytroupe/experimentation/randomization.py","ABRandomizer")
coin=randomizer(random_seed=42);orders=[coin.randomize(i,"left","right") for i in range(32)]
assert len(set(orders))==1
names={"_is_categorical_data","_extract_categories","_normalize_category","_convert_to_ordinal","_process_categorical_data_for_metric"}
metric=methods(review/"upstream/tinytroupe/tinytroupe/validation/simulation_validator.py","SimulationExperimentDataset",names)
converted=[];maps=[]
for values in [["buy"]*4,["decline"]*4]:
    obj=metric();obj.key_results={"purchase":values};obj.categorical_mappings={};obj._process_categorical_data_for_metric("purchase",values);converted.append(obj.key_results["purchase"]);maps.append(obj.categorical_mappings)
assert converted[0]==converted[1]==[0,0,0,0]
from collections import Counter
control=Counter(["buy"]*4);treatment=Counter(["decline"]*4)
tv=.5*sum(abs(control[k]/4-treatment[k]/4) for k in control.keys()|treatment.keys())
assert tv==1.0
# A narrow transplant candidate, emitted with its upstream license into the ignored probe directory.
utils=(review/"upstream/marktext/packages/muya/src/utils/index.ts").read_text()
start=utils.index("export interface IFenceLine");end=utils.index("/**",utils.index("export function parseFenceLine",start))
(probes/"marktext-fence.ts").write_text("// Extracted from pinned MarkText source; MIT. See LICENSE.marktext.\n"+utils[start:end])
(probes/"LICENSE.marktext").write_bytes((review/"upstream/marktext/LICENSE").read_bytes())
js=r"""const fs=require('node:fs');const {pathToFileURL}=require('node:url');const assert=require('node:assert/strict');
const {JSDOM}=require(process.env.PERSONA_LAB_JSDOM);const root=process.argv[2];
(async()=>{const {parseFenceLine}=await import(pathToFileURL(root+'/.research/probes/marktext-fence.ts'));const dom=new JSDOM('<div id="editor"></div>',{runScripts:'outside-only'});const w=dom.window;w.eval(fs.readFileSync(root+'/web/editor.js','utf8'));
const cases=[{name:'tilde fence',open:'~~~js',body:'a\n\n\nb',close:'~~~'},{name:'four backticks',open:'````js',body:'```\nconst a = 1\n```',close:'````'},{name:'fence info string',open:'```js title="x"',body:'const a = 1',close:'```'}];
const observations=[];for(const c of cases){const ref=parseFenceLine(c.open);assert.ok(ref);const element=w.document.getElementById('editor');const editor=new w.MarkdownEditor.Editor(element,()=>{});editor.setMarkdown('# Before\n\n'+c.open+'\n'+c.body+'\n'+c.close);const pre=element.querySelector('pre code');const displaysAsCode=Boolean(pre&&pre.textContent===c.body);element.querySelector('h1').textContent='After';element.dispatchEvent(new w.InputEvent('input',{bubbles:true}));const preserved=editor.getMarkdown().includes(c.open+'\n'+c.body+'\n'+c.close);observations.push({case:c.name,upstreamParserRecognizes:true,currentCodeRenderingCorrect:displaysAsCode,currentBlockPreservedAfterOtherEdit:preserved});}
dom.window.close();console.log(JSON.stringify(observations));})().catch(e=>{console.error(e);process.exitCode=1});"""
(probes/"editor.cjs").write_text(js)
env=__import__("os").environ.copy();env.setdefault("PERSONA_LAB_JSDOM",str(root/"node_modules/jsdom"))
editor=json.loads(subprocess.check_output(["node",str(probes/"editor.cjs"),str(root)],env=env,text=True))
# Adapter proof against the existing production SQLite result schema.
sys.path.insert(0,str(root/"src"));from persona_lab.runner import open_store
with tempfile.TemporaryDirectory() as tmp:
    db=open_store(Path(tmp)/"probe.sqlite");ordinal=0
    for person in range(30):
        for repeat in range(2):
            for product in range(5):
                if person==29 and repeat==1 and product==4:continue
                choice='buy';status='ok'
                if person==3 and product==1:choice='decline'
                if person==4 and product==2:choice='unknown';status='insufficient_information'
                if person==28 and product==3:choice='__backend_error__';status='backend_error'
                job=hashlib.sha256(str([person,repeat,product]).encode()).hexdigest()
                db.execute('INSERT INTO results VALUES (?,?,?,?,?,?,?,?,?,?,?)',(ordinal,job,str(person),str(person),str(product),'purchase','purchase',repeat,choice,status,'{}'));ordinal+=1
    db.commit();before=db.execute('SELECT COUNT(*) FROM results').fetchone()[0]
    sql="""SELECT a.persona_id,a.question_id,a.repeat,a.job_id,b.job_id,a.choice,b.choice,a.status,b.status FROM results a JOIN results b ON a.persona_id=b.persona_id AND a.question_id=b.question_id AND a.repeat=b.repeat WHERE a.product_id=? AND b.product_id=?"""
    valid=sql+" AND a.status!='backend_error' AND b.status!='backend_error'"
    changed=db.execute(valid+' AND a.choice!=b.choice',('0','1')).fetchall();assert len(changed)==2 and {row[2] for row in changed}=={0,1}
    unknown=db.execute(valid+" AND (a.choice='unknown' OR b.choice='unknown')",('0','2')).fetchall();assert len(unknown)==2
    errors=db.execute(sql+" AND (a.status='backend_error' OR b.status='backend_error')",('0','3')).fetchall();assert len(errors)==2
    assert int(errors[0][0])==28
    matched=db.execute(valid,('0','4')).fetchall();assert len(matched)==59
    first=db.execute(valid+' ORDER BY a.ordinal LIMIT ? OFFSET ?',('0','4',17,0)).fetchall();second=db.execute(valid+' ORDER BY a.ordinal LIMIT ? OFFSET ?',('0','4',17,17)).fetchall();assert not {r[3] for r in first}&{r[3] for r in second}
    assert db.execute('SELECT COUNT(*) FROM results').fetchone()[0]==before
    db.close()
receipt={"scope":"isolated inspected helpers + current editor DOM + proposed SQLite query; no integration, no upstream package install, no model calls","evidence_files_verified":sum(len(r.get('reviewed_files',[])) for r in manifest['repositories']),"tinytroupe":{"randomizer_seed":42,"calls":32,"distinct_orders":len(set(orders)),"distinct_categories_mapped_to_same_numbers":maps,"shared_label_distribution_distance":tv},"editor":editor,"sqlite":{"rows":before,"changed_pairs":2,"unknown_pairs":2,"late_error_pairs":2,"incomplete_pair_excluded":True,"pages_disjoint":True,"global_rows_preserved":True}}
(probes/"receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n")
print(json.dumps(receipt,ensure_ascii=False),flush=True)
