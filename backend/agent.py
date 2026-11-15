"""Resolution agent for missing information.

An LLM (any provider configured in backend/llm.py: Claude, Gemini, or any OpenAI-compatible endpoint) runs in a tool-use loop. It decides which applicants and which gaps to
work on, which approved source to try, whether to retry a failed lookup with a different query, and
what to ask each applicant. The tools below are its only way to act.

What the model can NOT do (enforced here, in code, whatever it asks for):
  * change a score: scoring stays in backend/scoring.py and is re-run after every change;
  * use a source the committee has not approved, or any source when external checks are not permitted;
  * accept a record that fails the identity check (ORCID iD, or full name plus a shared affiliation);
  * overwrite a value from the documents: sources only fill silent fields, disagreements become conflicts;
  * ask an applicant about a gap that cannot change eligibility or the shortlist (priority 4).

With no API key (provider 'offline') a scripted policy drives the same tools in a fixed order, so the
demo and tests run without network access. That mode is a workflow, not an agent, and is labelled so.
"""
import datetime as dt
import json
from collections import Counter

from . import clarify, db, jobs, llm, verification

MAX_TOOL_CALLS = 120
MAX_MODEL_TURNS = 60

SYSTEM = """You are the missing-information agent for an academic hiring committee. Applications have already been \
extracted and scored by a deterministic engine. Each candidate has a score range (supported score -> possible score) \
and a shortlist status: robust_in, robust_out, uncertain or ineligible. Each open item ("gap") has a priority:
  1 = eligibility of a shortlist contender, 2 = could change the shortlist on its own,
  3 = could change the shortlist together with other gaps, 4 = cannot change the outcome.

Your goal: make the shortlist as reliable as possible with the least burden on applicants.
- Work on gaps that can change eligibility or the shortlist. Leave priority-4 gaps alone.
- Where external checks are permitted, try approved sources first; an applicant should only be asked about what \
the sources could not settle. If a default lookup finds nothing, you may retry once or twice with search_publication \
using a different query (e.g. a shorter or corrected title), then accept a record only if it is clearly the same work.
- Re-check the shortlist after changes: a filled value can make other gaps irrelevant or make new ones matter.
- For every candidate with gaps of priority 1-3 that are still open at the end, call plan_clarification with the \
gaps worth asking about (an empty list if, on reflection, none are). Ask for as little as possible.
- You cannot change scores, overwrite documented values, or use records whose identity check fails; the tools enforce \
this. Never treat missing information as a "no".
- Be economical with tool calls. When done, call finish with a short summary for the committee: what you checked, \
what changed, and what remains open and why."""


def _obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


TOOLS = [
    {"name": "get_shortlist_state",
     "description": "Current ranking of all extracted applicants: score range, eligibility, shortlist status, number of open gaps by priority, "
                    "and whether a clarification has been planned. Call at the start and after changes to see their effect.",
     "input_schema": _obj({})},
    {"name": "get_candidate_gaps",
     "description": "Open gaps for one applicant with id, type, label, detail, priority and its reason, impact on the shortlist, which approved "
                    "sources could settle it, and relevant profile facts (ORCID iD present, listed publications).",
     "input_schema": _obj({"candidate_id": {"type": "string"},
                           "include_not_pursued": {"type": "boolean", "description": "Also list priority-4 gaps. Default false."}}, ["candidate_id"])},
    {"name": "verify_gap",
     "description": "Run the standard external check for one gap against approved sources (publication details via Crossref/OpenAlex/ORCID works; "
                    "doctoral degree via ORCID education; role dates via ORCID employment). Logs every record with provenance, applies values only "
                    "where documents are silent and the identity check passes, and returns the outcome plus the applicant's updated score and status.",
     "input_schema": _obj({"candidate_id": {"type": "string"}, "gap_id": {"type": "string"},
                           "sources": {"type": "array", "items": {"type": "string"},
                                       "description": "Subset of approved sources to query. Omit to use all approved sources."}},
                          ["candidate_id", "gap_id"])},
    {"name": "search_publication",
     "description": "Search Crossref or OpenAlex with your own query for one listed publication, e.g. after verify_gap found nothing. Returns candidate "
                    "records with title similarity and identity-check result, but applies nothing; use accept_publication_record to use one.",
     "input_schema": _obj({"candidate_id": {"type": "string"},
                           "publication_index": {"type": "integer", "description": "Index in the applicant's publication list (see get_candidate_gaps)."},
                           "query_title": {"type": "string"},
                           "author_surname": {"type": "string", "description": "Defaults to the applicant's surname."},
                           "source": {"type": "string", "enum": ["crossref", "openalex"]}},
                          ["candidate_id", "publication_index", "query_title", "source"])},
    {"name": "accept_publication_record",
     "description": "Use a record returned by search_publication to settle a publication gap. Rejected unless the title closely matches the listed "
                    "publication and the identity check passes. Fills only missing fields; disagreements become conflicts.",
     "input_schema": _obj({"candidate_id": {"type": "string"}, "gap_id": {"type": "string"}, "record_id": {"type": "string"}},
                          ["candidate_id", "gap_id", "record_id"])},
    {"name": "spot_check_orcid",
     "description": "For an applicant with an ORCID iD: compare listed publication years with their ORCID record and flag disagreements as conflicts. "
                    "Useful for applicants who are (or are close to being) shortlisted.",
     "input_schema": _obj({"candidate_id": {"type": "string"}}, ["candidate_id"])},
    {"name": "plan_clarification",
     "description": "Decide what to ask one applicant. Give the gap ids worth asking about (priority 1-3 only), or an empty list to ask nothing. "
                    "Returns the drafted message. Calling again for the same applicant replaces the earlier plan.",
     "input_schema": _obj({"candidate_id": {"type": "string"}, "gap_ids": {"type": "array", "items": {"type": "string"}},
                           "reason": {"type": "string", "description": "One sentence for the committee on why these questions (or none)."}},
                          ["candidate_id", "gap_ids", "reason"])},
    {"name": "finish",
     "description": "End the run with a short summary for the committee.",
     "input_schema": _obj({"summary": {"type": "string"}}, ["summary"])},
]


class ToolError(Exception):
    pass


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


class ToolBox:
    """Shared base for all agents: tool dispatch, a tool-call budget and a readable log.
    Subclasses set TOOLS (neutral tool definitions) and implement one method per tool name."""
    TOOLS = []
    MAX_CALLS = MAX_TOOL_CALLS

    def __init__(self):
        self.log = []
        self.summary = None
        self.tool_calls = 0

    def note(self, kind, text):
        self.log.append({"kind": kind, "text": text})
        jobs.emit(kind, text)  # live progress when running as a background job

    def call(self, name, args):
        """Execute one tool call. Returns (result_dict, is_error)."""
        self.tool_calls += 1
        fn = getattr(self, name, None) if name in {t["name"] for t in self.TOOLS} else None
        try:
            if not fn:
                raise ToolError(f"Unknown tool '{name}'.")
            if self.tool_calls > self.MAX_CALLS:
                raise ToolError("Tool-call budget for this run is used up. Call finish now.")
            res, err = fn(**(args or {})), False
        except ToolError as ex:
            res, err = {"error": str(ex)}, True
        except TypeError as ex:
            res, err = {"error": f"Invalid arguments: {ex}"}, True
        self._trace(name, args or {}, res, err)
        return res, err

    def _trace(self, name, args, res, err):
        if err:
            self.note("error", f"{name}: {res['error']}")

    def finish(self, summary):
        self.summary = summary
        self.note("summary", summary)
        return {"ok": True}


class Run(ToolBox):
    TOOLS = TOOLS

    def __init__(self, pid, external_permitted, sources, transport):
        super().__init__()
        from . import pipeline  # late import: pipeline imports this module
        self.pipeline = pipeline
        self.pid = pid
        self.external = external_permitted
        self.sources = sources
        self.transport = transport
        self.tr = verification.Transport(transport)
        self.counts = Counter()
        self.attempted = {}
        self.records = {}

    # -- helpers -----------------------------------------------------------------------------
    def _ranking(self):
        return self.pipeline.evaluate(self.pid)

    def _entry(self, cid):
        ev = self._ranking()
        e = next((x for x in ev["ranking"] if x["candidate_id"] == cid), None)
        if not e:
            raise ToolError(f"Unknown candidate_id '{cid}'. Use get_shortlist_state for valid ids.")
        return e, ev["k"]

    def _cand(self, cid):
        c = db.get_candidate(cid)
        if not c or self.pipeline._pid_of(cid) != self.pid or not c.get("profile_base"):
            raise ToolError(f"Unknown candidate_id '{cid}'.")
        c["id"] = cid  # stored records do not always carry their own id
        return c

    def _gap(self, e, gap_id):
        g = next((g for g in e["gaps"] if g["id"] == gap_id), None)
        if not g:
            raise ToolError(f"Gap '{gap_id}' is not open for this applicant (already settled, or wrong id). Call get_candidate_gaps.")
        return g

    def _need_external(self, srcs=None):
        if not self.external:
            raise ToolError("External verification is not permitted for this position. Only plan_clarification is available.")
        bad = [s for s in (srcs or []) if s not in self.sources]
        if bad:
            raise ToolError(f"Source(s) {bad} are not approved. Approved: {self.sources}.")

    @staticmethod
    def _status(e):
        return {"supported": e["lo"], "possible": e["hi"], "eligibility": e["eligibility"], "shortlist_status": e["shortlist_status"], "rank": e["rank"]}

    def _store(self, c, provs, pts):
        out_p = []
        for pr in provs:
            pr = db.add_provenance(c["id"], pr)
            self.counts["records"] += 1
            self.counts["rejected"] += pr["outcome"] in ("rejected", "needs_human_check")
            out_p.append({k: pr.get(k) for k in ("source", "outcome", "identity", "identity_basis", "record", "url")})
        applied = []
        for p in pts:
            p["provenance_id"] = (p.get("provenance") or {}).get("id")
            p.pop("provenance", None)
            c.setdefault("external_patches", []).append(p)
            self.counts["filled"] += p["op"] in ("set", "add")
            self.counts["conflicts"] += p["op"] == "conflict"
            applied.append({"op": p["op"], "field": p.get("field") or p.get("section"), "value": p.get("value", (p.get("conflict") or {}).get("topic"))})
        db.save_candidate(c["id"], self.pid, c)
        return out_p, applied

    # -- tools -------------------------------------------------------------------------------
    def get_shortlist_state(self):
        ev = self._ranking()
        rows = []
        for e in ev["ranking"]:
            pri = Counter(g.get("priority", 9) for g in e["gaps"])
            c = db.get_candidate(e["candidate_id"])
            rows.append({"candidate_id": e["candidate_id"], "name": e["name"], **self._status(e),
                         "open_gaps_by_priority": {str(k): v for k, v in sorted(pri.items())},
                         "values_from_sources": len(c.get("external_patches") or []),
                         "clarification_planned": (c.get("agent_clarification") or {}).get("gap_ids")})
        return {"shortlist_size": ev["k"], "external_checks_permitted": self.external, "approved_sources": self.sources if self.external else [],
                "candidates": rows}

    def get_candidate_gaps(self, candidate_id, include_not_pursued=False):
        e, k = self._entry(candidate_id)
        prof = self.pipeline.effective_profile(self._cand(candidate_id))
        gaps = []
        for g in e["gaps"]:
            if g.get("priority", 9) > 3 and not include_not_pursued:
                continue
            h = verification.handler_for(g)
            src = {verification.verify_publication: ["crossref", "openalex", "orcid_works"], verification.verify_degree: ["orcid_education"],
                   verification.verify_role_dates: ["orcid_employment"]}.get(h, [])
            if g["type"] == "eligibility" and g.get("criterion") == "publications":
                src = []  # settled through the individual publication gaps
            gaps.append({"gap_id": g["id"], "type": g["type"], "label": g["label"], "detail": g.get("detail"), "priority": g.get("priority"),
                         "why": g.get("priority_label"), "impact": g.get("impact", []), "publication_index": g.get("item_index") if g.get("section") == "publications" else None,
                         "checkable_with": [s for s in src if s in self.sources] if self.external else []})
        hidden = sum(1 for g in e["gaps"] if g.get("priority", 9) > 3) if not include_not_pursued else 0
        return {"candidate_id": candidate_id, "name": e["name"], **self._status(e), "shortlist_size": k,
                "has_orcid": bool(prof.get("orcid")),
                "publications": [{"index": i, "title": p.get("title"), "year": p.get("year"), "venue": p.get("venue"), "type": p.get("type")}
                                 for i, p in enumerate(prof.get("publications", []))],
                "conflicts": [c.get("topic") for c in prof.get("conflicts", [])],
                "gaps": gaps, "not_pursued_hidden": hidden}

    def verify_gap(self, candidate_id, gap_id, sources=None):
        self._need_external(sources)
        srcs = list(sources) if sources else list(self.sources)
        e, _ = self._entry(candidate_id)
        g = self._gap(e, gap_id)
        if g["type"] == "eligibility" and g.get("criterion") == "publications":
            raise ToolError("This eligibility item is settled through the individual publication gaps; verify those instead.")
        h = verification.handler_for(g)
        if not h:
            raise ToolError("No approved source can settle this kind of gap. Consider a clarification request.")
        key = (candidate_id, "degree") if h is verification.verify_degree else (candidate_id, g.get("section"), g.get("item_index"), tuple(sorted(srcs)))
        if key in self.attempted:
            return {"already_attempted": True, "previous_result": self.attempted[key]}
        c = self._cand(candidate_id)
        try:
            provs, pts = h(self.pipeline.effective_profile(c), g, self.tr, srcs)
        except Exception as ex:  # noqa: BLE001
            raise ToolError(f"Source query failed: {str(ex)[:200]}")
        recs, applied = self._store(c, provs, pts)
        e2, _ = self._entry(candidate_id)
        out = {"gap": g["label"], "records": recs or "no source returned anything for this gap", "applied": applied,
               "gap_still_open": any(x["id"] == gap_id for x in e2["gaps"]), "candidate_now": self._status(e2)}
        self.attempted[key] = {k: out[k] for k in ("applied", "gap_still_open")} | {"outcomes": [r["outcome"] for r in recs]}
        db.audit(candidate_id, "agent_verify", {"gap": gap_id, "sources": srcs, "outcomes": [r["outcome"] for r in recs], "applied": applied})
        return out

    def search_publication(self, candidate_id, publication_index, query_title, source, author_surname=None):
        self._need_external([source])
        if source not in ("crossref", "openalex"):
            raise ToolError("source must be 'crossref' or 'openalex'.")
        prof = self.pipeline.effective_profile(self._cand(candidate_id))
        pubs = prof.get("publications", [])
        if not isinstance(publication_index, int) or not 0 <= publication_index < len(pubs):
            raise ToolError(f"publication_index must be between 0 and {len(pubs) - 1}.")
        if self.counts[("search", candidate_id, publication_index)] >= 3:
            raise ToolError("Search limit for this publication reached (3). Ask the applicant instead.")
        self.counts[("search", candidate_id, publication_index)] += 1
        family = author_surname or verification._name_parts(prof.get("name"))[1]
        fn = verification.crossref_search if source == "crossref" else verification.openalex_search
        try:
            recs = fn(self.tr, query_title, family)
        except Exception as ex:  # noqa: BLE001
            raise ToolError(f"Source query failed: {str(ex)[:200]}")
        out = []
        for r in recs:
            rid = f"rec{len(self.records) + 1}"
            self.records[rid] = (candidate_id, publication_index, r)
            ident, basis = verification.identity_check(prof, r["authors"], r.get("affiliations"))
            out.append({"record_id": rid, "title": r.get("title"), "venue": r.get("venue"), "year": r.get("year"), "type": r.get("type"), "doi": r.get("doi"),
                        "title_similarity_to_listed": round(verification.title_similarity(r.get("title"), pubs[publication_index].get("title")), 2),
                        "identity": ident, "identity_basis": basis})
        note = "" if self.transport == "live" else " (recorded-responses mode: only queries that were recorded in advance return results)"
        return {"records": out, "note": ("no records found" + note) if not out else None}

    def accept_publication_record(self, candidate_id, gap_id, record_id):
        self._need_external()
        if record_id not in self.records:
            raise ToolError("Unknown record_id; use one returned by search_publication in this run.")
        rc, idx, rec = self.records[record_id]
        if rc != candidate_id:
            raise ToolError("That record was retrieved for a different applicant.")
        e, _ = self._entry(candidate_id)
        g = self._gap(e, gap_id)
        if g.get("section") != "publications" or g.get("item_index") != idx:
            raise ToolError(f"Gap '{gap_id}' is not about publication #{idx}.")
        c = self._cand(candidate_id)
        prof = self.pipeline.effective_profile(c)
        sim = verification.title_similarity(rec.get("title"), prof["publications"][idx].get("title"))
        if sim < 0.85:
            raise ToolError(f"Title similarity {sim:.2f} is below 0.85; this is not clearly the same work.")
        provs, pts = verification.verify_publication(prof, g, self.tr, self.sources, recs=[rec], min_similarity=0.85)
        recs, applied = self._store(c, provs, pts)
        e2, _ = self._entry(candidate_id)
        db.audit(candidate_id, "agent_accept_record", {"gap": gap_id, "record": rec.get("url"), "applied": applied})
        return {"gap": g["label"], "records": recs, "applied": applied, "gap_still_open": any(x["id"] == gap_id for x in e2["gaps"]), "candidate_now": self._status(e2)}

    def spot_check_orcid(self, candidate_id):
        self._need_external(["orcid_works"])
        if ("spot", candidate_id) in self.attempted:
            return {"already_attempted": True, "previous_result": self.attempted[("spot", candidate_id)]}
        c = self._cand(candidate_id)
        prof = self.pipeline.effective_profile(c)
        if not prof.get("orcid"):
            raise ToolError("This applicant gave no ORCID iD.")
        provs, pts = verification.spot_check_publications(prof, self.tr, self.sources)
        for p in pts:
            p.setdefault("provenance", None)
        recs, applied = self._store(c, provs, pts)
        e2, _ = self._entry(candidate_id)
        res = {"publications_compared": len(recs), "conflicts_flagged": applied, "candidate_now": self._status(e2)}
        self.attempted[("spot", candidate_id)] = res
        return res

    def plan_clarification(self, candidate_id, gap_ids, reason):
        e, _ = self._entry(candidate_id)
        c = self._cand(candidate_id)
        gaps = [self._gap(e, gid) for gid in gap_ids]
        low = [g["label"] for g in gaps if g.get("priority", 9) > 3]
        if low:
            raise ToolError(f"These gaps cannot change eligibility or the shortlist, so applicants are not asked about them: {low}.")
        c["agent_clarification"] = {"gap_ids": list(gap_ids), "reason": reason, "at": _now()}
        db.save_candidate(candidate_id, self.pid, c)
        db.audit(candidate_id, "agent_clarification_plan", {"gap_ids": gap_ids, "reason": reason})
        draft = clarify.build_requests({**e, "gaps": gaps}, db.get_position(self.pid)["template"]["position"]["title"]) if gaps else None
        return {"planned_questions": [q["question"] for q in (draft or {}).get("questions", [])] or "no request will be sent"}

    def finish(self, summary):
        self.summary = summary
        return {"ok": True}

    # -- trace -------------------------------------------------------------------------------
    def _name(self, cid):
        c = db.get_candidate(cid) if cid else None
        return (c or {}).get("name") or cid

    def _trace(self, name, args, res, err):
        who = self._name(args.get("candidate_id")) if args.get("candidate_id") else ""
        if err:
            self.note("error", f"{name}({who}): {res['error']}")
            return
        if name == "get_shortlist_state":
            self.note("tool", "Looked at the current shortlist.")
        elif name == "get_candidate_gaps":
            self.note("tool", f"Reviewed {who}'s open items ({len(res['gaps'])} that could matter).")
        elif name in ("verify_gap", "accept_publication_record"):
            if res.get("already_attempted"):
                self.note("tool", f"{who}: already checked; reused the earlier result.")
                return
            recs = res["records"] if isinstance(res["records"], list) else []
            outs = ", ".join(sorted({r["outcome"] for r in recs})) or "nothing found"
            filled = "; ".join(f"{a['field']} = {a['value']}" for a in res["applied"] if a["op"] in ("set", "add")) or "no values filled"
            now = res["candidate_now"]
            used = sorted({s for r in recs for s in str(r.get("source") or "").split(",") if s}) or (args.get("sources") or ["approved sources"])
            what = res.get("gap") or args.get("gap_id", "")
            self.note("tool", f"{who}: checked “{what}” via {', '.join(used)} → {outs}; {filled}. "
                              f"Now {now['supported']:.1f}–{now['possible']:.1f}, {now['shortlist_status'].replace('_', ' ')}.")
        elif name == "search_publication":
            self.note("tool", f"{who}: searched {args['source']} for “{args['query_title']}” → {len(res['records'])} record(s).")
        elif name == "spot_check_orcid":
            self.note("tool", f"{who}: compared listed publications with ORCID ({res['publications_compared']} matched, {len(res['conflicts_flagged'])} disagreement(s)).")
        elif name == "plan_clarification":
            q = res["planned_questions"]
            self.note("decision", f"{who}: " + (f"ask {len(q)} question(s)" if isinstance(q, list) else "no request") + f" — {args.get('reason', '')}")
        elif name == "finish":
            self.note("summary", args.get("summary", ""))


# ------------------------------------------------------------------------------------------------
# Drivers
# ------------------------------------------------------------------------------------------------
def _kickoff(run):
    pos = db.get_position(run.pid)
    t = pos["template"]
    return (f"Position: {t['position']['title']}. Shortlist size: {t['shortlist_size']}.\n"
            f"External verification permitted: {'yes' if run.external else 'no'}"
            + (f"; approved sources: {', '.join(run.sources)}; access mode: {'live internet' if run.transport == 'live' else 'recorded responses'}." if run.external else ".")
            + f"\nTool-call budget: {MAX_TOOL_CALLS}. Start by looking at the shortlist.")


def _drive_model(run, chat):
    """Protocol-neutral agent loop: the model picks tools until it calls finish or stops calling tools."""
    for _ in range(MAX_MODEL_TURNS):
        turn = chat.step()
        for t in turn.texts:
            run.note("agent", t)
        if turn.stop == "refusal":
            run.note("error", "The model declined to continue; the run stopped. Open items keep the default clarification rule.")
            return
        if turn.stop == "max_tokens":
            run.note("error", "The model's reply was cut off (output limit); the run stopped.")
            return
        if turn.stop.startswith("error:"):
            run.note("error", f"The model stopped: {turn.stop[6:]}.")
            return
        if not turn.calls:
            if run.tool_calls == 0:
                run.note("error", "The model answered without using any tools. Some models (especially small local ones) do not support tool calling.")
            return
        chat.add_results([(c, *run.call(c.name, c.args)) for c in turn.calls])
        if run.summary is not None:
            return
    run.note("error", f"Stopped after {MAX_MODEL_TURNS} model turns.")


def _drive_scripted(run):
    """Offline fallback: the original fixed procedure, executed through the same tools."""
    ev = run._ranking()
    for e in ev["ranking"]:
        if not run.external:
            break
        cid = e["candidate_id"]
        pri = [g for g in e["gaps"] if g.get("priority", 9) <= 3]
        crit = {g["criterion"] for g in pri if g["type"] == "eligibility"}
        pri += [g for g in e["gaps"] if g.get("priority", 9) > 3 and g["criterion"] in crit and g["type"] != "eligibility"]
        for g in pri:
            if verification.handler_for(g) and not (g["type"] == "eligibility" and g["criterion"] == "publications"):
                if any(x["id"] == g["id"] for x in run._entry(cid)[0]["gaps"]):
                    run.call("verify_gap", {"candidate_id": cid, "gap_id": g["id"]})
        if e["provisional_shortlist"] and run._cand(cid)["profile_base"].get("orcid") and "orcid_works" in run.sources:
            run.call("spot_check_orcid", {"candidate_id": cid})
    run.summary = ("Scripted run (no AI model selected): every gap of priority 1–3 with an approved source was checked once, in ranking order; "
                   "clarification requests follow the default rule.")
    run.note("summary", run.summary)


def run(pid, external_permitted=False, sources=None, transport="fixture", resume=False):
    """resume=True continues from the previous run's results (values filled, clarifications planned) instead of starting over.
    Useful when a run stopped part-way because the model was overloaded or rate-limited."""
    from . import pipeline
    sources = [s for s in (sources or list(verification.SOURCES)) if s in verification.SOURCES]
    pos = db.get_position(pid)
    prev = pos.get("last_resolution") if resume else None
    pos["resolution"] = {"external_permitted": external_permitted, "sources": sources, "transport": transport}
    db.save_position(pid, pos)
    if not prev:
        for c in db.list_candidates(pid):
            if c.get("profile_base"):
                c["external_patches"], c["agent_clarification"] = [], None
                db.save_candidate(c["id"], pid, c)
                db.clear_provenance(c["id"])
    r = Run(pid, external_permitted, sources, transport)
    kickoff = _kickoff(r)
    if prev:
        kickoff += ("\nThis run CONTINUES an earlier run that stopped part-way. Values already filled from sources and clarification plans "
                    "already made are kept (get_shortlist_state shows them as values_from_sources and clarification_planned). "
                    "Do not redo finished work; continue with what is still open.")
    try:
        chat = llm.tool_chat(SYSTEM, TOOLS, kickoff)
    except llm.LLMError as ex:
        chat = None
        r.note("error", f"Could not start the AI agent ({ex}); running the scripted workflow instead.")
    mode = f"AI agent: {llm.active_label()}" if chat else "Scripted workflow (no AI model)"
    r.log.insert(0, {"kind": "info", "text": f"{mode}. External checks {'permitted: ' + ', '.join(sources) if external_permitted else 'not permitted'}."
                                             + (" Continuing the previous run." if prev else "")})
    jobs.emit("info", r.log[0]["text"])
    try:
        _drive_model(r, chat) if chat else _drive_scripted(r)
    except llm.LLMError as ex:
        r.note("error", f"The agent stopped: {ex}. Changes made before the error are kept.")
    except Exception as ex:  # noqa: BLE001 - never lose the run log to an unexpected failure
        r.note("error", f"The agent stopped on an unexpected error ({type(ex).__name__}: {str(ex)[:200]}). Changes made before the error are kept.")
    undecided = [e["name"] for e in pipeline.evaluate(pid)["ranking"]
                 if e.get("clarification") and not db.get_candidate(e["candidate_id"]).get("agent_clarification")]
    if undecided and chat:
        r.note("info", f"No plan from the agent for {', '.join(undecided)}; the default clarification rule applies to them.")
    r.note("info", f"{r.tool_calls} tool calls · {r.counts['records']} source records logged · {r.counts['filled']} values filled · "
                   f"{r.counts['conflicts']} conflicts flagged · {r.counts['rejected']} records rejected or held for an identity check.")
    ev = pipeline.evaluate(pid)
    pos = db.get_position(pid)
    log = (prev.get("log") or []) + [{"kind": "info", "text": "— continued —"}] + r.log if prev else r.log
    stopped = r.summary is None and any(l["kind"] == "error" for l in r.log)
    pos["last_resolution"] = {"at": _now(), "mode": mode, "summary": r.summary, "log": log, "stopped": stopped}
    db.save_position(pid, pos)
    return {"log": log, "summary": r.summary, "mode": mode, "stopped": stopped, "evaluation": ev}
