"""Vercel entry point: Vercel's Python runtime serves the ASGI app exported here.
vercel.json routes every path (pages, static files and the API) to this function."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app import app  # noqa: E402,F401
