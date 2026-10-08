"""Optional DOM/API regression using an already installed development jsdom."""
import os, sys, subprocess, tempfile, shutil, json, hashlib, threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from persona_desktop.application import Application
from persona_desktop.server import make_server
from persona_lab.backends import FixtureBackend
jsdom=os.environ.get('PERSONA_LAB_JSDOM',str(ROOT/'node_modules/jsdom'))
if not Path(jsdom).is_dir():raise SystemExit('Set PERSONA_LAB_JSDOM to an existing development jsdom installation; the app does not use it.')
for suite in ('test_ui.cjs','test_response_ui.cjs'):
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary)/'resources';(root/'assets/data').mkdir(parents=True)
  source=json.loads((ROOT/'demo/data/packs/synthetic-fixture.json').read_text());raw=(ROOT/'demo/data/packs/synthetic-fixture.jsonl').read_bytes();source['local_sha256']=hashlib.sha256(raw).hexdigest()
  (root/'assets/data/nemotron-japan-sample.json').write_text(json.dumps(source));(root/'assets/data'/source['data_file']).write_bytes(raw);shutil.copy2(ROOT/'assets/questions.json',root/'assets/questions.json')
  app=Application(root,Path(temporary)/'home',FixtureBackend())
  if suite=='test_ui.cjs':
   # Keep the old seven-question flow as a compatibility regression.
   legacy=app.create();legacy.pop('run',None);legacy.pop('legacy_items',None);legacy['workflow']='legacy'
   legacy['items']=[{'id':legacy['items'][0]['id'],'document':''}];legacy['settings']['budget']=None
   (app.directory(legacy['id'])/'draft.json').write_text(json.dumps(legacy))
  server=make_server(app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   subprocess.run(['node',str(ROOT/'tests'/suite)],env={**os.environ,'PERSONA_LAB_JSDOM':jsdom,'PERSONA_LAB_UI_URL':f'http://127.0.0.1:{server.server_address[1]}','PERSONA_LAB_UI_TOKEN':server.token},check=True)
  finally:server.shutdown();server.server_close();app.close();thread.join(2)
