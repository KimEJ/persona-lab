import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .backends import FixtureBackend, LocalLLMBackend, JuliaBackend
from .contracts import ContractError
from .runner import run
from .reports import export


def main() -> int:
    parser = argparse.ArgumentParser(prog="persona_lab")
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("run", help="run/resume a local JSONL experiment")
    execute.add_argument("--personas", type=Path, default=Path("data/packs/synthetic-fixture.jsonl"))
    execute.add_argument("--source", type=Path, default=Path("data/packs/synthetic-fixture.json"))
    execute.add_argument("--experiment", type=Path, default=Path("examples/experiment.json"))
    execute.add_argument("--store", type=Path, default=Path(f"runs/cli-demo-{__version__}.sqlite"))
    execute.add_argument("--backend", choices=("mock", "local", "julia"), default="mock")
    execute.add_argument("--max-batches", type=int)
    execute.add_argument("--retry-errors", action="store_true")
    report = commands.add_parser("export")
    report.add_argument("--store", type=Path, required=True)
    report.add_argument("--format", choices=("json", "csv", "md"), default="json")
    report.add_argument("--output", type=Path)
    serve = commands.add_parser("serve", help="serve the loopback-only demo")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--root", type=Path, default=Path.cwd())
    commands.add_parser("fetch-sample", help="import the fixed public NVIDIA Viewer sample, at most 1MB per response")
    parquet = commands.add_parser('parquet-import', help='stream a pinned official shard or explicitly attributed local Parquet')
    inputs = parquet.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--shard'); inputs.add_argument('--path', type=Path); inputs.add_argument('--resume')
    parquet.add_argument('--source', type=Path); parquet.add_argument('--batch-size', type=int, default=256); parquet.add_argument('--max-batches', type=int)
    args = parser.parse_args()
    try:
        if args.command == 'parquet-import':
            import threading, signal
            from .parquet_import import create_import, run_import
            event = threading.Event(); previous = signal.signal(signal.SIGINT, lambda *_: event.set())
            try:
                if args.resume: identifier = args.resume
                elif args.shard: identifier = create_import(Path.cwd(), shard=args.shard, batch_size=args.batch_size)
                else:
                    if not args.source: raise ContractError('local Parquet requires an explicit --source metadata JSON')
                    identifier = create_import(Path.cwd(), local_path=args.path, source=json.loads(args.source.read_text()), batch_size=args.batch_size)
                print(json.dumps({'id': identifier, **run_import(Path.cwd(), identifier, cancelled=event.is_set, max_batches=args.max_batches)}, ensure_ascii=False))
            finally: signal.signal(signal.SIGINT, previous)
        elif args.command == "fetch-sample":
            from .importer import fetch_sample
            print(json.dumps(fetch_sample(Path.cwd()), ensure_ascii=False, indent=2))
        elif args.command == "serve":
            from .server import serve as serve_demo
            serve_demo(args.root.resolve(), args.port)
        elif args.command == "run":
            source = json.loads(args.source.read_text())
            spec = json.loads(args.experiment.read_text())
            backend = {"mock": FixtureBackend, "local": LocalLLMBackend, "julia": JuliaBackend}[args.backend]()
            print(json.dumps(run(args.personas, source, spec, args.store, backend, max_batches=args.max_batches, retry_errors=args.retry_errors), ensure_ascii=False))
        else:
            body, _ = export(args.store, args.format)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(body, encoding="utf-8")
            else:
                print(body, end="")
    except (ContractError, OSError, ValueError, ImportError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
