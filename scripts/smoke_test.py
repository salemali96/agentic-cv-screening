"""End-to-end check without a browser or API key: demo applications -> extraction (offline) -> ranking
-> resolution process -> clarification reply. Run:  python scripts/smoke_test.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["CVSCREEN_DB"] = str(Path(tempfile.mkdtemp()) / "smoke.sqlite3")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import db, pipeline  # noqa: E402

db.init()
pipeline.seed_offline_extractions()
pid = pipeline.create_position()
ids = pipeline.load_demo(pid)
for cid in ids:
    pipeline.extract_candidate(cid)
ev = pipeline.evaluate(pid)
by = {e["name"]: e for e in ev["ranking"]}
assert by["Karim Saleh"]["eligibility"] == "ineligible", "PhD expected after start date must be 'not met'"
assert by["Omar Farouk"]["eligibility"] == "unresolved", "an unstated PhD must stay 'not established', not 'not met'"
assert by["Sara Mansour"]["hi"] > by["Sara Mansour"]["lo"], "undated leadership must give a score range"
assert by["Nadia Karim"]["conflicts"], "conflicting documents must be flagged"
assert by["Mona Fathy"]["shortlist_status"] == "robust_out"
r = pipeline.resolve(pid, external_permitted=True, transport="fixture")
by = {e["name"]: e for e in r["evaluation"]["ranking"]}
assert by["Youssef Adel"]["eligibility"] == "eligible", "verified publications should establish eligibility"
prov = db.provenance(by["Youssef Adel"]["candidate_id"])
assert any(p["outcome"] == "rejected" for p in prov), "a same-surname record by another person must be rejected"
omar = by["Omar Farouk"]["candidate_id"]
pipeline.record_reply(omar, {"op": "add", "section": "degrees", "item": {"level": "phd", "field": "Computer Science", "institution": "Delta University",
                                                                           "year": 2020, "status": "completed", "expected_year": None, "evidence": []}})
by = {e["name"]: e for e in pipeline.evaluate(pid)["ranking"]}
assert by["Omar Farouk"]["shortlist_status"] == "robust_in", "a confirmed PhD should make Omar a robust shortlist member"
print("All checks passed.")
for e in pipeline.evaluate(pid)["ranking"]:
    print(f"{e['rank']:>2}  {e['name']:<15} {e['lo']:5.1f}-{e['hi']:5.1f}  {e['eligibility']:<11} {e['shortlist_status']}")
