"""FastAPI application. Run with:  uvicorn backend.app:app --reload   (from the project folder)"""
import base64
import re
import secrets
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, db, evaluation, jobs, lead_agent, llm, pipeline, reply_agent, scoring, template, verification
from .config import FRONTEND_DIR


_ready = False


def _init():
    """Idempotent start-up. Runs from the lifespan hook, and from the first request on platforms that skip lifespan."""
    global _ready
    if _ready:
        return
    db.init()
    llm.load_saved()
    pipeline.seed_offline_extractions()
    if config.PUBLIC_DEMO:
        pipeline.seed_demo_position()
    if config.RETENTION_DAYS > 0:
        n = db.purge_inactive(config.RETENTION_DAYS)
        if n:
            print(f"Data retention: deleted {n} application(s) inactive for more than {config.RETENTION_DAYS} days.")
    _ready = True


@asynccontextmanager
async def _lifespan(_app):
    _init()
    yield


app = FastAPI(title="Evidence-aware CV screening", version="1.0", lifespan=_lifespan)


# Access control --------------------------------------------------------------------------------
# Writes blocked in public demo mode: anything that uploads personal data, changes settings or keys.
_DEMO_BLOCKED = [(m, re.compile(rx)) for m, rx in (
    ("POST", r"^/api/positions$"),                      # new positions (would exist on one serverless instance only)
    ("PUT", r"^/api/settings$"), ("DELETE", r"^/api/settings/providers/"),   # keys and providers
    ("POST", r"^/api/positions/[^/]+/upload$"),         # personal data
    ("POST", r"^/api/candidates/[^/]+/reply/propose$"),  # model calls
    ("DELETE", r"^/api/(positions|candidates)/"),
)]


@app.middleware("http")
async def _guard(request: Request, call_next):
    if not _ready:
        _init()
    if config.APP_PASSWORD and request.url.path != "/api/health":
        ok = False
        h = request.headers.get("authorization", "")
        if h.lower().startswith("basic "):
            try:
                pw = base64.b64decode(h[6:]).decode().split(":", 1)[1]
                ok = secrets.compare_digest(pw.encode(), config.APP_PASSWORD.encode())
            except Exception:  # noqa: BLE001
                ok = False
        if not ok:
            return Response("Password required", status_code=401, headers={"WWW-Authenticate": 'Basic realm="CV screening"'})
    if config.PUBLIC_DEMO:
        m, path = request.method, request.url.path
        if any(m == bm and rx.search(path) for bm, rx in _DEMO_BLOCKED):
            return JSONResponse(status_code=403, content={"detail": "Disabled in the public demo. Run the project locally to use your own files and AI model."})
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.get("/api/health")
def health():
    return {"ok": True}


def _pos(pid):
    p = db.get_position(pid)
    if not p:
        raise HTTPException(404, "Position not found")
    return p


@app.exception_handler(llm.LLMError)
def _llm_err(_, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# Settings ------------------------------------------------------------------------------------
@app.get("/api/settings")
def get_settings():
    return {"llm": llm.settings_public(), "sources": verification.SOURCES}


@app.put("/api/settings")
def put_settings(s: dict = Body(...)):
    return {"llm": llm.update_settings(s)}


@app.delete("/api/settings/providers/{provider_id}")
def delete_provider(provider_id: str):
    return {"llm": llm.delete_provider(provider_id)}


@app.get("/api/guide")
def guide():
    return {"parameters": template.parameter_guide(), "criteria": template.CRITERIA_INFO, "req_kinds": template.REQ_KINDS,
            "tiers": template.TIER_LABELS}


# Positions -----------------------------------------------------------------------------------
@app.get("/api/positions")
def positions():
    return [{"id": p["id"], "title": p["template"]["position"]["title"], "candidates": len(db.list_candidates(p["id"]))} for p in db.list_positions()]


@app.post("/api/positions")
def new_position(body: dict = Body(default={})):
    pid = pipeline.create_position(body.get("template"))
    if body.get("demo"):
        for cid in pipeline.load_demo(pid):
            try:
                pipeline.extract_candidate(cid)
            except Exception:  # noqa: BLE001
                pass
    return {"id": pid}


@app.get("/api/positions/{pid}")
def get_position(pid: str):
    p = _pos(pid)
    return {"id": pid, **p}


@app.put("/api/positions/{pid}/template")
def put_template(pid: str, t: dict = Body(...)):
    p = _pos(pid)
    p["template"] = template.validate_template(t)
    db.save_position(pid, p)
    return {"ok": True, "template": p["template"]}


@app.delete("/api/positions/{pid}")
def del_position(pid: str):
    db.delete_position(pid)
    return {"ok": True}


@app.post("/api/positions/{pid}/demo")
def demo(pid: str):
    _pos(pid)
    ids = pipeline.load_demo(pid)
    return {"added": len(ids), "ids": ids}


@app.post("/api/positions/{pid}/upload")
async def upload(pid: str, files: List[UploadFile] = File(...), paths: Optional[str] = Form(None)):
    _pos(pid)
    rel = [x.strip() for x in (paths or "").splitlines()] if paths else []
    data = []
    for i, f in enumerate(files):
        data.append((rel[i] if i < len(rel) and rel[i] else f.filename, await f.read()))
    existing = len(db.list_candidates(pid))
    out = pipeline.upload(pid, data)
    if existing + len(out) > 100:
        for o in out[100 - existing:]:
            db.delete_candidate(o["candidate_id"])
        out = out[:max(0, 100 - existing)]
    return {"applications": out}


@app.get("/api/positions/{pid}/candidates")
def candidates(pid: str):
    _pos(pid)
    out = []
    for c in db.list_candidates(pid):
        docs = db.documents(c["id"])
        out.append({"id": c["id"], "name": c.get("name"), "status": c.get("status"), "error": c.get("error"), "scenario": c.get("scenario"),
                    "documents": [{"type": d["doc_type"], "filename": d["filename"], "chars": len(d["text"])} for d in docs],
                    "upload_errors": c.get("upload_errors") or [], "replies": len(c.get("reply_patches") or []),
                    "quote_check": (c.get("extraction_meta") or {}).get("quote_check")})
    return out


@app.post("/api/candidates/{cid}/extract")
def extract(cid: str):
    if not db.get_candidate(cid):
        raise HTTPException(404, "Candidate not found")
    try:
        pipeline.extract_candidate(cid)
    except llm.LLMError:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))
    return pipeline.candidate_detail(cid)


@app.get("/api/candidates/{cid}")
def candidate(cid: str):
    d = pipeline.candidate_detail(cid)
    if not d:
        raise HTTPException(404, "Candidate not found")
    return d


@app.delete("/api/candidates/{cid}")
def del_candidate(cid: str):
    db.delete_candidate(cid)
    return {"ok": True}


@app.post("/api/candidates/{cid}/reply")
def reply(cid: str, body: dict = Body(...)):
    if not db.get_candidate(cid):
        raise HTTPException(404, "Candidate not found")
    for p in body.get("patches") or ([body["patch"]] if body.get("patch") else []):
        pipeline.record_reply(cid, p, body.get("note", ""))
    return pipeline.candidate_detail(cid)


@app.post("/api/candidates/{cid}/reply/propose")
def reply_propose(cid: str, body: dict = Body(...)):
    """Reply agent: read a pasted reply and propose updates. Nothing is applied."""
    if not db.get_candidate(cid):
        raise HTTPException(404, "Candidate not found")
    return reply_agent.propose(cid, body.get("text") or "")


@app.post("/api/candidates/{cid}/reply/apply")
def reply_apply(cid: str, body: dict = Body(...)):
    """Apply the proposals the committee approved; the rest are discarded."""
    if not db.get_candidate(cid):
        raise HTTPException(404, "Candidate not found")
    reply_agent.apply(cid, body.get("proposal_ids") or [])
    return pipeline.candidate_detail(cid)


@app.delete("/api/candidates/{cid}/replies")
def clear_replies(cid: str):
    c = db.get_candidate(cid)
    c["reply_patches"] = []
    db.save_candidate(cid, pipeline._pid_of(cid), c)
    return pipeline.candidate_detail(cid)


# Ranking, comparison, sensitivity, resolution ------------------------------------------------
@app.post("/api/positions/{pid}/rank")
def rank(pid: str, body: dict = Body(default={})):
    _pos(pid)
    return pipeline.evaluate(pid, body.get("template"))


@app.post("/api/positions/{pid}/compare")
def compare(pid: str, body: dict = Body(...)):
    _pos(pid)
    cands = [c for c in db.list_candidates(pid) if c.get("profile_base")]
    profiles = {c["id"]: pipeline.effective_profile(c) for c in cands}
    ta, tb = template.validate_template(body["template_a"]), template.validate_template(body["template_b"])
    return scoring.compare(profiles, ta, tb)


@app.post("/api/positions/{pid}/sensitivity")
def sensitivity(pid: str, body: dict = Body(default={})):
    p = _pos(pid)
    t = template.validate_template(body.get("template") or p["template"])
    cands = [c for c in db.list_candidates(pid) if c.get("profile_base")]
    profiles = {c["id"]: pipeline.effective_profile(c) for c in cands}
    if not profiles:
        raise HTTPException(400, "No extracted applications yet.")
    return scoring.sensitivity(profiles, t, draws=int(body.get("draws", 200)), spread=float(body.get("spread", 0.2)))


def _transport(body):
    return "fixture" if config.PUBLIC_DEMO else body.get("transport", "fixture")


@app.post("/api/positions/{pid}/resolve")
def resolve(pid: str, body: dict = Body(default={})):
    """Synchronous run (scripts, tests). The interface uses the background job below."""
    _pos(pid)
    return pipeline.resolve(pid, bool(body.get("external_permitted")), body.get("sources"), _transport(body), bool(body.get("resume")))


@app.post("/api/positions/{pid}/screen")
def screen(pid: str, body: dict = Body(default={})):
    """Lead agent, synchronous. The interface uses the background job below."""
    _pos(pid)
    return lead_agent.run(pid, bool(body.get("external_permitted")), body.get("sources"), _transport(body))


# Background jobs -------------------------------------------------------------------------------
def _extract_pending(pid, fresh=False):
    todo = [c for c in db.list_candidates(pid) if fresh or not c.get("profile_base")]
    ok, failed = 0, []
    for i, c in enumerate(todo, 1):
        jobs.emit("info", f"Extracting {c.get('name') or c['id']} ({i} of {len(todo)})…")
        try:
            pipeline.extract_candidate(c["id"], fresh=fresh)
            ok += 1
        except Exception as e:  # noqa: BLE001
            failed.append(c.get("name") or c["id"])
            jobs.emit("error", f"{c.get('name') or c['id']}: {str(e)[:200]}")
    jobs.emit("summary", f"Extracted {ok}" + (f"; failed: {', '.join(failed)}" if failed else "") + ".")
    return {"extracted": ok, "failed": failed}


@app.post("/api/positions/{pid}/jobs")
def start_job(pid: str, body: dict = Body(...)):
    """Start a long run in the background: kind = resolve | screen | extract. Poll GET /api/jobs/{id}."""
    _pos(pid)
    kind = body.get("kind")
    ext, src = bool(body.get("external_permitted")), body.get("sources")
    if kind == "resolve":
        job, _ = jobs.start(kind, pid, "Missing-information agent", pipeline.resolve, pid, ext, src, _transport(body), bool(body.get("resume")))
    elif kind == "screen":
        job, _ = jobs.start(kind, pid, "Lead agent (AI screening)", lead_agent.run, pid, ext, src, _transport(body))
    elif kind == "extract":
        job, _ = jobs.start(kind, pid, "Extraction", _extract_pending, pid, bool(body.get("fresh")))
    else:
        raise HTTPException(400, "kind must be resolve, screen or extract")
    return job.public()


@app.get("/api/jobs/{jid}")
def job_status(jid: str, since: int = 0):
    job = jobs.get(jid)
    if not job:
        raise HTTPException(404, "Job not found (finished jobs are kept for an hour).")
    return job.public(since)


@app.get("/api/positions/{pid}/jobs/current")
def current_job(pid: str):
    job = jobs.running_for(pid)
    return job.public() if job else None


# Evaluation ------------------------------------------------------------------------------------
@app.post("/api/evaluate")
def run_evaluation(body: dict = Body(default={})):
    """Evidence-aware screening vs baselines on the synthetic applications. With position_id, uses that position's
    extractions of the demo applications (so a real model's extraction is evaluated too)."""
    t = template.validate_template(body.get("template")) if body.get("template") else None
    extracted = None
    if body.get("position_id"):
        cands = [c for c in db.list_candidates(body["position_id"]) if c.get("demo_id") and c.get("profile_base")]
        real = [c for c in cands if (c.get("extraction_meta") or {}).get("provider") not in (None, "offline")]
        extracted = {c["demo_id"]: c["profile_base"] for c in real} or None
    res = evaluation.run(t, extracted)
    res["text"] = evaluation.report(res)
    return res


# Privacy ---------------------------------------------------------------------------------------
@app.get("/api/candidates/{cid}/export")
def export_candidate(cid: str):
    """Everything stored about one applicant (right of access)."""
    c = db.get_candidate(cid)
    if not c:
        raise HTTPException(404, "Candidate not found")
    return {"candidate": c, "documents": db.documents(cid), "provenance": db.provenance(cid), "audit": db.audit_log(cid)}


# Frontend ------------------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/{path:path}", include_in_schema=False)
def spa_fallback(path: str):
    """Any other page address loads the interface (it routes by #hash); unknown API paths stay a 404 that names the path."""
    if path.startswith("api/") or path.startswith("static/"):
        return JSONResponse(status_code=404, content={"detail": "Not Found", "path": "/" + path})
    return FileResponse(FRONTEND_DIR / "index.html")
