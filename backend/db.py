"""SQLite storage. Documents, profiles and results are stored as JSON blobs; this is a demo-scale store."""
import json
import sqlite3
import threading
import time
import uuid

from .config import DB_PATH

_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS positions (id TEXT PRIMARY KEY, data TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS candidates (id TEXT PRIMARY KEY, position_id TEXT, data TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, candidate_id TEXT, doc_type TEXT, filename TEXT, text TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, data TEXT);
        CREATE TABLE IF NOT EXISTS provenance (id TEXT PRIMARY KEY, candidate_id TEXT, data TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT, step TEXT, data TEXT, created REAL);
        """)


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _put(table, id_, data, extra=None):
    cols = ["id", "data", "created"] + list((extra or {}).keys())
    vals = [id_, json.dumps(data, ensure_ascii=False), time.time()] + list((extra or {}).values())
    with _lock, _conn() as c:
        c.execute(f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)


def _get(table, id_):
    with _conn() as c:
        r = c.execute(f"SELECT data FROM {table} WHERE id=?", (id_,)).fetchone()
    return json.loads(r["data"]) if r else None


# Positions -------------------------------------------------------------------------------------
def save_position(pid, data):
    _put("positions", pid, data)


def get_position(pid):
    return _get("positions", pid)


def list_positions():
    with _conn() as c:
        rows = c.execute("SELECT id, data FROM positions ORDER BY created").fetchall()
    return [{"id": r["id"], **json.loads(r["data"])} for r in rows]


def delete_position(pid):
    with _lock, _conn() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM candidates WHERE position_id=?", (pid,))]
        for cid in ids:
            c.execute("DELETE FROM documents WHERE candidate_id=?", (cid,))
            c.execute("DELETE FROM provenance WHERE candidate_id=?", (cid,))
            c.execute("DELETE FROM audit WHERE candidate_id=?", (cid,))
        c.execute("DELETE FROM candidates WHERE position_id=?", (pid,))
        c.execute("DELETE FROM positions WHERE id=?", (pid,))


# Candidates ------------------------------------------------------------------------------------
def save_candidate(cid, pid, data):
    _put("candidates", cid, data, {"position_id": pid})


def get_candidate(cid):
    return _get("candidates", cid)


def list_candidates(pid):
    with _conn() as c:
        rows = c.execute("SELECT id, data FROM candidates WHERE position_id=? ORDER BY created", (pid,)).fetchall()
    return [{"id": r["id"], **json.loads(r["data"])} for r in rows]


def delete_candidate(cid):
    with _lock, _conn() as c:
        for t in ("documents", "provenance", "audit"):
            c.execute(f"DELETE FROM {t} WHERE candidate_id=?", (cid,))
        c.execute("DELETE FROM candidates WHERE id=?", (cid,))


# Documents -------------------------------------------------------------------------------------
def add_document(cid, doc_type, filename, text):
    did = new_id("doc")
    with _lock, _conn() as c:
        c.execute("INSERT INTO documents (id, candidate_id, doc_type, filename, text, created) VALUES (?,?,?,?,?,?)",
                  (did, cid, doc_type, filename, text, time.time()))
    return did


def documents(cid):
    with _conn() as c:
        rows = c.execute("SELECT id, doc_type, filename, text FROM documents WHERE candidate_id=? ORDER BY created", (cid,)).fetchall()
    return [dict(r) for r in rows]


def delete_document(did):
    with _lock, _conn() as c:
        c.execute("DELETE FROM documents WHERE id=?", (did,))


# Cache, provenance, audit ----------------------------------------------------------------------
def cache_get(key):
    with _conn() as c:
        r = c.execute("SELECT data FROM cache WHERE key=?", (key,)).fetchone()
    return json.loads(r["data"]) if r else None


def cache_put(key, data):
    with _lock, _conn() as c:
        c.execute("INSERT OR REPLACE INTO cache (key, data) VALUES (?, ?)", (key, json.dumps(data, ensure_ascii=False)))


def add_provenance(cid, rec):
    rec.setdefault("id", new_id("prov"))
    _put("provenance", rec["id"], rec, {"candidate_id": cid})
    return rec


def provenance(cid):
    with _conn() as c:
        rows = c.execute("SELECT data FROM provenance WHERE candidate_id=? ORDER BY created", (cid,)).fetchall()
    return [json.loads(r["data"]) for r in rows]


def clear_provenance(cid):
    with _lock, _conn() as c:
        c.execute("DELETE FROM provenance WHERE candidate_id=?", (cid,))


def audit(cid, step, data):
    with _lock, _conn() as c:
        c.execute("INSERT INTO audit (candidate_id, step, data, created) VALUES (?,?,?,?)",
                  (cid, step, json.dumps(data, ensure_ascii=False), time.time()))


def audit_log(cid):
    with _conn() as c:
        rows = c.execute("SELECT step, data, created FROM audit WHERE candidate_id=? ORDER BY id", (cid,)).fetchall()
    return [{"step": r["step"], "data": json.loads(r["data"]), "at": r["created"]} for r in rows]


# Data retention --------------------------------------------------------------------------------
def purge_inactive(days):
    """Delete applications not changed for `days` days (documents, provenance and audit included). Returns the count."""
    cutoff = time.time() - days * 86400
    with _conn() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM candidates WHERE created < ?", (cutoff,))]
    for cid in ids:
        delete_candidate(cid)
    return len(ids)
