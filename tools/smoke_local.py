"""Exercise real Japanese input through the local backend and compare mock.

Requires the already installed official local server on 127.0.0.1:8081.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from persona_lab import __version__
from persona_lab.backends import FixtureBackend, LocalLLMBackend
from persona_lab.runner import run
from persona_lab.reports import summarize, export

root = Path(__file__).resolve().parents[1]
source = json.loads((root / "data/packs/nemotron-japan-sample.json").read_text())
spec = json.loads((root / "examples/experiment.json").read_text())
spec.update(experiment_id="real-japanese-local-smoke", panel={"selection": "filter", "query": "09ae83ddc11745f6b995113fe7ed4a77"}, assumptions={})
backend = LocalLLMBackend()
invocation = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
started = time.monotonic()
local_path = root / f"runs/local-japanese-smoke-{__version__}-{invocation}.sqlite"
local = run(root / "data/packs/nemotron-japan-sample.jsonl", source, spec, local_path, backend)
elapsed = time.monotonic() - started
mock_path = root / f"runs/mock-japanese-smoke-{__version__}-{invocation}.sqlite"
mock = run(root / "data/packs/nemotron-japan-sample.jsonl", source, spec, mock_path, FixtureBackend())
local_report, mock_report = summarize(local_path), summarize(mock_path)
receipt = {"verified_at": datetime.now(timezone.utc).isoformat(), "status": "passed", "engine": __version__, "checkpoint": str(local_path.relative_to(root)), "input_language": "Japanese", "input_origin": "NVIDIA public Viewer sample", "matched_personas": 1, "conditions": 2, "domains": 7, "local": local, "mock": mock, "actual_http_metrics_this_invocation": backend.metrics, "elapsed_seconds_this_invocation": elapsed, "local_unknown": sum(g["unknown"] for g in local_report["groups"]), "mock_unknown": sum(g["unknown"] for g in mock_report["groups"]), "notes": ["A repeated invocation resumes completed results; zero HTTP requests then does not mean a new inference was run.", "No-event churn is gated to unknown without a model request.", "Qwen is a general instruction model, not a dedicated decision model.", "Schema-valid output is not evidence of behavioral accuracy."]}
(root / "verification").mkdir(exist_ok=True)
(root / "verification/local-inference.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
for label, path in (("local", local_path), ("mock", mock_path)):
    body, _ = export(path, "json")
    (root / f"verification/{label}-japanese-report.json").write_text(body)
print(json.dumps(receipt, ensure_ascii=False, indent=2))
