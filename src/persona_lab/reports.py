"""SQL aggregation and template export. No report model is used."""

import csv
import io
import json
import sqlite3
from itertools import combinations
from pathlib import Path

from .contracts import require
from .scenarios import budget_context


def result_page(path: Path, *, mode="all", baseline=None, domain=None, query="", offset=0, limit=25, reviews: Path | None = None) -> dict:
    """Page case rows, keeping every item's cell and the global report separate."""
    require(mode in {"all", "changed", "unknown", "errors", "marked"}, "unsupported result filter")
    require(type(offset) is int and offset >= 0 and type(limit) is int and 1 <= limit <= 100, "invalid result page")
    require(isinstance(query, str) and len(query) <= 120, "search must be at most 120 characters")
    db = sqlite3.connect(path)
    try:
        has_reviews = reviews is not None and reviews.is_file()
        if has_reviews:
            db.execute("ATTACH DATABASE ? AS review_db", (str(reviews),))
        db.execute("BEGIN")
        cursor, status, spec_json = db.execute("SELECT cursor,status,spec FROM run WHERE id=1").fetchone()
        spec = json.loads(spec_json)
        products = spec["products"]
        ids = [p["id"] for p in products]
        baseline = baseline or ids[0]
        require(baseline in ids, "baseline item does not exist")
        require(domain is None or domain in {q["domain"] for q in spec["questions"]}, "unknown judgment domain")
        where, params = ["1=1"], [baseline]
        if domain:
            where.append("r.domain=?"); params.append(domain)
        if query:
            where.append("r.uuid LIKE ? ESCAPE '\\'")
            params.append("%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        having = {
            "all": "1=1",
            "changed": "SUM(CASE WHEN r.status!='backend_error' AND b.status!='backend_error' AND r.choice!=b.choice THEN 1 ELSE 0 END)>0",
            "unknown": "SUM(CASE WHEN r.status!='backend_error' AND r.choice='unknown' THEN 1 ELSE 0 END)>0",
            "errors": "SUM(CASE WHEN r.status='backend_error' THEN 1 ELSE 0 END)>0",
            "marked": "SUM(CASE WHEN EXISTS(SELECT 1 FROM review_db.reviews v WHERE v.job_id=r.job_id AND v.marked=1) THEN 1 ELSE 0 END)>0" if has_reviews else "0=1",
        }[mode]
        grouped = """FROM results r LEFT JOIN results b
          ON b.persona_id=r.persona_id AND b.question_id=r.question_id AND b.repeat=r.repeat AND b.product_id=?
          WHERE """ + " AND ".join(where) + " GROUP BY r.persona_id,r.question_id,r.repeat HAVING " + having
        count = db.execute("SELECT COUNT(*) FROM (SELECT 1 " + grouped + ")", params).fetchone()[0]
        keys = db.execute("SELECT r.persona_id,r.question_id,r.repeat,MIN(r.ordinal),r.uuid,r.domain " + grouped + " ORDER BY MIN(r.ordinal) LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
        cells = {}
        if keys:
            placeholders = ",".join("(?,?,?)" for _ in keys)
            cell_params = [value for row in keys for value in row[:3]]
            review_join = " LEFT JOIN review_db.reviews v ON v.job_id=r.job_id " if has_reviews else ""
            review_fields = ",COALESCE(v.revision,0),COALESCE(v.note,''),COALESCE(v.marked,0),v.updated_at" if has_reviews else ",0,'',0,NULL"
            for person, question, repeat, product, payload, revision, note, marked, updated_at in db.execute("SELECT r.persona_id,r.question_id,r.repeat,r.product_id,r.payload" + review_fields + " FROM results r" + review_join + f" WHERE (r.persona_id,r.question_id,r.repeat) IN ({placeholders}) ORDER BY r.ordinal", cell_params):
                record = json.loads(payload)
                cells[(person, question, repeat, product)] = {"record": record, "review": {"revision": revision, "note": note, "marked": bool(marked), "updated_at": updated_at}}
        rows = [{"persona_id": person, "question_id": question, "repeat": repeat, "uuid": uuid, "domain": domain, "ordinal": ordinal, "cells": [cells.get((person, question, repeat, pid)) for pid in ids]} for person, question, repeat, ordinal, uuid, domain in keys]
        return {"rows": rows, "count": count, "offset": offset, "limit": limit, "snapshot_cursor": cursor, "status": status, "baseline": baseline, "products": [{"id": p["id"], "name": p["name"]} for p in products]}
    finally:
        db.close()


def summarize(path: Path, connection=None) -> dict:
    """Use an existing read transaction when composing a response report."""
    if connection is None:
        with sqlite3.connect(path) as db:
            db.execute("BEGIN")
            return summarize(path, connection=db)
    db = connection
    row = db.execute("SELECT cursor,total,status,spec,source,backend_id,backend_kind,error FROM run WHERE id=1").fetchone()
    require(row is not None, "run has no metadata")
    cursor, total, status, spec_json, source_json, backend_id, backend_kind, error = row
    spec = json.loads(spec_json)
    groups = {}
    for product, question, domain, choice, result_status, count in db.execute("SELECT product_id,question_id,domain,choice,status,COUNT(*) FROM results GROUP BY product_id,question_id,domain,choice,status ORDER BY product_id,question_id,choice"):
        group = groups.setdefault((product, question), {"product_id": product, "question_id": question, "domain": domain, "processed": 0, "completed": 0, "backend_errors": 0, "unknown": 0, "choice_counts": {}})
        group["processed"] += count
        if result_status == "backend_error":
            group["backend_errors"] += count
            continue
        group["completed"] += count
        group["unknown"] += count if choice == "unknown" else 0
        group["choice_counts"][choice] = count
    for group in groups.values():
        group["choice_shares"] = {choice: count / group["completed"] for choice, count in group["choice_counts"].items()} if group["completed"] else {}
    transitions = []
    comparisons = []
    if len(spec["products"]) >= 2:
        for first, second in combinations(spec["products"], 2):
            a, b = first["id"], second["id"]
            pairs = [{"from": old, "to": new, "count": count} for old, new, count in db.execute("""SELECT a.choice,b.choice,COUNT(*) FROM results a JOIN results b
          ON a.persona_id=b.persona_id AND a.repeat=b.repeat AND a.question_id=b.question_id
          WHERE a.domain='purchase' AND a.product_id=? AND b.product_id=? AND a.status!='backend_error' AND b.status!='backend_error'
          GROUP BY a.choice,b.choice ORDER BY a.choice,b.choice""", (a, b))]
            comparisons.append({"from_product": a, "to_product": b, "transitions": pairs, "paired_count": sum(pair["count"] for pair in pairs)})
        transitions = comparisons[0]["transitions"]
    examples = [json.loads(payload) for (payload,) in db.execute("SELECT payload FROM results ORDER BY ordinal LIMIT 28")]
    observed = db.execute("SELECT COUNT(DISTINCT persona_id) FROM results").fetchone()[0]
    # Audit contradictions without changing or excluding the model's choices.
    products = {product["id"]: product for product in spec["products"]}
    budget_conflicts = 0
    warning_examples = []
    for persona_id, product_id, job_id in db.execute("SELECT uuid,product_id,job_id FROM results WHERE domain='purchase' AND choice='buy' AND status!='backend_error' ORDER BY ordinal"):
        price = products[product_id]["price"]
        if price is None:
            continue
        budget,_ = budget_context(spec['assumptions'],persona_id,spec['scenario'])
        if budget is not None and all(price[key]==budget[key] for key in ('currency','billing')) and price['amount_minor']>budget['amount_minor']:
            budget_conflicts += 1
            if len(warning_examples) < 28:
                warning_examples.append({"code": "purchase_above_explicit_budget", "job_id": job_id, "uuid": persona_id, "product_id": product_id, "amount_minor": price["amount_minor"], "budget_minor": budget['amount_minor'],'currency':budget['currency'],'billing':budget['billing']})
    warnings = {"purchase_above_explicit_budget": budget_conflicts, "examples": warning_examples, "policy": "Preserve decisions and denominators; flag contradictions with a budget in the same currency and billing period. This is an input-consistency check, not behavior validation."}
    return {"schema_version": "0.1", "experiment_id": spec["experiment_id"], "status": status, "completed_jobs": cursor, "valid_decisions": sum(g["completed"] for g in groups.values()), "validity_semantics": "schema_contract_only_not_behavior_accuracy", "backend_errors": sum(g["backend_errors"] for g in groups.values()), "planned_jobs": total, "observed_personas": observed, "backend_id": backend_id, "backend_kind": backend_kind, "source": json.loads(source_json), "assumptions": spec["assumptions"], "scenario": spec["scenario"], "input_condition": "with_explicit_assumptions" if spec["assumptions"] or spec["scenario"]["events"] else "source_only", "consistency_warnings": warnings, "groups": list(groups.values()), "products": spec["products"], "panel": spec["panel"], "comparisons": comparisons, "paired_purchase_transitions": transitions, "paired_transition_count": sum(t["count"] for t in transitions), "examples": examples, "error": error, "limitations": ["This is a virtual choice experiment; actual purchase prediction is unvalidated. Synthetic choice shares are not real probabilities or revenue forecasts.", "Initial contrasts showed option-order sensitivity and unknown outputs in both local models; a dedicated architecture does not establish behavior accuracy.", "Unknown decisions remain in the valid-decision denominator; backend errors are counted separately.", "Partial-run results may be biased toward earlier input records.", "Reason codes are backend output; evidence paths require semantic review.", "Independent variants use the same initial state; no longitudinal behavior is invented."]}

def export(path: Path, format: str) -> tuple[str, str]:
    report = summarize(path)
    if format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2), "application/json"
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["product_id", "question_id", "domain", "choice", "count", "completed_denominator", "synthetic_choice_share", "result_status", "group_backend_errors", "backend_kind", "source_id", "source_version", "run_budget_conflicts", "input_condition", "assumptions_json", "scenario_json", "license_id", "license_url", "source_url", "attribution","product_name","price_amount_minor","price_currency","price_billing","price_state"])
        for group in report["groups"]:
            for choice, count in list(group["choice_counts"].items()) + ([("", group["backend_errors"])] if group["backend_errors"] else []):
                values = [group["product_id"], group["question_id"], group["domain"], choice, count, group["completed"], group["choice_shares"].get(choice, ""), ("backend_error" if choice == "" else "insufficient_information" if choice == "unknown" else "not_run" if choice=='not_run' else "ok"), group["backend_errors"], report["backend_kind"], report["source"]["source_id"], report["source"]["version"], report["consistency_warnings"]["purchase_above_explicit_budget"], report["input_condition"], json.dumps(report["assumptions"], ensure_ascii=False), json.dumps(report["scenario"], ensure_ascii=False), report["source"]["license_id"], report["source"]["license_url"], report["source"]["url"], report["source"].get("attribution", "Project-authored synthetic fixture")]
                product=next(p for p in report['products'] if p['id']==group['product_id']);price=product['price'] or {}
                values.extend([product['name'],price.get('amount_minor',''),price.get('currency',''),price.get('billing',''),product.get('price_state','legacy')])
                # Spreadsheet formula injection protection for user-defined identifiers.
                writer.writerow(["'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for value in values])
        return output.getvalue(), "text/csv; charset=utf-8"
    require(format == "md", "export format must be json, csv or md")
    lines = ["# Persona Lab experiment report", "", "Virtual choice experiment. Actual purchase prediction is unvalidated; local models showed option-order sensitivity in initial contrasts.", "", f"Experiment: {report['experiment_id']}", f"Backend: {report['backend_kind']} / {report['backend_id']}", f"Status: {report['status']} · {report['completed_jobs']}/{report['planned_jobs']} processed jobs · valid {report['valid_decisions']} · backend errors {report['backend_errors']}", "", f"Source: {report['source']['source_id']} @ {report['source']['version']}", f"Original source URL: {report['source']['url']}", f"Origin: {report['source']['origin']}", f"License: {report['source']['license_id']} ({report['source']['license_url']})", f"Attribution: {report['source'].get('attribution', 'Project-authored synthetic fixture')}", "", "| Product | Question | Choice | Count / completed |", "| --- | --- | --- | --- |"]
    escape = lambda value: str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    conditions=['## Product conditions','','| Product | Amount (minor units) | Currency | Billing | Price state |','| --- | --- | --- | --- | --- |']
    for product in report['products']:
        price=product['price'] or {}
        conditions.append('| '+' | '.join(escape(v) for v in [product['name'],price.get('amount_minor',''),price.get('currency',''),price.get('billing',''),product.get('price_state','legacy')])+' |')
    conditions+=['','## Choices',''];position=lines.index('| Product | Question | Choice | Count / completed |');lines[position:position]=conditions
    for group in report["groups"]:
        for choice, count in group["choice_counts"].items():
            lines.append(f"| {escape(group['product_id'])} | {escape(group['question_id'])} | {escape(choice)} | {count} / {group['completed']} |")
        if group["backend_errors"]:
            lines.append(f"| {escape(group['product_id'])} | {escape(group['question_id'])} | backend_error (separate) | {group['backend_errors']} / {group['processed']} processed |")
    lines += ["", "## Input consistency warnings", "", f"Purchase above explicit budget: {report['consistency_warnings']['purchase_above_explicit_budget']} decisions. Compared only within the same currency and billing period; original choices and denominators are preserved.", "", "## Paired purchase changes", ""]
    products = {product["id"]: product["name"] for product in report["products"]}
    for pair in report["comparisons"]:
        lines += [f"### {escape(products[pair['from_product']])} ({escape(pair['from_product'])}) → {escape(products[pair['to_product']])} ({escape(pair['to_product'])})", "", "| From choice | To choice | Paired judgments |", "| --- | --- | --- |"]
        lines += [f"| {escape(change['from'])} | {escape(change['to'])} | {change['count']} |" for change in pair["transitions"]]
        lines.append("")
    lines += ["## Explicit assumptions and scenario", "", "```json", json.dumps({"assumptions": report["assumptions"], "scenario": report["scenario"]}, ensure_ascii=False, indent=2), "```", "", "## Limits", ""]
    lines += [f"- {limit}" for limit in report["limitations"]]
    return "\n".join(lines) + "\n", "text/markdown; charset=utf-8"
