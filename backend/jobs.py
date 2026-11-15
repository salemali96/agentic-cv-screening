"""Background jobs for long agent runs.

An agent run can take minutes (many model calls, waits for rate limits). Running it inside the HTTP request ties up
the request until it ends and fails behind any proxy with a request timeout. Here a run starts in a worker thread
and returns a job id at once; the browser polls GET /api/jobs/{id} and shows the log as it grows.

* One job per position at a time (a second start returns the running job instead of a duplicate).
* Every agent's log line is mirrored live into the job (ToolBox.note calls `emit`), including sub-agents started by the lead agent.
* Finished jobs are kept in memory for an hour; the run results themselves are saved on the position as before.
* Token usage of the model calls made during the job is counted (see llm.usage_scope).
"""
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import config, llm

KEEP_SECONDS = 3600
_pool = ThreadPoolExecutor(max_workers=int(__import__("os").environ.get("CVSCREEN_JOB_WORKERS", "2")), thread_name_prefix="job")
_jobs = {}
_lock = threading.Lock()
_local = threading.local()


class Job:
    def __init__(self, kind, pid, label):
        self.id = "job_" + uuid.uuid4().hex[:12]
        self.kind, self.pid, self.label = kind, pid, label
        self.status = "queued"  # queued | running | done | error
        self.log = []
        self.result = None
        self.error = None
        self.created = time.time()
        self.started = self.finished = None
        self.usage = None

    def public(self, since=0):
        return {"id": self.id, "kind": self.kind, "position_id": self.pid, "label": self.label, "status": self.status,
                "log": self.log[since:], "log_total": len(self.log), "error": self.error, "usage": self.usage,
                "elapsed": round((self.finished or time.time()) - (self.started or self.created), 1),
                "result": self.result if self.status == "done" else None}


def emit(kind, text):
    """Called by every agent's note(); a no-op outside a job."""
    job = getattr(_local, "job", None)
    if job is not None:
        job.log.append({"kind": kind, "text": text, "t": round(time.time() - (job.started or job.created), 1)})


def _gc():
    now = time.time()
    for jid in [j.id for j in _jobs.values() if j.finished and now - j.finished > KEEP_SECONDS]:
        _jobs.pop(jid, None)


def running_for(pid):
    with _lock:
        return next((j for j in _jobs.values() if j.pid == pid and j.status in ("queued", "running")), None)


def start(kind, pid, label, fn, *args, **kwargs):
    """Start fn(*args, **kwargs) in the background. Returns (job, created)."""
    with _lock:
        _gc()
        cur = next((j for j in _jobs.values() if j.pid == pid and j.status in ("queued", "running")), None)
        if cur:
            return cur, False
        job = Job(kind, pid, label)
        _jobs[job.id] = job

    def work():
        _local.job = job
        job.status, job.started = "running", time.time()
        try:
            with llm.usage_scope() as usage:
                job.result = fn(*args, **kwargs)
            job.status = "done"
        except llm.LLMError as ex:
            job.status, job.error = "error", str(ex)
        except Exception as ex:  # noqa: BLE001 - report, never kill the worker
            job.status, job.error = "error", f"{type(ex).__name__}: {str(ex)[:300]}"
            traceback.print_exc()
        finally:
            job.usage = dict(usage) if "usage" in locals() else None
            job.finished = time.time()
            _local.job = None

    if config.SYNC_JOBS:
        work()  # serverless: finish inside the request; the response already holds the result
    else:
        _pool.submit(work)
    return job, True


def get(jid):
    return _jobs.get(jid)
