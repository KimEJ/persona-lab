"""Lazy jobs, bounded batches and transactional SQLite checkpoints.

Single writer per run. Replays local input on resume; never expands all jobs.
"""

import hashlib
import heapq
import fcntl
import itertools
import json
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path
from collections.abc import Iterator, Callable

from . import __version__
from .adapter import read_personas
from .backends import DecisionBackend
from .tags import matching_tags
from .scenarios import execution_record, context_gate, SCENARIO_IDS
from .responses import RESPONSE_SCENARIO_IDS, LINKED_SCENARIO_IDS, FINITE_SCENARIO_IDS, SURVEY_SCENARIO_ID, SURVEY_V2_SCENARIO_ID, input_product
from .contracts import Job, Persona, ContractError, canonical, digest, require, validate_decision, validate_experiment, validate_source


def matches(persona: Persona, panel: dict) -> bool:
    if panel["selection"] == "all":
        return True
    raw = persona.raw
    if panel.get('sex') and sex_code(raw.get('sex'))!=panel['sex']:
        return False
    if panel.get("prefecture") and raw.get("prefecture") != panel["prefecture"]:
        return False
    if "age_min" in panel or "age_max" in panel:
        age = raw.get("age")
        if type(age) is not int or not panel.get("age_min", 0) <= age <= panel.get("age_max", 10000):
            return False
    if panel.get("query") and panel["query"].casefold() not in canonical(raw).casefold():
        return False
    requested = panel.get('tags', [])
    if requested:
        available = matching_tags(raw)
        return (all(identifier in available for identifier in requested)
                if panel.get('tag_mode', 'any') == 'all'
                else any(identifier in available for identifier in requested))
    return True


def sex_code(value):
    value=str(value or '').strip().casefold()
    if value in {'女','女性','female','woman','여성','여'}:return 'female'
    if value in {'男','男性','male','man','남성','남'}:return 'male'
    return 'unknown' if value in {'','unknown','미제공','不明'} else 'other'


def selected_personas(people, panel):
    """Sample once by stable hash rank; frozen UUIDs keep resume cohorts exact."""
    eligible=(person for person in people if matches(person,panel))
    if panel['selection']!='random':
        yield from eligible
    elif 'selected_uuids' in panel:
        ids=panel['selected_uuids'];wanted=set(ids);found={}
        for person in eligible:
            if person.uuid in wanted:
                require(person.uuid not in found, 'duplicate persona UUID in frozen sample')
                found[person.uuid]=person
        require(set(found)==wanted, 'frozen sample no longer matches its source or filters')
        yield from (found[identifier] for identifier in ids)
    else:
        yield from heapq.nsmallest(panel['sample_size'],eligible,key=lambda person:(digest(['hash-rank-v1',panel['sample_seed'],person.persona_id]),person.uuid))


def jobs(path: Path, source: dict, spec: dict) -> Iterator[Job]:
    ordinal = 0
    for persona in selected_personas(read_personas(path, source),spec['panel']):
        for product in spec["products"]:
            for repeat in range(spec["repeats"]):
                for question in spec["questions"]:
                    job_id = digest([spec["experiment_id"], persona.persona_id, product["id"], question["id"], repeat, spec["seed"]])
                    seed = int(digest([spec["seed"], persona.persona_id, repeat, question["id"]])[:8], 16) % 2147483647
                    domain='usage' if spec['scenario'].get('id') in {SURVEY_SCENARIO_ID,SURVEY_V2_SCENARIO_ID} and question['domain']!='purchase' else question['domain']
                    supplied = input_product(product, domain) if spec['scenario'].get('id') in RESPONSE_SCENARIO_IDS else product
                    yield Job(ordinal, job_id, persona, supplied, question, repeat, seed, spec["scenario"], spec["assumptions"])
                    ordinal += 1


def input_digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def open_store(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA temp_store=FILE")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS run (
          id INTEGER PRIMARY KEY CHECK(id=1), fingerprint TEXT NOT NULL,
          cursor INTEGER NOT NULL, total INTEGER NOT NULL, status TEXT NOT NULL,
          spec TEXT NOT NULL, source TEXT NOT NULL, backend_id TEXT NOT NULL,
          backend_kind TEXT NOT NULL, error TEXT
        );
        CREATE TABLE IF NOT EXISTS results (
          ordinal INTEGER PRIMARY KEY, job_id TEXT NOT NULL UNIQUE,
          persona_id TEXT NOT NULL, uuid TEXT NOT NULL, product_id TEXT NOT NULL,
          question_id TEXT NOT NULL, domain TEXT NOT NULL, repeat INTEGER NOT NULL,
          choice TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS result_comparison ON results(domain, persona_id, repeat, product_id);
        CREATE INDEX IF NOT EXISTS result_case ON results(persona_id,question_id,repeat,product_id);
        CREATE TABLE IF NOT EXISTS model_calls (
          id INTEGER PRIMARY KEY, job_id TEXT NOT NULL, started_at TEXT NOT NULL,
          request TEXT NOT NULL, response TEXT, error TEXT, finished_at TEXT
        );
        CREATE INDEX IF NOT EXISTS model_call_job ON model_calls(job_id,id);
    """)
    return db


def read_status(path: Path) -> dict:
    if not path.exists():
        raise ContractError("run does not exist")
    with sqlite3.connect(path) as db:
        db.execute("BEGIN")
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT cursor,total,status,backend_id,backend_kind,error FROM run WHERE id=1").fetchone()
        require(row is not None, "run has no metadata")
        result = dict(row)
        result["backend_errors"] = db.execute("SELECT COUNT(*) FROM results WHERE status='backend_error'").fetchone()[0]
        return result


def batch_outcomes(backend: DecisionBackend, batch: list[Job], cancelled: Callable[[], bool]):
    """Keyed optional inference batches; cancellation saves a returned whole chunk."""
    decide_batch = getattr(backend, "decide_batch", None)
    limit = getattr(backend, "batch_limit", 1) if callable(decide_batch) else 1
    require(type(limit) is int and 1 <= limit <= 1024, "invalid backend batch limit")
    for offset in range(0, len(batch), limit):
        if cancelled():
            break
        chunk = batch[offset:offset + limit]
        gated = {job.job_id: gate for job in chunk if job.scenario.get("id") in SCENARIO_IDS and (gate := context_gate(job)) is not None}
        active = [job for job in chunk if job.job_id not in gated]
        try:
            if not active:
                outcomes = {}
            elif callable(decide_batch):
                outcomes = decide_batch(active)
                require(isinstance(outcomes, dict) and set(outcomes) == {job.job_id for job in active}, "batch response IDs mismatch")
            else:
                outcomes = {active[0].job_id: backend.decide(active[0])}
        except (ContractError, OSError, ValueError) as error:
            outcomes = {job.job_id: error for job in active}
        outcomes.update(gated)
        for job in chunk:
            try:
                decision = outcomes[job.job_id]
                if isinstance(decision, Exception):
                    raise decision
                validate_decision(decision, job)
                yield job, decision, None
            except (ContractError, OSError, ValueError) as error:
                yield job, None, {"type": type(error).__name__, "message": str(error)[:500], "retryable": True}


def run(path: Path, source: dict, spec: dict, store: Path, backend: DecisionBackend, *, max_batches: int | None = None, retry_errors: bool = False, cancelled: Callable[[], bool] = lambda: False, progress: Callable[[dict], None] = lambda _: None) -> dict:
    store.parent.mkdir(parents=True, exist_ok=True)
    with store.with_suffix(store.suffix + ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ContractError("another writer is active for this experiment") from error
        return _run_locked(path, source, spec, store, backend, max_batches=max_batches, retry_errors=retry_errors, cancelled=cancelled, progress=progress)


def _run_locked(path: Path, source: dict, spec: dict, store: Path, backend: DecisionBackend, *, max_batches: int | None = None, retry_errors: bool = False, cancelled: Callable[[], bool] = lambda: False, progress: Callable[[dict], None] = lambda _: None) -> dict:
    validate_source(source)
    validate_experiment(spec)
    require(max_batches is None or type(max_batches) is int and max_batches > 0, "max_batches must be positive")
    fingerprint = digest({"engine": __version__, "input_sha256": input_digest(path), "source": source, "spec": spec, "backend_id": backend.backend_id, "backend_kind": backend.kind})
    db = open_store(store)
    previous_audit=getattr(backend,'audit',None)
    if hasattr(backend,'audit'):
        def audit(event,identifier,value):
            if event=='start':
                row=db.execute('INSERT INTO model_calls(job_id,started_at,request) VALUES (?,?,?)',(identifier,value['time'],value.get('request_text',canonical(value['request']))))
                db.commit();return row.lastrowid
            db.execute('UPDATE model_calls SET response=COALESCE(?,response),error=?,finished_at=? WHERE id=?',(value.get('response'),value.get('error'),value['time'],identifier));db.commit()
        backend.audit=audit
    try:
        row = db.execute("SELECT fingerprint,cursor,total FROM run WHERE id=1").fetchone()
        if row is None:
            # Counts and uniqueness remain on disk, not in a million-element set.
            db.execute("CREATE TEMP TABLE panel_ids (id TEXT PRIMARY KEY)")
            count = 0
            for persona in selected_personas(read_personas(path, source),spec['panel']):
                try:
                    db.execute("INSERT INTO panel_ids VALUES (?)", (persona.persona_id,))
                except sqlite3.IntegrityError as error:
                    raise ContractError(f"duplicate persona UUID: {persona.uuid}") from error
                count += 1
            require(count > 0, "selected panel is empty; broaden the filters")
            total = count * len(spec["products"]) * len(spec["questions"]) * spec["repeats"]
            require(total <= 9223372036854775807, "planned job count exceeds SQLite's 64-bit checkpoint range")
            db.execute("INSERT INTO run VALUES (1,?,0,?,'ready',?,?,?, ?,NULL)", (fingerprint, total, canonical(spec), canonical(source), backend.backend_id, backend.kind))
            db.commit()
            cursor = 0
        else:
            require(row[0] == fingerprint, "resume rejected: input, experiment, source, backend or engine changed")
            cursor, total = row[1:]
        require(db.execute("SELECT COUNT(*) FROM results").fetchone()[0] == cursor, "checkpoint/result count mismatch")
        require(0 <= cursor <= total, "checkpoint cursor is invalid")
        require(not retry_errors or cursor == total, "finish or resume the initial pass before retrying errors")
        db.execute("UPDATE run SET status=?,error=NULL WHERE id=1", ("retrying" if retry_errors else "running",))
        db.commit()
        progress({"cursor": cursor, "total": total, "status": "running"})
        pending = itertools.islice(jobs(path, source, spec), 0 if retry_errors else cursor, None)
        # Linked stages must commit before their dependent job is evaluated.
        batch_size=1 if spec['scenario'].get('id') in LINKED_SCENARIO_IDS else spec['batch_size']
        batch_count = 0
        retry_ordinal = -1
        stream_ordinal = 0
        while retry_errors or cursor < total:
            if cancelled() or max_batches is not None and batch_count >= max_batches:
                break
            if retry_errors:
                targets = [row[0] for row in db.execute("SELECT ordinal FROM results WHERE status='backend_error' AND ordinal>? ORDER BY ordinal LIMIT ?", (retry_ordinal, batch_size))]
                if not targets:
                    break
                batch = []
                for target in targets:
                    job = next(itertools.islice(pending, target - stream_ordinal, None), None)
                    require(job is not None and job.ordinal == target, "retry input cursor mismatch")
                    batch.append(job)
                    stream_ordinal = target + 1
                retry_ordinal = targets[-1]
            else:
                batch = list(itertools.islice(pending, batch_size))
                require(bool(batch), "input ended before planned job count")
            if spec['scenario'].get('id') in LINKED_SCENARIO_IDS:
                enriched=[]
                for job in batch:
                    if job.question['domain']=='purchase':
                        prior={}
                        from .survey import PREDECESSOR_DOMAINS
                        domains=PREDECESSOR_DOMAINS if spec['scenario'].get('id')==SURVEY_SCENARIO_ID else ('usage','fair_price')
                        for domain,payload in db.execute("SELECT domain,payload FROM results WHERE persona_id=? AND product_id=? AND repeat=?",(job.persona.persona_id,job.product['id'],job.repeat)):
                            if domain not in domains:continue
                            record=json.loads(payload);decision=record['decision']
                            prior[domain]={'job_id':record['job_id'],**{key:decision.get(key) for key in ('choice','reason','valuation','missing_information')}} if decision else {'job_id':record['job_id'],'choice':'error','error':record['backend_error']}
                        job=replace(job,assessments=prior)
                    enriched.append(job)
                batch=enriched
            completed = list(batch_outcomes(backend, batch, cancelled))
            if not completed:
                break
            # Result rows and the next ordinal are committed in one transaction.
            db.execute("BEGIN IMMEDIATE")
            require(db.execute("SELECT cursor FROM run WHERE id=1").fetchone()[0] == cursor, "another writer advanced this checkpoint")
            for job, decision, backend_error in completed:
                record = {"schema_version": "0.1", "job_id": job.job_id, "persona_id": job.persona.persona_id, "uuid": job.persona.uuid, "persona_content_hash": job.persona.content_hash, "source_id": source["source_id"], "source_version": source["version"], "license_id": source["license_id"], "product_id": job.product["id"], "question_id": job.question["id"], "domain": job.question["domain"], "repeat": job.repeat, "seed": job.seed, "initial_state_id": job.scenario["initial_state_id"], "backend_id": backend.backend_id, "backend_kind": backend.kind, "decision": asdict(decision) if decision else None, "backend_error": backend_error}
                if job.scenario.get('id') in LINKED_SCENARIO_IDS:record['assessments']=job.assessments
                elif decision:
                    record['decision'].pop('evidence',None);record['decision'].pop('valuation',None)
                if decision and job.scenario.get('id') not in FINITE_SCENARIO_IDS:
                    record['decision'].pop('option_probabilities',None);record['decision'].pop('probability_semantics',None);record['decision'].pop('diagnostic_error',None)
                choice, decision_status = (decision.choice, decision.status) if decision else ("__backend_error__", "backend_error")
                record["execution"] = execution_record(job, decision, backend_error)
                if retry_errors:
                    db.execute("UPDATE results SET choice=?,status=?,payload=? WHERE ordinal=? AND job_id=? AND status='backend_error'", (choice, decision_status, canonical(record), job.ordinal, job.job_id))
                else:
                    db.execute("INSERT INTO results VALUES (?,?,?,?,?,?,?,?,?,?,?)", (job.ordinal, job.job_id, job.persona.persona_id, job.persona.uuid, job.product["id"], job.question["id"], job.question["domain"], job.repeat, choice, decision_status, canonical(record)))
            if not retry_errors:
                cursor = completed[-1][0].ordinal + 1
            db.execute("UPDATE run SET cursor=? WHERE id=1", (cursor,))
            db.commit()
            batch_count += 1
            progress({"cursor": cursor, "total": total, "status": "running"})
        errors = db.execute("SELECT COUNT(*) FROM results WHERE status='backend_error'").fetchone()[0]
        status = ("completed_with_errors" if errors else "completed") if cursor == total else "paused"
        db.execute("UPDATE run SET status=? WHERE id=1", (status,))
        db.commit()
        progress({"cursor": cursor, "total": total, "status": status})
        return read_status(store)
    except Exception as error:
        db.rollback()
        if db.execute("SELECT 1 FROM run WHERE id=1").fetchone():
            db.execute("UPDATE run SET status='failed',error=? WHERE id=1", (str(error)[:1000],))
            db.commit()
        raise
    finally:
        if hasattr(backend,'audit'):backend.audit=previous_audit
        db.close()
