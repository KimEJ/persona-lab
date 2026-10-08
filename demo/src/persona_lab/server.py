"""Local demo service. Static assets, known dataset packs and persisted runs only."""

import importlib.util
import json
import re
import sqlite3
import threading
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .adapter import read_personas
from .backends import FixtureBackend, LocalLLMBackend, JuliaBackend
from .contracts import ContractError, canonical, require, validate_experiment, validate_source
from .runner import run, read_status, matches
from .reports import summarize, export


class App:
    def __init__(self, root: Path):
        self.root = root
        self.workers: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self.lock = threading.Lock()
        self.import_workers = {}

    def packs(self) -> list[dict]:
        return [{**json.loads(path.read_text()), "id": path.stem} for path in sorted((self.root / "data/packs").glob("*.json"))]

    def pack(self, id: str) -> tuple[dict, Path]:
        require(bool(re.fullmatch(r"[a-z0-9-]+", id)), "invalid dataset id")
        entries = [pack for pack in self.packs() if pack["id"] == id]
        require(bool(entries), "dataset not found")
        source = entries[0]
        path = (self.root / "data/packs" / source["data_file"]).resolve()
        require(path.parent == (self.root / "data/packs").resolve(), "invalid dataset file")
        return source, path

    def run_dir(self, id: str) -> Path:
        require(bool(re.fullmatch(r"[a-f0-9]{32}", id)), "invalid run id")
        directory = self.root / "runs" / id
        require((directory / "manifest.json").exists(), "run not found")
        return directory

    def status(self, id: str) -> dict:
        directory = self.run_dir(id)
        manifest = json.loads((directory / "manifest.json").read_text())
        database = directory / "run.sqlite"
        worker = self.workers.get(id)
        alive = bool(worker and worker[0].is_alive())
        status = {"cursor": 0, "total": None, "status": "preparing", "backend_kind": manifest["backend"], "error": None}
        if database.exists():
            try:
                status = read_status(database)
            except (ContractError, sqlite3.OperationalError):
                pass
        if not alive and status["status"] in {"preparing", "running", "retrying"}:
            status["status"] = "interrupted"
        if (directory / "error.txt").exists():
            status["error"] = (directory / "error.txt").read_text()
            status["status"] = "failed"
        return {**status, "id": id, "experiment_id": manifest["spec"]["experiment_id"], "dataset_id": manifest["dataset_id"], "active": alive, "cancel_requested": bool(worker and worker[1].is_set()), "manifest": manifest}

    def start(self, id: str, retry_errors: bool = False) -> None:
        with self.lock:
            require(id not in self.workers or not self.workers[id][0].is_alive(), "run is already active")
            directory = self.run_dir(id)
            manifest = json.loads((directory / "manifest.json").read_text())
            source, path = self.pack(manifest["dataset_id"])
            backend = {"mock": FixtureBackend, "local": LocalLLMBackend, "julia": JuliaBackend}[manifest["backend"]]()
            event = threading.Event()
            def work():
                try:
                    (directory / "error.txt").unlink(missing_ok=True)
                    run(path, source, manifest["spec"], directory / "run.sqlite", backend, cancelled=event.is_set, retry_errors=retry_errors)
                except Exception as error:
                    (directory / "error.txt").write_text(str(error)[:1000])
            thread = threading.Thread(target=work, daemon=True, name=f"run-{id[:8]}")
            self.workers[id] = (thread, event)
            thread.start()

    def detail(self, id: str, job_id: str) -> dict:
        require(bool(re.fullmatch(r"[a-f0-9]{64}", job_id)), "invalid job id")
        directory = self.run_dir(id)
        manifest = json.loads((directory / "manifest.json").read_text())
        source, path = self.pack(manifest["dataset_id"])
        with sqlite3.connect(directory / "run.sqlite") as db:
            row = db.execute("SELECT payload FROM results WHERE job_id=?", (job_id,)).fetchone()
            require(row is not None, "saved job not found")
            record = json.loads(row[0])
            spec_json, source_json = db.execute("SELECT spec,source FROM run WHERE id=1").fetchone()
        spec, saved_source = json.loads(spec_json), json.loads(source_json)
        require(all(source[key] == saved_source[key] for key in ("source_id", "version", "license_id")), "source metadata changed; original input cannot be verified")
        if source.get("catalog_file"):
            from .catalog import indexed_persona
            person = indexed_persona(self.root, source, path, record["uuid"])
        else:
            person = next((person for person in read_personas(path, source) if person.uuid == record["uuid"]), None)
        require(person is not None and person.content_hash == record["persona_content_hash"], "source row changed or missing; original input cannot be verified")
        return {"saved_result": record, "source": saved_source, "persona": {"uuid": person.uuid, "raw": person.raw, "missing": person.missing, "field_provenance": person.field_provenance, "content_hash": person.content_hash}, "product": next(product for product in spec["products"] if product["id"] == record["product_id"]), "question": next(question for question in spec["questions"] if question["id"] == record["question_id"]), "assumptions": spec["assumptions"], "scenario": spec["scenario"], "verification": "Source row hash matches saved result. Backends use the central persona and structured fields; five specialized narratives are retained in raw but omitted from inference prompts."}

    def create(self, data: dict) -> dict:
        require(data.get("backend") in {"mock", "local", "julia"}, "choose mock, local or julia backend")
        self.pack(data.get("dataset_id", ""))
        spec = validate_experiment(data.get("spec", {}))
        id = uuid.uuid4().hex
        directory = self.root / "runs" / id
        directory.mkdir(parents=True)
        manifest = {"dataset_id": data["dataset_id"], "backend": data["backend"], "spec": spec}
        (directory / "manifest.json").write_text(canonical(manifest))
        self.start(id)
        return {"id": id}


    def import_status(self, identifier):
        from .parquet_import import read_import_status, import_locked
        status = read_import_status(self.root, identifier)
        worker = self.import_workers.get(identifier)
        managed_active = bool(worker and worker[0].is_alive())
        external_active = not managed_active and import_locked(self.root, identifier)
        active = managed_active or external_active
        if not active and status['status'] in {'running', 'preparing'}: status['status'] = 'interrupted'
        error_path = self.root / 'imports' / identifier / 'worker-error.txt'
        if not active and error_path.exists(): status.update(status='failed', error=error_path.read_text())
        return {**status, 'active': active, 'external_active': external_active, 'cancel_requested': bool(worker and worker[1].is_set())}

    def start_import(self, identifier):
        from .parquet_import import run_import, read_import_status, import_locked
        read_import_status(self.root, identifier)
        require(not import_locked(self.root, identifier), 'import writer is already active; CLI imports are paused with Ctrl+C')
        with self.lock:
            require(not any(worker[0].is_alive() for worker in self.import_workers.values()), 'another import is active; wait or pause it')
            event = threading.Event()
            def work():
                error_path = self.root / 'imports' / identifier / 'worker-error.txt'
                error_path.unlink(missing_ok=True)
                try: run_import(self.root, identifier, cancelled=event.is_set)
                except Exception as error: error_path.write_text(str(error)[:1000])
            thread = threading.Thread(target=work, daemon=True, name='import-' + identifier[:8])
            self.import_workers[identifier] = (thread, event); thread.start()

    def local_parquet(self, filename):
        require(isinstance(filename, str) and Path(filename).name == filename and filename.lower().endswith('.parquet'), 'choose a listed local Parquet basename')
        inbox = (self.root / 'data/inbox').resolve(); path = (inbox / filename).resolve()
        sidecar = (inbox / (filename + '.source.json')).resolve()
        require(path.parent == inbox and sidecar.parent == inbox and path.is_file() and sidecar.is_file(), 'local file and explicit .source.json must be in data/inbox; arbitrary paths/uploads rejected')
        source = json.loads(sidecar.read_text()); validate_source(source)
        return path, source

    def parquet_config(self):
        from .parquet_import import official_shards
        candidates = []
        for path in sorted((self.root / 'data/inbox').glob('*.parquet')):
            try:
                _, source = self.local_parquet(path.name)
                candidates.append({'filename': path.name, 'source_id': source.get('source_id'), 'license_id': source.get('license_id')})
            except (ValueError, OSError): pass
        return {'available': importlib.util.find_spec('pyarrow') is not None, 'official_shards': official_shards(self.root), 'local_files': candidates}


def serve(root: Path, port: int) -> None:
    require((root / "web/index.html").is_file(), "run serve from the persona-lab project folder")
    app = App(root)
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def send(self, status: int, body: bytes, mime: str = "application/json", filename: str | None = None):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def json(self, value, status=200):
            self.send(status, canonical(value).encode("utf-8"))

        def check_host(self):
            require(self.headers.get("Host") in allowed_hosts, "invalid Host header")

        def do_GET(self):
            try:
                self.check_host()
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                if parsed.path == "/api/parquet-config":
                    self.json(app.parquet_config())
                elif parsed.path == "/api/parquet-imports":
                    ids = [path.parent.name for path in sorted((root / 'imports').glob('*/manifest.json'), key=lambda path: path.stat().st_mtime, reverse=True)]
                    self.json([app.import_status(identifier) for identifier in ids])
                elif parsed.path.startswith('/api/parquet-imports/'):
                    parts = parsed.path.strip('/').split('/')
                    require(len(parts) == 3, 'invalid import status route')
                    self.json(app.import_status(parts[2]))
                elif parsed.path == "/api/packs":
                    self.json(app.packs())
                elif parsed.path == "/api/default-experiment":
                    self.json(json.loads((root / "examples/experiment.json").read_text()))
                elif parsed.path == "/api/backend-status":
                    try:
                        with urllib.request.urlopen("http://127.0.0.1:8081/health", timeout=2) as response:
                            healthy = response.status == 200
                    except OSError:
                        healthy = False
                    try:
                        with urllib.request.urlopen("http://127.0.0.1:8082/health", timeout=2) as response:
                            julia_healthy = response.status == 200
                    except OSError:
                        julia_healthy = False
                    self.json({"mock": True, "local_available": healthy, "julia_available": julia_healthy, "local_model": "Qwen3-0.6B Q8_0", "dedicated_model": "Julia-1", "external_api": "unconfigured"})
                elif parsed.path == "/api/personas":
                    source, path = app.pack(query.get("pack", [""])[0])
                    panel = {"selection": "filter"}
                    for key in ("prefecture", "query", "age_min", "age_max"):
                        if query.get(key, [""])[0] != "":
                            panel[key] = int(query[key][0]) if key.startswith("age_") else query[key][0]
                    require(panel.get("age_min", 0) <= panel.get("age_max", 10000), "age range is reversed")
                    offset = int(query.get("offset", [0])[0])
                    require(offset >= 0, "offset must be nonnegative")
                    if source.get('catalog_file'):
                        from .catalog import indexed_page
                        people, count = indexed_page(root, source, path, panel, offset)
                    else:
                        people, count = [], 0
                        for persona in read_personas(path, source):
                            if matches(persona, panel):
                                if offset <= count < offset + 20: people.append(persona)
                                count += 1
                    items = [{"uuid": persona.uuid, "raw": persona.raw, "missing": persona.missing, "field_provenance": persona.field_provenance, "content_hash": persona.content_hash} for persona in people]
                    self.json({"items": items, "matched_count": count, "offset": offset, "page_size": 20})
                elif parsed.path == "/api/runs":
                    ids = [path.parent.name for path in sorted((root / "runs").glob("*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)]
                    self.json([app.status(id) for id in ids])
                elif parsed.path.startswith("/api/runs/"):
                    parts = parsed.path.strip("/").split("/")
                    id = parts[2]
                    directory = app.run_dir(id)
                    if len(parts) == 3:
                        self.json(app.status(id))
                    elif parts[3] == "report":
                        self.json(summarize(directory / "run.sqlite"))
                    elif parts[3] == "jobs" and len(parts) == 5:
                        self.json(app.detail(id, parts[4]))
                    elif parts[3] == "export":
                        format = query.get("format", ["json"])[0]
                        body, mime = export(directory / "run.sqlite", format)
                        self.send(200, body.encode("utf-8"), mime, f"persona-lab-{id[:8]}.{format}")
                    elif parts[3] == "spec":
                        self.send(200, (directory / "manifest.json").read_bytes(), "application/json", f"persona-lab-{id[:8]}-spec.json")
                    else:
                        raise ContractError("unknown run route")
                elif parsed.path in {"/", "/app.js", "/style.css"}:
                    name = "index.html" if parsed.path == "/" else parsed.path[1:]
                    mime = {"index.html": "text/html; charset=utf-8", "app.js": "application/javascript", "style.css": "text/css"}[name]
                    self.send(200, (root / "web" / name).read_bytes(), mime)
                else:
                    self.json({"error": "not found"}, 404)
            except (ContractError, ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
                self.json({"error": str(error)}, 400)

        def do_POST(self):
            try:
                self.check_host()
                require(self.headers.get("X-Persona-Lab") == "demo-v1", "missing local UI request header")
                origin = self.headers.get("Origin")
                require(origin is None or origin in {f"http://{host}" for host in allowed_hosts}, "cross-origin request rejected")
                length = int(self.headers.get("Content-Length", 0))
                require(0 < length <= 131072, "request must be 1 to 128KB")
                data = json.loads(self.rfile.read(length))
                require(isinstance(data, dict), "request must be an object")
                if self.path == '/api/parquet-imports':
                    require(importlib.util.find_spec('pyarrow') is not None, 'PyArrow is not prepared; see docs/PARQUET.md')
                    from .parquet_import import create_import
                    if data.get('kind') == 'official_parquet':
                        require(set(data) == {'kind', 'shard'}, 'only a listed fixed official shard is supported')
                        identifier = create_import(root, shard=data['shard'])
                    elif data.get('kind') == 'local_parquet':
                        require(set(data) == {'kind', 'filename'}, 'only a listed local basename is supported')
                        path, source = app.local_parquet(data['filename']); identifier = create_import(root, local_path=path, source=source)
                    else: raise ContractError('choose official_parquet or local_parquet')
                    app.start_import(identifier); self.json({'id': identifier}, 201)
                elif self.path.startswith('/api/parquet-imports/'):
                    parts = self.path.strip('/').split('/')
                    require(len(parts) == 4 and parts[:2] == ['api', 'parquet-imports'], 'invalid import action')
                    identifier, action = parts[2:]; app.import_status(identifier)
                    if action == 'cancel':
                        worker = app.import_workers.get(identifier)
                        if worker: worker[1].set()
                    elif action == 'resume': app.start_import(identifier)
                    else: raise ContractError('unknown import action')
                    self.json({'id': identifier, 'action': action})
                elif self.path == "/api/runs":
                    self.json(app.create(data), 201)
                elif self.path == "/api/import":
                    require(data == {"dataset": "nemotron-japan-viewer"}, "only the fixed NVIDIA Viewer import is supported; arbitrary URLs/uploads are rejected")
                    from .importer import fetch_sample
                    with app.lock:
                        self.json(fetch_sample(root), 201)
                else:
                    parts = self.path.strip("/").split("/")
                    require(len(parts) == 4 and parts[:2] == ["api", "runs"], "unknown action route")
                    id, action = parts[2:]
                    app.run_dir(id)
                    if action == "cancel":
                        worker = app.workers.get(id)
                        if worker:
                            worker[1].set()
                    elif action == "resume":
                        app.start(id)
                    elif action == "retry":
                        app.start(id, retry_errors=True)
                    else:
                        raise ContractError("unknown action")
                    self.json({"id": id, "action": action})
            except (ContractError, ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
                self.json({"error": str(error)}, 400)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Persona Lab demo: http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for _, event in list(app.workers.values()) + list(app.import_workers.values()):
            event.set()
        server.server_close()
