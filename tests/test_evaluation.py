"""Evaluation harness: the evidence-aware method against the baselines on the synthetic applications."""
from backend import evaluation


def test_evidence_aware_beats_baselines():
    r = evaluation.run()
    m = r["methods"]
    ea, ma, kw, cl = m["evidence_aware"], m["missing_absent"], m["keyword"], m["evidence_aware_clarified"]
    assert ea["wrongful_exclusions"] == [], "never excludes a truly eligible applicant"
    assert len(ma["wrongful_exclusions"]) > 0, "the missing = absent baseline does"
    assert ea["confident_decision_errors"] == [], "no errors among robust / ineligible decisions"
    assert ea["shortlist"]["precision"] >= ma["shortlist"]["precision"]
    assert ea["kendall_tau"] > kw["kendall_tau"]
    assert cl["shortlist"]["precision"] == 1.0, "asking only the flagged applicants recovers the true shortlist"
    assert ea["applicants_asked"] < r["applications"]
    assert ea["requirement_state_accuracy"] == 1.0


def test_report_and_endpoint(client):
    res = client.post("/api/evaluate", json={}).json()
    assert res["status"] == "ok" and "Evidence-aware" in res["text"]


def test_keyword_scores_rank_relevant_text_higher():
    s = evaluation.keyword_scores({"a": "machine learning teaching phd", "b": "cooking recipes"}, "machine learning phd")
    assert s["a"] > s["b"]
