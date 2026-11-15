"""Lead agent: runs the whole screening pipeline for a position and briefs the committee.

The model decides the order of work: which applications to extract, whether a weak extraction is worth
re-running, when to run the missing-information agent (a sub-agent, backend/agent.py), whether to test the
shortlist's robustness to the weights, and what to tell the committee.

Enforced in code, whatever the model asks for:
  * it cannot change scores, weights, requirements or the shortlist size; it can only read them;
  * external checks follow the committee's permission and approved sources for the position;
  * a re-extraction is kept only if its quote check is no worse than the previous one (else rolled back);
  * the briefing's table of candidates, scores and statuses is generated from the scoring engine,
    so the figures cannot be invented; the model writes only the narrative around it.

Without an AI model a scripted policy runs the same steps in a fixed order (labelled as such).
"""
import datetime as dt

from . import agent, db, jobs, llm, scoring, template
from .agent import ToolBox, ToolError, _drive_model, _obj

SYSTEM = """You are the lead screening assistant for an academic hiring committee. You run the screening pipeline for \
one position and then brief the committee. Rule-based scoring (which you cannot change) ranks the applicants; your job is \
to make sure the ranking rests on good evidence and to tell the committee what they need to know.
Suggested approach, adapt as needed:
1. get_pipeline_status. Extract any applications not yet extracted.
2. Look at extraction quality: where many quotes were not found in the documents, the facts may be unreliable. You may \
re-run extraction (fresh=true) for those; the system keeps the better result. Do not re-run good extractions.
3. Run the missing-information agent once to verify gaps and plan clarification requests (it does its own work).
4. Check whether the shortlist is robust to reasonable changes in the criterion weights.
5. write_briefing for the committee, then finish.
The briefing is read by academics, not engineers: plain language, short, specific (names, what is uncertain and why, \
what to do next). Never recommend hiring or rejecting anyone: the committee decides. Do not state numbers that you did \
not get from a tool; a table of scores is added automatically."""

TOOLS = [
    {"name": "get_pipeline_status",
     "description": "All applications for the position: extraction status, quote-check results (exact / close / not found), conflicts "
                    "between documents, and whether the missing-information process has run.",
     "input_schema": _obj({})},
    {"name": "extract_applications",
     "description": "Run AI extraction for the given applications. fresh=true re-runs an already extracted application instead of "
                    "using the cached result; the new result is kept only if its quote check is no worse. At most 2 fresh re-runs per application.",
     "input_schema": _obj({"candidate_ids": {"type": "array", "items": {"type": "string"}},
                           "fresh": {"type": "boolean"}}, ["candidate_ids"])},
    {"name": "run_missing_information_agent",
     "description": "Start the missing-information agent: it checks approved sources for gaps that could change eligibility or the "
                    "shortlist and plans clarification requests. Returns its summary and how the shortlist changed. At most 2 runs.",
     "input_schema": _obj({})},
    {"name": "get_shortlist_state",
     "description": "Current ranking: score range, eligibility, shortlist status, open gaps by priority, clarification planned.",
     "input_schema": _obj({})},
    {"name": "check_weight_sensitivity",
     "description": "Perturb the criterion weights at random (each by up to ±spread) and report how often each applicant is shortlisted, "
                    "and which single weight changes (halving or +50%) would change the shortlist.",
     "input_schema": _obj({"spread": {"type": "number", "description": "0.1 to 0.5; default 0.2"}})},
    {"name": "write_briefing",
     "description": "Write the briefing for the committee (replaces an earlier one). A table of all candidates with scores and statuses "
                    "is added automatically from the scoring engine.",
     "input_schema": _obj({"overview": {"type": "string", "description": "2-4 sentences: the state of the shortlist."},
                           "needs_attention": {"type": "array", "items": {"type": "string"},
                                               "description": "Specific points the committee should look at, one per entry."},
                           "robustness": {"type": "string", "description": "How much the shortlist depends on the weights / open information."},
                           "next_steps": {"type": "array", "items": {"type": "string"}}},
                          ["overview", "needs_attention", "robustness", "next_steps"])},
    {"name": "finish", "description": "End the run with a one-line summary.", "input_schema": _obj({"summary": {"type": "string"}}, ["summary"])},
]


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


class LeadRun(ToolBox):
    TOOLS = TOOLS
    MAX_CALLS = 60

    def __init__(self, pid, external_permitted, sources, transport):
        super().__init__()
        from . import pipeline
        self.pipeline, self.pid = pipeline, pid
        self.external, self.sources, self.transport = external_permitted, sources, transport
        self.fresh_runs, self.resolution_runs = {}, 0
        self.briefing = None
        self.sub_logs = []

    def _cands(self):
        return db.list_candidates(self.pid)

    def get_pipeline_status(self):
        pos = db.get_position(self.pid)
        rows = []
        for c in self._cands():
            qc = (c.get("extraction_meta") or {}).get("quote_check") or {}
            rows.append({"candidate_id": c["id"], "name": c.get("name"), "status": c.get("status"), "error": c.get("error"),
                         "documents": len(db.documents(c["id"])),
                         "quotes": qc or None, "quotes_not_found": qc.get("missing"),
                         "conflicts_between_documents": len((c.get("profile_base") or {}).get("conflicts", [])) if c.get("profile_base") else None})
        last = pos.get("last_resolution")
        return {"position": pos["template"]["position"]["title"], "applications": rows,
                "missing_information_process": {"last_run": last["at"], "mode": last.get("mode")} if last else "not run yet",
                "external_checks_permitted": self.external, "ai_model": llm.active_label()}

    def extract_applications(self, candidate_ids, fresh=False):
        if not candidate_ids:
            raise ToolError("Give at least one candidate_id.")
        out = []
        for cid in candidate_ids[:100]:
            c = db.get_candidate(cid)
            if not c or self.pipeline._pid_of(cid) != self.pid:
                out.append({"candidate_id": cid, "error": "unknown candidate"})
                continue
            again = bool(fresh) and bool(c.get("profile_base"))
            if again:
                if self.fresh_runs.get(cid, 0) >= 2:
                    out.append({"candidate_id": cid, "name": c.get("name"), "error": "re-run limit reached (2)"})
                    continue
                self.fresh_runs[cid] = self.fresh_runs.get(cid, 0) + 1
            before = c if c.get("profile_base") else None
            old_missing = ((before or {}).get("extraction_meta") or {}).get("quote_check", {}).get("missing")
            try:
                self.pipeline.extract_candidate(cid, fresh=again)
            except Exception as ex:  # noqa: BLE001
                if before:  # keep the previous extraction
                    db.save_candidate(cid, self.pid, {k: v for k, v in before.items() if k != "id"})
                out.append({"candidate_id": cid, "name": c.get("name"), "error": str(ex)[:200]})
                continue
            new = db.get_candidate(cid)
            qc = (new.get("extraction_meta") or {}).get("quote_check") or {}
            kept = "new"
            if before and old_missing is not None and qc.get("missing", 0) > old_missing:
                db.save_candidate(cid, self.pid, {k: v for k, v in before.items() if k != "id"})
                kept, qc = "previous (new result had more quotes not found)", before["extraction_meta"]["quote_check"]
            out.append({"candidate_id": cid, "name": new.get("name"), "quotes": qc, "kept": kept if again else None,
                        "cached": (new.get("extraction_meta") or {}).get("cached")})
        return {"results": out}

    def _short(self):
        return {e["name"]: e["shortlist_status"] for e in self.pipeline.evaluate(self.pid)["ranking"]}

    def run_missing_information_agent(self):
        if self.resolution_runs >= 2:
            raise ToolError("The missing-information agent has already run twice in this session.")
        if not any(c.get("profile_base") for c in self._cands()):
            raise ToolError("No application has been extracted yet.")
        self.resolution_runs += 1
        before = self._short()
        r = agent.run(self.pid, self.external, self.sources, self.transport)
        after = {e["name"]: e["shortlist_status"] for e in r["evaluation"]["ranking"]}
        self.sub_logs.append({"mode": r["mode"], "log": r["log"]})
        return {"mode": r["mode"], "summary": r["summary"],
                "status_changes": [{"name": n, "before": before.get(n), "after": s} for n, s in after.items() if before.get(n) != s],
                "result_line": r["log"][-1]["text"] if r["log"] else None,
                "errors": [l["text"] for l in r["log"] if l["kind"] == "error"][:5]}

    def get_shortlist_state(self):
        ev = self.pipeline.evaluate(self.pid)
        return {"shortlist_size": ev["k"], "candidates": [
            {"name": e["name"], "rank": e["rank"], "supported": e["lo"], "possible": e["hi"], "eligibility": e["eligibility"],
             "shortlist_status": e["shortlist_status"], "open_gaps_priority_1_to_3": sum(1 for g in e["gaps"] if g.get("priority", 9) <= 3),
             "clarification_planned": bool(e.get("clarification")), "conflicts": e.get("conflicts") and len(e["conflicts"])}
            for e in ev["ranking"]]}

    def check_weight_sensitivity(self, spread=0.2):
        try:
            spread = min(0.5, max(0.1, float(spread)))
        except (TypeError, ValueError):
            spread = 0.2
        cands = [c for c in self._cands() if c.get("profile_base")]
        if not cands:
            raise ToolError("No application has been extracted yet.")
        t = template.validate_template(db.get_position(self.pid)["template"])
        res = scoring.sensitivity({c["id"]: self.pipeline.effective_profile(c) for c in cands}, t, draws=200, spread=spread)
        return {"spread": spread, "draws": res["draws"], "average_overlap_with_current_shortlist": res["shortlist_jaccard_mean"],
                "shortlisted_how_often": [{"name": x["name"], "share_of_draws": x["freq"], "currently_shortlisted": x["in_base"]}
                                          for x in res["shortlist_frequency"] if x["freq"] > 0 or x["in_base"]],
                "single_weight_changes_that_alter_shortlist": [
                    {"criterion": r["criterion"], "change": f, "entered": r[k]["entered"], "left": r[k]["left"]}
                    for r in res["one_at_a_time"] for k, f in (("x0.5", "halved"), ("x1.5", "+50%")) if r[k]["entered"] or r[k]["left"]]}

    def write_briefing(self, overview, needs_attention, robustness, next_steps):
        self.briefing = {"overview": overview, "needs_attention": list(needs_attention or []), "robustness": robustness,
                         "next_steps": list(next_steps or [])}
        return {"ok": True, "note": "Saved. A table of candidates and scores from the scoring engine is attached automatically."}

    def _trace(self, name, args, res, err):
        if err:
            self.note("error", f"{name}: {res['error']}")
        elif name == "get_pipeline_status":
            n = len(res["applications"])
            todo = sum(1 for a in res["applications"] if a["status"] != "extracted")
            self.note("tool", f"Checked the pipeline: {n} applications, {todo} not yet extracted.")
        elif name == "extract_applications":
            for r in res["results"]:
                if r.get("error"):
                    self.note("error", f"Extraction of {r.get('name') or r['candidate_id']}: {r['error']}")
                else:
                    q = r["quotes"] or {}
                    self.note("tool", f"{'Re-extracted' if args.get('fresh') else 'Extracted'} {r['name']}: {q.get('exact', 0)} quotes found, "
                                      f"{q.get('approx', 0)} close, {q.get('missing', 0)} not found" + (f"; kept {r['kept']} result" if r.get("kept") else "") + ".")
        elif name == "run_missing_information_agent":
            ch = "; ".join(f"{c['name']}: {str(c['before']).replace('_', ' ')} → {c['after'].replace('_', ' ')}" for c in res["status_changes"]) or "no shortlist status changed"
            self.note("tool", f"Ran the missing-information agent ({res['mode']}): {ch}.")
        elif name == "get_shortlist_state":
            self.note("tool", "Looked at the current shortlist.")
        elif name == "check_weight_sensitivity":
            self.note("tool", f"Tested the shortlist against weight changes of ±{int(res['spread'] * 100)}%: average overlap "
                              f"{res['average_overlap_with_current_shortlist']:.0%} with the current shortlist.")
        elif name == "write_briefing":
            self.note("decision", "Wrote the committee briefing.")


def _table(pid):
    from . import pipeline
    ev = pipeline.evaluate(pid)
    return [{"rank": e["rank"], "candidate_id": e["candidate_id"], "name": e["name"], "supported": e["lo"], "possible": e["hi"], "eligibility": e["eligibility"],
             "shortlist_status": e["shortlist_status"], "clarification": bool(e.get("clarification"))} for e in ev["ranking"]]


def _scripted(r):
    st = r.get_pipeline_status()
    todo = [a["candidate_id"] for a in st["applications"] if a["status"] != "extracted"]
    if todo:
        r.call("extract_applications", {"candidate_ids": todo})
    if any(c.get("profile_base") for c in r._cands()):
        mi = r.call("run_missing_information_agent", {})[0]
        sens = r.call("check_weight_sensitivity", {"spread": 0.2})[0]
        sh = r.get_shortlist_state()["candidates"]
        unc = [c["name"] for c in sh if c["shortlist_status"] == "uncertain"]
        opn = [c["name"] for c in sh if c["eligibility"] == "unresolved" and c["shortlist_status"] != "robust_out"]
        r.call("write_briefing", {
            "overview": f"{sum(1 for c in sh if c['shortlist_status'] == 'robust_in')} applicants are shortlisted whatever the open information "
                        f"turns out to be; {len(unc)} are uncertain.",
            "needs_attention": ([f"Uncertain (range crosses the cut-off): {', '.join(unc)}."] if unc else [])
                               + ([f"Eligibility not established: {', '.join(opn)}."] if opn else []),
            "robustness": f"Under random weight changes of ±20%, the shortlist overlaps the current one by "
                          f"{sens.get('average_overlap_with_current_shortlist', 0):.0%} on average.",
            "next_steps": ["Send the drafted clarification requests (Missing information).", "Record replies as they arrive; the ranking updates."]})
    r.summary = "Scripted run (no AI model): extracted pending applications, ran the missing-information process, checked weight sensitivity, wrote a templated briefing."
    r.note("summary", r.summary)


def run(pid, external_permitted=False, sources=None, transport="fixture"):
    from . import verification
    sources = [s for s in (sources or list(verification.SOURCES)) if s in verification.SOURCES]
    pos = db.get_position(pid)
    pos["resolution"] = {"external_permitted": external_permitted, "sources": sources, "transport": transport}
    db.save_position(pid, pos)
    r = LeadRun(pid, external_permitted, sources, transport)
    try:
        chat = llm.tool_chat(SYSTEM, TOOLS, f"Screen the applications for this position. External checks permitted: "
                                            f"{'yes (' + ', '.join(sources) + ')' if external_permitted else 'no'}. Tool-call budget: {LeadRun.MAX_CALLS}.")
    except llm.LLMError as ex:
        chat = None
        r.note("error", f"Could not start the AI agent ({ex}); running the scripted workflow instead.")
    mode = f"AI agent: {llm.active_label()}" if chat else "Scripted workflow (no AI model)"
    r.log.insert(0, {"kind": "info", "text": mode + "."})
    jobs.emit("info", mode + ".")
    try:
        _drive_model(r, chat) if chat else _scripted(r)
    except llm.LLMError as ex:
        r.note("error", f"The lead agent stopped: {ex}. Work done before the error is kept.")
    except Exception as ex:  # noqa: BLE001
        r.note("error", f"The lead agent stopped on an unexpected error ({type(ex).__name__}: {str(ex)[:200]}).")
    if chat and not r.briefing:
        r.note("info", "The agent did not write a briefing; only the table below is available.")
    out = {"at": _now(), "mode": mode, "summary": r.summary, "log": r.log, "briefing": r.briefing,
           "table": _table(pid) if any(c.get("profile_base") for c in db.list_candidates(pid)) else [],
           "sub_agent_runs": len(r.sub_logs), "tool_calls": r.tool_calls}
    pos = db.get_position(pid)
    pos["last_screening"] = out
    db.save_position(pid, pos)
    return out
