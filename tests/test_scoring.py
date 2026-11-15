"""The evidence-aware scoring rules on the demo applications (no AI model)."""
from conftest import ranking


def test_missing_is_not_absent(client, position):
    r = ranking(client, position)
    assert r["Omar Farouk"]["eligibility"] == "unresolved", "an unstated PhD stays 'not established', never 'not met'"
    assert r["Karim Saleh"]["eligibility"] == "ineligible", "PhD expected after the start date is evidence of 'not met'"
    assert r["Karim Saleh"]["shortlist_status"] == "ineligible"


def test_ranges_and_conflicts(client, position):
    r = ranking(client, position)
    assert r["Sara Mansour"]["hi"] > r["Sara Mansour"]["lo"], "undated leadership gives a score range"
    assert r["Nadia Karim"]["conflicts"], "conflicting documents are flagged"
    assert r["Layla Haddad"]["lo"] == r["Layla Haddad"]["hi"], "a complete application has no range"


def test_shortlist_status(client, position):
    r = ranking(client, position)
    assert r["Layla Haddad"]["shortlist_status"] == "robust_in"
    assert r["Mona Fathy"]["shortlist_status"] == "robust_out"
    assert r["Sara Mansour"]["shortlist_status"] == "uncertain"


def test_unpursued_gaps_are_not_asked(client, position):
    r = ranking(client, position)
    for name in ("Tarek Nabil", "Amr Hassan"):
        assert r[name]["gaps"] and all(g["priority"] == 4 for g in r[name]["gaps"])
        assert not r[name]["clarification"]


def test_weights_change_ranking(client, position):
    t = client.get(f"/api/positions/{position}").json()["template"]
    t["criteria"]["publications"]["weight"] = 50
    before = ranking(client, position)["Mona Fathy"]["rank"]
    after = next(e for e in client.post(f"/api/positions/{position}/rank", json={"template": t}).json()["ranking"] if e["name"] == "Mona Fathy")
    assert after["rank"] < before


def test_reply_updates_eligibility(client, position):
    omar = ranking(client, position)["Omar Farouk"]
    patch = {"op": "add", "section": "degrees", "item": {"level": "phd", "field": "Computer Science", "year": 2020, "status": "completed",
                                                         "evidence": [{"quote": "PhD in Computer Science, 2020", "doc": "clarification", "check": "external"}]}}
    d = client.post(f"/api/candidates/{omar['candidate_id']}/reply", json={"patch": patch, "note": "test"}).json()
    assert d["evaluation"]["eligibility"] == "eligible"


def test_scripted_resolution_uses_sources_safely(client, position):
    out = client.post(f"/api/positions/{position}/resolve", json={"external_permitted": True, "transport": "fixture"}).json()
    r = {e["name"]: e for e in out["evaluation"]["ranking"]}
    assert r["Youssef Adel"]["eligibility"] == "eligible", "verified publications establish eligibility"
    prov = client.get(f"/api/candidates/{r['Youssef Adel']['candidate_id']}").json()["provenance"]
    assert any(p["outcome"] == "rejected" for p in prov), "a same-surname record by another person is rejected"


def test_no_external_checks_when_not_permitted(client, position):
    out = client.post(f"/api/positions/{position}/resolve", json={"external_permitted": False}).json()
    assert all(e["external"] == 0 for e in out["evaluation"]["ranking"])
