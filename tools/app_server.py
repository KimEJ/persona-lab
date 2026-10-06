"""Absolute-path entrypoint for the project-owned demo process."""
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
from persona_lab.server import serve
serve(root, 8787)
