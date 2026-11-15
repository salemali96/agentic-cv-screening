"""Background jobs, access control, public demo mode and privacy endpoints."""
import time

from backend import config


def _wait(client, jid, timeout=60):
    t = time.time()
    while time.time() - t < timeout:
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_background_job_runs_and_streams_log(client, position):
    j = client.post(f"/api/positions/{position}/jobs", json={"kind": "resolve", "external_permitted": True}).json()
    assert j["status"] in ("queued", "running")
    again = client.post(f"/api/positions/{position}/jobs", json={"kind": "resolve"}).json()
    if again["status"] in ("queued", "running"):
        assert again["id"] == j["id"], "one job per position at a time"
    done = _wait(client, j["id"])
    assert done["status"] == "done" and done["result"]["mode"].startswith("Scripted")
    assert done["log_total"] > 3 and any("tool calls" in l["text"] for l in done["log"])
    assert client.get(f"/api/jobs/{j['id']}?since={done['log_total']}").json()["log"] == []
    assert client.get(f"/api/positions/{position}/jobs/current").json() is None


def test_background_job_counts_tokens(client, position, fake_model):
    fake_model.steps([[("get_shortlist_state", {})], [("finish", {"summary": "ok"})]])
    j = client.post(f"/api/positions/{position}/jobs", json={"kind": "resolve"}).json()
    done = _wait(client, j["id"])
    assert done["usage"]["calls"] == 2 and done["usage"]["input_tokens"] == 200


def test_extract_job(client):
    pid = client.post("/api/positions", json={}).json()["id"]
    client.post(f"/api/positions/{pid}/demo")
    done = _wait(client, client.post(f"/api/positions/{pid}/jobs", json={"kind": "extract"}).json()["id"])
    assert done["result"]["extracted"] == 14


def test_unknown_job_kind(client, position):
    assert client.post(f"/api/positions/{position}/jobs", json={"kind": "nope"}).status_code == 400


def test_password(client, monkeypatch):
    monkeypatch.setattr(config, "APP_PASSWORD", "s3cret")
    assert client.get("/api/settings").status_code == 401
    assert client.get("/api/settings", auth=("any", "wrong")).status_code == 401
    assert client.get("/api/settings", auth=("any", "s3cret")).status_code == 200
    assert client.get("/api/health").status_code == 200


def test_public_demo_mode(client, position, monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_DEMO", True)
    assert client.put("/api/settings", json={"provider": "offline"}).status_code == 403
    assert client.post(f"/api/positions/{position}/upload", files={"files": ("a.txt", b"x")}).status_code == 403
    assert client.delete(f"/api/positions/{position}").status_code == 403
    assert client.post("/api/positions", json={}).status_code == 403
    assert client.post(f"/api/positions/{position}/rank", json={}).status_code == 200, "reading and re-ranking still work"
    assert client.get("/api/settings").json()["llm"]["public_demo"] is True
    out = client.post(f"/api/positions/{position}/resolve", json={"external_permitted": True, "transport": "live"}).json()
    assert out["mode"].startswith("Scripted"), "no model calls in demo mode"
    assert client.get(f"/api/positions/{position}").json()["resolution"]["transport"] == "fixture", "no live lookups"


def test_export_and_delete_applicant(client, position):
    cid = client.get(f"/api/positions/{position}/candidates").json()[0]["id"]
    ex = client.get(f"/api/candidates/{cid}/export").json()
    assert ex["documents"] and ex["candidate"]["profile_base"]
    assert client.delete(f"/api/candidates/{cid}").json()["ok"]
    assert client.get(f"/api/candidates/{cid}/export").status_code == 404


def test_retention_purge(client):
    from backend import db
    pid = client.post("/api/positions", json={"demo": True}).json()["id"]
    with db._conn() as c:
        c.execute("UPDATE candidates SET created = 0 WHERE position_id = ?", (pid,))
    assert db.purge_inactive(30) >= 14
    assert client.get(f"/api/positions/{pid}/candidates").json() == []


def test_serverless_mode_runs_jobs_inline_and_seeds_fixed_demo(client, monkeypatch):
    from backend import db, pipeline
    monkeypatch.setattr(config, "SYNC_JOBS", True)
    pipeline.seed_demo_position()
    pipeline.seed_demo_position()  # idempotent
    cands = client.get("/api/positions/pos_demo/candidates").json()
    assert len(cands) == 14 and {c["id"] for c in cands} == {f"cand_A{i:02d}" for i in range(1, 15)}
    j = client.post("/api/positions/pos_demo/jobs", json={"kind": "resolve", "external_permitted": True}).json()
    assert j["status"] == "done" and j["result"] and j["log"], "finished inside the request, log included"
