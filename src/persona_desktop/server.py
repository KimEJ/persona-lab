"""Loopback-only application service with a per-launch request token."""
import argparse
import json
import secrets
import signal
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from persona_lab.contracts import canonical, require
from .application import Application
from .documents import item_name, price_from_document, pricing_fields, MAX_DOCUMENT_CHARS


def make_server(app, port=0):
    token=secrets.token_hex(24)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def send(self,status,body,mime='application/json; charset=utf-8',filename=None):
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
            if filename:self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
            self.end_headers()
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass
        def json(self,data,status=200):self.send(status,canonical(data).encode())
        def host(self):
            require(self.headers.get('Host') in {f'127.0.0.1:{self.server.server_address[1]}',f'localhost:{self.server.server_address[1]}'},'invalid Host')
        def auth(self):
            require(secrets.compare_digest(self.headers.get('X-Persona-Token',''),token),'invalid app request')
            origin=self.headers.get('Origin')
            require(origin in {None,f'http://127.0.0.1:{self.server.server_address[1]}',f'http://localhost:{self.server.server_address[1]}'},'invalid Origin')
        def do_GET(self):
            try:
                self.host()
                parsed=urlparse(self.path);parts=parsed.path.strip('/').split('/');query=parse_qs(parsed.query,keep_blank_values=True)
                if parsed.path in {'/','/app.js','/editor.js','/results.js','/style.css','/results.css'}:
                    name='index.html' if parsed.path=='/' else parsed.path[1:]
                    body=(app.root/'web'/name).read_bytes()
                    if name=='index.html':body=body.replace(b'__APP_TOKEN__',token.encode())
                    mime='text/html; charset=utf-8' if name=='index.html' else 'application/javascript; charset=utf-8' if name.endswith('.js') else 'text/css; charset=utf-8'
                    self.send(200,body,mime);return
                self.auth()
                if parsed.path=='/api/state':self.json(app.state())
                elif len(parts)>=3 and parts[:2]==['api','experiments']:
                    identifier=parts[2]
                    if len(parts)==3:self.json(app.get(identifier))
                    elif len(parts)==4 and parts[3]=='report':
                        require(set(query)<= {'repeat'} and all(len(v)==1 for v in query.values()), 'unknown report filter')
                        self.json(app.report(identifier,int(query.get('repeat',['0'])[0])))
                    elif len(parts)==4 and parts[3]=='responses':
                        require(set(query)<= {'repeat'} and all(len(v)==1 for v in query.values()), 'unknown response filter')
                        self.json(app.responses(identifier,int(query.get('repeat',['0'])[0])))
                    elif len(parts)==4 and parts[3]=='results':
                        require(all(len(values)==1 for values in query.values()), 'duplicate query parameter')
                        require(set(query)<= {'mode','baseline','domain','query','offset','limit'}, 'unknown result filter')
                        value=lambda name,default=None:query.get(name,[default])[0]
                        self.json(app.results(identifier,mode=value('mode','all'),baseline=value('baseline'),domain=value('domain') or None,query=value('query',''),offset=int(value('offset','0')),limit=int(value('limit','25'))))
                    elif len(parts)==4 and parts[3]=='documents':
                        require(set(query)=={'baseline','item'} and all(len(v)==1 for v in query.values()), 'document comparison requires two items')
                        self.json(app.compare_documents(identifier,query['baseline'][0],query['item'][0]))
                    elif len(parts)==5 and parts[3]=='jobs':self.json(app.detail(identifier,parts[4]))
                    else:self.json({'error':'not found'},404)
                else:self.json({'error':'not found'},404)
            except (ValueError,TypeError,KeyError,OSError,sqlite3.Error) as error:self.json({'error':str(error)},400)
        def do_POST(self):
            try:
                self.host();self.auth()
                length=int(self.headers.get('Content-Length',0))
                require(0<length<=1048576,'request must be 1 byte to 1MB')
                data=json.loads(self.rfile.read(length));require(isinstance(data,dict),'request must be an object')
                parts=urlparse(self.path).path.strip('/').split('/')
                if self.path=='/api/experiments':self.json(app.create(data.get('copy_from')),201)
                elif self.path=='/api/panel':self.json(app.panel(data.get('panel',{'selection':'all'}),data.get('experiment_id')))
                elif self.path=='/api/document/inspect':
                    document=data.get('document');require(isinstance(document,str) and len(document)<=MAX_DOCUMENT_CHARS,'문서는 20,000자까지 사용할 수 있습니다.')
                    self.json({'name':item_name(document,''),'pricing':pricing_fields(price_from_document(document))})
                elif self.path=='/api/model/restart':
                    require(app.model is not None,'test model cannot restart')
                    require(not any(w[0].is_alive() for w in app.workers.values()),'실험을 먼저 중단하세요.')
                    from .model import BundledModel
                    origin=app.model.origin;app.model.close();app.model=BundledModel(app.root/'assets',app.home);app.model.start(origin)
                    self.json(app.model_status())
                elif len(parts)==4 and parts[:2]==['api','experiments']:
                    identifier,action=parts[2:]
                    if action=='save':self.json(app.save(identifier,data))
                    elif action=='delete':self.json(app.remove(identifier))
                    elif action=='restore':self.json(app.restore(identifier))
                    elif action in {'start','resume','retry'}:self.json(app.start(identifier,retry=action=='retry'))
                    elif action=='cancel':self.json(app.cancel(identifier))
                    elif action=='export':
                        format=data.get('format');require(format in {'json','csv','md','html','pdf','spec','reviews'},'invalid export format')
                        repeat=data.get('repeat',0);require(type(repeat) is int and repeat>=0,'invalid report repeat')
                        body,mime=app.export(identifier,format,repeat)
                        self.json({'body':body,'mime':mime,'format':format,'filename':f'persona-lab-{identifier[:8]}-r{repeat+1}.{format if format not in {"spec","reviews"} else "json"}'})
                    else:self.json({'error':'not found'},404)
                elif len(parts)==6 and parts[:2]==['api','experiments'] and parts[3]=='jobs' and parts[5]=='review':
                    self.json(app.save_review(parts[2],parts[4],data))
                else:self.json({'error':'not found'},404)
            except (ValueError,TypeError,KeyError,OSError,sqlite3.Error) as error:self.json({'error':str(error)},400)
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.token=token
    return server


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--home',type=Path,required=True)
    args=parser.parse_args()
    app=Application(args.root,args.home)
    server=make_server(app)
    origin=f'http://127.0.0.1:{server.server_address[1]}'
    app.model.start(origin)
    def stop(*_):threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    print(canonical({'url':origin}),flush=True)
    try:server.serve_forever(poll_interval=.25)
    finally:server.server_close();app.close()

if __name__=='__main__':main()
