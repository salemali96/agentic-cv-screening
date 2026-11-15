"""Orchestration: upload -> extraction -> evaluation -> resolution of missing information -> clarification."""
import datetime as dt
import hashlib
import json

from . import clarify, db, extraction, patches, scoring, template, verification
from .config import SYNTHETIC_DIR
from .parsing import DOC_LABELS, clean, doc_type, extract_text, group_files


# ------------------------------------------------------------------------------------------------
# Positions and applications
# ------------------------------------------------------------------------------------------------
def create_position(tpl=None, pid=None):
    pid = pid or db.new_id("pos")
    db.save_position(pid, {"template": template.validate_template(tpl or template.default_template()),
                           "resolution": {"external_permitted": False, "sources": list(verification.SOURCES), "transport": "fixture"}})
    return pid


def docs_key(docs):
    blob = "\n".join(f"{d['doc_type']}:{d['text'].strip()}" for d in sorted(docs, key=lambda d: d["doc_type"]))
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def seed_offline_extractions():
    """Store gold extractions of the synthetic applications so offline mode can 'extract' them."""
    if not SYNTHETIC_DIR.exists():
        return 0
    n = 0
    for d in sorted(SYNTHETIC_DIR.iterdir()):
        if not d.is_dir() or not (d / "gold_profile.json").exists():
            continue
        docs = [{"doc_type": f.stem, "filename": f.name, "text": clean(f.read_text(encoding="utf-8"))} for f in d.glob("*.txt")]
        db.cache_put(f"offline:extract:{docs_key(docs)}", json.loads((d / "gold_profile.json").read_text(encoding="utf-8")))
        n += 1
    return n


def add_application(pid, name, files, cid=None):
    """files: [(filename, bytes)]"""
    cid = cid or db.new_id("cand")
    errors = []
    db.save_candidate(cid, pid, {"name": name, "status": "uploaded", "external_patches": [], "reply_patches": []})
    for fn, data in files:
        try:
            text = clean(extract_text(fn, data))
            if len(text) < 40:
                errors.append(f"{fn}: almost no text found (scanned PDF?)")
            db.add_document(cid, doc_type(fn), fn, text)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{fn}: {e}")
    c = db.get_candidate(cid)
    c["upload_errors"] = errors
    db.save_candidate(cid, pid, c)
    return cid, errors


def upload(pid, files):
    groups = group_files(files)
    out = []
    for key, fl in groups.items():
        cid, errs = add_application(pid, key.title(), fl)
        out.append({"candidate_id": cid, "name": key.title(), "files": [f for f, _ in fl], "errors": errs})
    return out


def load_demo(pid, fixed_ids=False):
    manifest = json.loads((SYNTHETIC_DIR / "manifest.json").read_text())
    out = []
    for m in manifest:
        d = SYNTHETIC_DIR / m["id"]
        files = [(f.name, f.read_bytes()) for f in sorted(d.glob("*.txt"))]
        cid, _ = add_application(pid, m["name"], files, cid=f"cand_{m['id']}" if fixed_ids else None)
        c = db.get_candidate(cid)
        c["demo_id"], c["scenario"] = m["id"], m["scenario"]
        db.save_candidate(cid, pid, c)
        out.append(cid)
    return out


# ------------------------------------------------------------------------------------------------
# Extraction
# ------------------------------------------------------------------------------------------------
def extract_candidate(cid, fresh=False):
    c = db.get_candidate(cid)
    pid = _pid_of(cid)
    docs = db.documents(cid)
    if not docs:
        raise ValueError("This application has no readable documents.")
    c["status"] = "extracting"
    db.save_candidate(cid, pid, c)
    try:
        prof, meta = extraction.extract(docs, offline_key=docs_key(docs), fresh=fresh)
    except Exception as e:
        c["status"], c["error"] = "error", str(e)
        db.save_candidate(cid, pid, c)
        raise
    c.update({"status": "extracted", "error": None, "profile_base": prof, "extraction_meta": meta,
              "extracted_at": _now(), "external_patches": [], "name": prof.get("name") or c.get("name")})
    db.save_candidate(cid, pid, c)
    db.clear_provenance(cid)
    db.audit(cid, "extraction", {"documents": [{"type": d["doc_type"], "label": DOC_LABELS.get(d["doc_type"], d["doc_type"]), "file": d["filename"]} for d in docs],
                                 "quote_check": meta.get("quote_check"), "conflicts": len(prof.get("conflicts", [])), "provider": meta.get("provider")})
    return c


def _pid_of(cid):
    with db._conn() as conn:
        r = conn.execute("SELECT position_id FROM candidates WHERE id=?", (cid,)).fetchone()
    return r["position_id"] if r else None


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def effective_profile(c):
    return patches.apply(c["profile_base"], (c.get("external_patches") or []) + (c.get("reply_patches") or []))


# ------------------------------------------------------------------------------------------------
# Evaluation
# ------------------------------------------------------------------------------------------------
def evaluate(pid, tpl=None):
    pos = db.get_position(pid)
    t = template.validate_template(tpl or pos["template"])
    cands = [c for c in db.list_candidates(pid) if c.get("profile_base")]
    profiles = {c["id"]: effective_profile(c) for c in cands}
    ranked = scoring.run(profiles, t) if profiles else []
    meta = {c["id"]: c for c in cands}
    for e in ranked:
        c = meta[e["candidate_id"]]
        e["scenario"] = c.get("scenario")
        e["replies"] = len(c.get("reply_patches") or [])
        e["external"] = len(c.get("external_patches") or [])
        plan = c.get("agent_clarification")
        if plan is not None:  # the agent chose what to ask; gaps closed since then drop out
            ids = set(plan.get("gap_ids") or [])
            chosen = [g for g in e["gaps"] if g["id"] in ids]
            e["clarification"] = clarify.build_requests({**e, "gaps": chosen}, t["position"]["title"]) if chosen else None
            e["clarification_plan"] = {"by": "agent", "reason": plan.get("reason")}
        else:
            e["clarification"] = clarify.build_requests(e, t["position"]["title"])
    return {"template": t, "ranking": ranked, "k": t["shortlist_size"],
            "pending": [{"id": c["id"], "name": c.get("name"), "status": c.get("status"), "error": c.get("error")}
                        for c in db.list_candidates(pid) if not c.get("profile_base")]}


# ------------------------------------------------------------------------------------------------
# Resolution of missing information: an LLM agent decides what to check and what to ask (backend/agent.py)
# ------------------------------------------------------------------------------------------------
def resolve(pid, external_permitted=False, sources=None, transport="fixture", resume=False):
    from . import agent
    return agent.run(pid, external_permitted, sources, transport, resume)


def record_reply(cid, patch, note=""):
    c = db.get_candidate(cid)
    pid = _pid_of(cid)
    patch = dict(patch)
    patch["evidence"] = {"quote": f"Clarification reply ({dt.date.today().isoformat()}): {note or json.dumps(patch.get('value', patch.get('item')), ensure_ascii=False)}",
                         "doc": "clarification", "check": "external", "source": "clarification"}
    if patch.get("op") == "add" and patch.get("item"):
        patch["item"].setdefault("evidence", [])
    c.setdefault("reply_patches", []).append(patch)
    db.save_candidate(cid, pid, c)
    db.audit(cid, "clarification_reply", {"patch": patch})
    return c


def candidate_detail(cid):
    c = db.get_candidate(cid)
    if not c:
        return None
    pid = _pid_of(cid)
    out = {"id": cid, "position_id": pid, **{k: v for k, v in c.items() if k not in ("profile_base",)},
           "documents": [{"id": d["id"], "type": d["doc_type"], "label": DOC_LABELS.get(d["doc_type"], d["doc_type"]), "filename": d["filename"], "text": d["text"]}
                         for d in db.documents(cid)],
           "provenance": db.provenance(cid), "audit": db.audit_log(cid)}
    if c.get("profile_base"):
        out["profile_base"] = c["profile_base"]
        out["profile"] = effective_profile(c)
        ev = evaluate(pid)
        out["evaluation"] = next((e for e in ev["ranking"] if e["candidate_id"] == cid), None)
        out["k"] = ev["k"]
    return out


DEMO_POSITION_ID = "pos_demo"


def seed_demo_position():
    """Public demo: the same example position on every server instance (fixed ids), so links work on serverless
    hosting where each instance starts from an empty database."""
    if db.get_position(DEMO_POSITION_ID):
        return
    create_position(pid=DEMO_POSITION_ID)
    for cid in load_demo(DEMO_POSITION_ID, fixed_ids=True):
        extract_candidate(cid)
