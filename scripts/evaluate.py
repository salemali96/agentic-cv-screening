"""Evaluate the evidence-aware screening against two baselines on the 14 synthetic applications.

    python scripts/evaluate.py            # table in the terminal
    python scripts/evaluate.py --json     # full results as JSON
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import evaluation  # noqa: E402

res = evaluation.run()
print(json.dumps(res, indent=2, ensure_ascii=False) if "--json" in sys.argv else evaluation.report(res))
