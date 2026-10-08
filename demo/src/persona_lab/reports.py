"""SQL aggregation and template export. No report model is used."""

import csv
import io
import json
import sqlite3
from pathlib import Path

from .contracts import require


def summarize(path: Path) -> dict:
    with sqlite3.connect(path) as db:
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
        if len(spec["products"]) >= 2:
            a, b = (p["id"] for p in spec["products"][:2])
            transitions = [{"from": old, "to": new, "count": count} for old, new, count in db.execute("""SELECT a.choice,b.choice,COUNT(*) FROM results a JOIN results b
              ON a.persona_id=b.persona_id AND a.repeat=b.repeat AND a.question_id=b.question_id
              WHERE a.domain='purchase' AND a.product_id=? AND b.product_id=? AND a.status!='backend_error' AND b.status!='backend_error'
              GROUP BY a.choice,b.choice ORDER BY a.choice,b.choice""", (a, b))]
        examples = [json.loads(payload) for (payload,) in db.execute("SELECT payload FROM results ORDER BY ordinal LIMIT 28")]
        observed = db.execute("SELECT COUNT(DISTINCT persona_id) FROM results").fetchone()[0]
        # Audit contradictions without changing or excluding the model's choices.
        products = {product["id"]: product for product in spec["products"]}
        budget_conflicts = 0
        warning_examples = []
        for persona_id, product_id, job_id in db.execute("SELECT uuid,product_id,job_id FROM results WHERE domain='purchase' AND choice='buy' AND status!='backend_error' ORDER BY ordinal"):
            price = products[product_id]["price"]
            budget = spec["assumptions"].get("fixture_budget_jpy_minor_by_uuid", {}).get(persona_id, spec["assumptions"].get("purchase_budget_jpy_minor"))
            if budget is not None and price["currency"] == "JPY" and price["billing"] == "one_time" and price["amount_minor"] > budget:
                budget_conflicts += 1
                if len(warning_examples) < 28:
                    warning_examples.append({"code": "purchase_above_explicit_budget", "job_id": job_id, "uuid": persona_id, "product_id": product_id, "amount_minor": price["amount_minor"], "budget_jpy_minor": budget})
        warnings = {"purchase_above_explicit_budget": budget_conflicts, "examples": warning_examples, "policy": "Preserve decisions and denominators; flag contradictions with the supplied one-time JPY budget. This is an input-consistency check, not behavior validation."}
    return {"schema_version": "0.1", "experiment_id": spec["experiment_id"], "status": status, "completed_jobs": cursor, "valid_decisions": sum(g["completed"] for g in groups.values()), "validity_semantics": "schema_contract_only_not_behavior_accuracy", "backend_errors": sum(g["backend_errors"] for g in groups.values()), "planned_jobs": total, "observed_personas": observed, "backend_id": backend_id, "backend_kind": backend_kind, "source": json.loads(source_json), "assumptions": spec["assumptions"], "scenario": spec["scenario"], "input_condition": "with_explicit_assumptions" if spec["assumptions"] or spec["scenario"]["events"] else "source_only", "consistency_warnings": warnings, "groups": list(groups.values()), "paired_purchase_transitions": transitions, "paired_transition_count": sum(t["count"] for t in transitions), "examples": examples, "error": error, "limitations": ["This is a virtual choice experiment; actual purchase prediction is unvalidated. Synthetic choice shares are not real probabilities or revenue forecasts.", "Initial contrasts showed option-order sensitivity and unknown outputs in both local models; a dedicated architecture does not establish behavior accuracy.", "Unknown decisions remain in the valid-decision denominator; backend errors are counted separately.", "Partial-run results may be biased toward earlier input records.", "Reason codes are backend output; evidence paths require semantic review.", "Independent variants use the same initial state; no longitudinal behavior is invented."]}


def export(path: Path, format: str) -> tuple[str, str]:
    report = summarize(path)
    if format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2), "application/json"
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["product_id", "question_id", "domain", "choice", "count", "completed_denominator", "synthetic_choice_share", "result_status", "group_backend_errors", "backend_kind", "source_id", "source_version", "run_budget_conflicts", "input_condition", "assumptions_json", "scenario_json", "license_id", "license_url", "source_url", "attribution"])
        for group in report["groups"]:
            for choice, count in list(group["choice_counts"].items()) + ([("", group["backend_errors"])] if group["backend_errors"] else []):
                values = [group["product_id"], group["question_id"], group["domain"], choice, count, group["completed"], group["choice_shares"].get(choice, ""), ("backend_error" if choice == "" else "insufficient_information" if choice == "unknown" else "ok"), group["backend_errors"], report["backend_kind"], report["source"]["source_id"], report["source"]["version"], report["consistency_warnings"]["purchase_above_explicit_budget"], report["input_condition"], json.dumps(report["assumptions"], ensure_ascii=False), json.dumps(report["scenario"], ensure_ascii=False), report["source"]["license_id"], report["source"]["license_url"], report["source"]["url"], report["source"].get("attribution", "Project-authored synthetic fixture")]
                # Spreadsheet formula injection protection for user-defined identifiers.
                writer.writerow(["'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value for value in values])
        return output.getvalue(), "text/csv; charset=utf-8"
    require(format == "md", "export format must be json, csv or md")
    lines = ["# Persona Lab experiment report", "", "Virtual choice experiment. Actual purchase prediction is unvalidated; local models showed option-order sensitivity in initial contrasts.", "", f"Experiment: {report['experiment_id']}", f"Backend: {report['backend_kind']} / {report['backend_id']}", f"Status: {report['status']} · {report['completed_jobs']}/{report['planned_jobs']} processed jobs · valid {report['valid_decisions']} · backend errors {report['backend_errors']}", "", f"Source: {report['source']['source_id']} @ {report['source']['version']}", f"Original source URL: {report['source']['url']}", f"Origin: {report['source']['origin']}", f"License: {report['source']['license_id']} ({report['source']['license_url']})", f"Attribution: {report['source'].get('attribution', 'Project-authored synthetic fixture')}", "", "| Product | Question | Choice | Count / completed |", "| --- | --- | --- | --- |"]
    escape = lambda value: str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    for group in report["groups"]:
        for choice, count in group["choice_counts"].items():
            lines.append(f"| {escape(group['product_id'])} | {escape(group['question_id'])} | {escape(choice)} | {count} / {group['completed']} |")
        if group["backend_errors"]:
            lines.append(f"| {escape(group['product_id'])} | {escape(group['question_id'])} | backend_error (separate) | {group['backend_errors']} / {group['processed']} processed |")
    lines += ["", "## Input consistency warnings", "", f"Purchase above explicit one-time JPY budget: {report['consistency_warnings']['purchase_above_explicit_budget']} decisions. Original choices and denominators are preserved.", "", "## Paired purchase changes", "", json.dumps(report["paired_purchase_transitions"], ensure_ascii=False), "", "## Explicit assumptions and scenario", "", "```json", json.dumps({"assumptions": report["assumptions"], "scenario": report["scenario"]}, ensure_ascii=False, indent=2), "```", "", "## Limits", ""]
    lines += [f"- {limit}" for limit in report["limitations"]]
    return "\n".join(lines) + "\n", "text/markdown; charset=utf-8"
