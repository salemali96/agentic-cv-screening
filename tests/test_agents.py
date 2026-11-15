"""The three agents against a fake model: the model chooses tools, code enforces the guardrails."""
from conftest import ranking

from backend import db


def _pub_gap(e):
    return next(g for g in e["gaps"] if g["criterion"] == "publications" and g["type"] != "eligibility")


def test_missing_information_agent_guardrails(client, position, fake_model):
    r = ranking(client, position)
    y, mona = r["Youssef Adel"], r["Mona Fathy"]
    g4 = next(g for g in mona["gaps"] if g["priority"] == 4) if any(g["priority"] == 4 for g in mona["gaps"]) else None
    steps = [
        [("get_shortlist_state", {})],
        [("verify_gap", {"candidate_id": y["candidate_id"], "gap_id": _pub_gap(y)["id"], "sources": ["not_a_source"]})],  # refused
        [("verify_gap", {"candidate_id": y["candidate_id"], "gap_id": _pub_gap(y)["id"], "sources": ["crossref"]})],
        [("verify_gap", {"candidate_id": "cand_nope", "gap_id": "x"})],  # unknown candidate: refused
    ]
    if g4:
        steps.append([("plan_clarification", {"candidate_id": mona["candidate_id"], "gap_ids": [g4["id"]], "reason": "x"})])  # priority 4: refused
    steps.append([("finish", {"summary": "Checked Youssef."})])
    fake_model.steps(steps)
    out = client.post(f"/api/positions/{position}/resolve", json={"external_permitted": True, "sources": ["crossref", "orcid_works"]}).json()
    errors = [l["text"] for l in out["log"] if l["kind"] == "error"]
    assert out["mode"].startswith("AI agent: Fake") and out["summary"] == "Checked Youssef."
    assert any("not approved" in e for e in errors)
    assert any("Unknown candidate_id" in e for e in errors)
    assert len(db.get_candidate(y["candidate_id"]).get("external_patches") or []) > 0


def test_agent_cannot_use_sources_when_not_permitted(client, position, fake_model):
    y = ranking(client, position)["Youssef Adel"]
    fake_model.steps([[("verify_gap", {"candidate_id": y["candidate_id"], "gap_id": _pub_gap(y)["id"]})], [("finish", {"summary": "ok"})]])
    out = client.post(f"/api/positions/{position}/resolve", json={"external_permitted": False}).json()
    assert any("not permitted" in l["text"] for l in out["log"] if l["kind"] == "error")
    assert not db.get_candidate(y["candidate_id"]).get("external_patches")


def test_resume_after_overload_keeps_work(client, position, fake_model):
    y = ranking(client, position)["Youssef Adel"]
    first = [[("get_shortlist_state", {})], [("verify_gap", {"candidate_id": y["candidate_id"], "gap_id": _pub_gap(y)["id"]})]]
    fake_model.script = lambda body, n: first[n] if n < len(first) else ("http", 503, "This model is currently experiencing high demand.")
    out = client.post(f"/api/positions/{position}/resolve", json={"external_permitted": True}).json()
    filled = len(db.get_candidate(y["candidate_id"]).get("external_patches") or [])
    assert out["stopped"] and filled > 0
    assert any("high demand" in l["text"] for l in out["log"]), "the provider's own message is shown"

    fake_model.steps([[("get_shortlist_state", {})], [("finish", {"summary": "Continued."})]])
    out2 = client.post(f"/api/positions/{position}/resolve", json={"external_permitted": True, "resume": True}).json()
    assert not out2["stopped"] and out2["summary"] == "Continued."
    assert len(db.get_candidate(y["candidate_id"]).get("external_patches") or []) == filled
    assert "CONTINUES" in fake_model.requests[-1]["messages"][1]["content"]

    fake_model.steps([[("finish", {"summary": "Fresh."})]])
    client.post(f"/api/positions/{position}/resolve", json={"external_permitted": True})
    assert not db.get_candidate(y["candidate_id"]).get("external_patches"), "a new run starts over"


def test_reply_agent_needs_exact_quote_and_approval(client, position, fake_model):
    omar = ranking(client, position)["Omar Farouk"]
    g = next(g for g in omar["gaps"] if g["type"] == "eligibility")
    reply = "Dear committee, yes, I hold a PhD in Computer Science from Delta University, awarded in 2020. Best, Omar"
    fake_model.steps([
        [("get_open_items", {})],
        [("propose_answer", {"gap_id": g["id"], "answers": [{"field": "year", "value": "2021"}], "quote": "my PhD was awarded in 2021"}),
         ("propose_answer", {"gap_id": g["id"], "answers": [{"field": "year", "value": "1820"}], "quote": "awarded in 2020"}),
         ("propose_answer", {"gap_id": g["id"], "answers": [{"field": "salary", "value": "x"}], "quote": "awarded in 2020"})],
        [("propose_answer", {"gap_id": g["id"], "answers": [{"field": "field", "value": "Computer Science"}, {"field": "year", "value": "2020"}],
                             "quote": "I hold a PhD in Computer Science from Delta University, awarded in 2020"})],
        [("finish", {"summary": "Omar confirms his PhD."})],
    ])
    pend = client.post(f"/api/candidates/{omar['candidate_id']}/reply/propose", json={"text": reply}).json()
    assert len(pend["proposals"]) == 1, "invented quote, implausible year and unknown field are all refused"
    assert sum(l["kind"] == "error" for l in pend["log"]) == 3
    assert ranking(client, position)["Omar Farouk"]["eligibility"] == "unresolved", "nothing changes before approval"
    d = client.post(f"/api/candidates/{omar['candidate_id']}/reply/apply", json={"proposal_ids": [pend["proposals"][0]["id"]]}).json()
    assert d["evaluation"]["eligibility"] == "eligible"


def test_lead_agent_orchestrates_and_keeps_good_extractions(client, fake_model):
    pid = client.post("/api/positions", json={}).json()["id"]
    client.post(f"/api/positions/{pid}/demo")
    client.put("/api/settings", json={"provider": "offline"})
    for c in client.get(f"/api/positions/{pid}/candidates").json():
        client.post(f"/api/candidates/{c['id']}/extract")
    client.put("/api/settings", json={"provider": "fake"})
    ids = [c["id"] for c in client.get(f"/api/positions/{pid}/candidates").json()]
    lead = [
        [("get_pipeline_status", {})],
        [("extract_applications", {"candidate_ids": ids[:2], "fresh": True})],  # the fake model cannot extract: previous kept
        [("run_missing_information_agent", {})],
        [("check_weight_sensitivity", {"spread": 0.9})],
        [("write_briefing", {"overview": "Five are shortlisted.", "needs_attention": ["Omar's PhD"], "robustness": "Stable.", "next_steps": ["Send requests."]})],
        [("finish", {"summary": "Done."})],
    ]

    def router(body, n):
        if body["messages"][0]["content"].startswith("You are the missing-information agent"):
            return [[("get_shortlist_state", {})], [("finish", {"summary": "Sub-agent done."})]][n]
        if "tools" not in body:
            return ("http", 400, "no tools: extraction call")
        return lead[n]
    fake_model.script = router
    out = client.post(f"/api/positions/{pid}/screen", json={"external_permitted": True}).json()
    assert out["briefing"]["overview"] == "Five are shortlisted." and out["sub_agent_runs"] == 1
    assert all(c["status"] == "extracted" for c in client.get(f"/api/positions/{pid}/candidates").json())
    assert any("±50%" in l["text"] for l in out["log"]), "sensitivity spread is clamped to 0.5"
    assert len(out["table"]) == 14 and all("candidate_id" in r for r in out["table"]), "the table comes from the engine"


def test_offline_agents_fall_back_or_refuse(client, position):
    out = client.post(f"/api/positions/{position}/resolve", json={"external_permitted": True}).json()
    assert out["mode"].startswith("Scripted")
    omar = ranking(client, position)["Omar Farouk"]
    r = client.post(f"/api/candidates/{omar['candidate_id']}/reply/propose", json={"text": "hello"})
    assert r.status_code == 400
