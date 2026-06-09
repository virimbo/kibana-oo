"""Shared test fixtures. Backend modules import from the backend/ root,
so tests run with backend/ on sys.path (pytest rootdir = backend/)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
