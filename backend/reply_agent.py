"""Reply agent: reads an applicant's reply (pasted e-mail text) and proposes updates for the open items.

The model matches what the applicant wrote to the open gaps and proposes structured answers. It cannot
change anything itself: proposals are stored, shown to the committee, and applied only for the ones the
committee approves (POST /api/candidates/{cid}/reply/apply).

Enforced in code:
  * every proposal must quote the applicant's own words, and the quote must be found in the reply text;
  * values are validated per kind of gap (years in a plausible range, roles from a fixed list, a conflict
    can only be resolved to one of the values already on record);
  * the patch that would be applied is built here from those values, never written by the model.
"""
import datetime as dt

from . import db, extraction, llm
from .agent import MAX_MODEL_TURNS, ToolBox, ToolError, _drive_model, _obj

SYSTEM = """You read an applicant's reply to a clarification request from an academic hiring committee and map what \
they wrote onto the open items in their application.
- Call get_open_items first. For each item the reply answers, call propose_answer with the values the reply states and \
an exact quote of the applicant's words that supports them. Use only what the reply actually says: never infer, guess or \
fill in values from elsewhere. If the reply only partly answers an item, propose only the values it states.
- For items the reply does not answer, or answers ambiguously, call mark_unanswered with a short reason.
- The committee reviews every proposal before anything changes. When done, call finish with a two-sentence summary."""

YEAR = {"type": "integer", "description": "Four-digit year"}
TOOLS = [
    {"name": "get_open_items",
     "description": "The applicant's open items, each with gap_id, what is missing, and which fields an answer can contain.",
     "input_schema": _obj({})},
    {"name": "propose_answer",
     "description": "Propose an answer to one open item from the reply. 'answers' may use only the fields listed for that item. "
                    "'quote' must be the applicant's exact words from the reply that state these values.",
     "input_schema": _obj({"gap_id": {"type": "string"},
                           "answers": {"type": "array", "description": "One entry per field the reply states, using the fields listed for this item.",
                                       "items": _obj({"field": {"type": "string"}, "value": {"type": "string"}}, ["field", "value"])},
                           "quote": {"type": "string"}}, ["gap_id", "answers", "quote"])},
    {"name": "mark_unanswered",
     "description": "Record that the reply does not (clearly) answer an open item.",
     "input_schema": _obj({"gap_id": {"type": "string"}, "reason": {"type": "string"}}, ["gap_id", "reason"])},
    {"name": "finish", "description": "End with a short summary for the committee.", "input_schema": _obj({"summary": {"type": "string"}}, ["summary"])},
]

# What an answer may contain, per kind of open item. type: str | year | year_or_present | int | one of a list
FIELDS = {
    "degree": {"field": "str", "institution": "str", "year": "year"},
    "teaching": {"course": "str", "institution": "str", "role": ["lead", "assistant"], "start": "year", "end": "year_or_present"},
    "dates": {"start": "year", "end": "year_or_present"},
    "publication": {"year": "year", "venue": "str", "type": ["journal", "conference", "book", "chapter", "preprint"]},
    "grant_role": {"role": ["PI", "Co-I"]},
    "supervision": {"count": "int"},
    "conflict": {"value": "one of the recorded values"},
    "phd_awarded": {"year": "year"},
}


def _kind(g):
    t, code, crit = g["type"], g.get("code"), g.get("criterion")
    if (t == "eligibility" and code in ("unstated", "implied") and crit == "qualifications") or t == "degree_unstated":
        return "degree"
    if (t == "eligibility" and code == "unstated" and crit == "teaching") or t == "teaching_unstated":
        return "teaching"
    if t == "eligibility" and code == "in_progress":
        return "phd_awarded"
    if t == "conflict" and ((g.get("request") or {}).get("conflict")):
        return "conflict"
    return {"dates": "dates", "publication_details": "publication", "grant_role": "grant_role", "supervision_details": "supervision"}.get(t)


def _check_value(kind_spec, k, v):
    yr = dt.date.today().year + 2
    if kind_spec == "str":
        if not isinstance(v, str) or not v.strip():
            raise ToolError(f"'{k}' must be non-empty text.")
        return v.strip()
    if kind_spec in ("year", "year_or_present"):
        if kind_spec == "year_or_present" and isinstance(v, str) and v.strip().lower() in ("present", "now", "current"):
            return "present"
        try:
            v = int(v)
        except (TypeError, ValueError):
            raise ToolError(f"'{k}' must be a four-digit year" + (" or 'present'." if kind_spec == "year_or_present" else "."))
        if not 1950 <= v <= yr:
            raise ToolError(f"'{k}' = {v} is not a plausible year.")
        return v
    if kind_spec == "int":
        try:
            v = int(v)
        except (TypeError, ValueError):
            raise ToolError(f"'{k}' must be a whole number.")
        if not 0 <= v <= 200:
            raise ToolError(f"'{k}' = {v} is not plausible.")
        return v
    if isinstance(kind_spec, list):
        m = next((x for x in kind_spec if str(v).strip().lower() == x.lower()), None)
        if not m:
            raise ToolError(f"'{k}' must be one of {kind_spec}.")
        return m
    return v


def _describe(kind, g, vals):
    if kind == "degree":
        return "Add PhD: " + ", ".join(str(vals[k]) for k in ("field", "institution", "year") if vals.get(k) is not None)
    if kind == "teaching":
        return "Add teaching: " + ", ".join(f"{k} {vals[k]}" for k in ("course", "institution", "role", "start", "end") if vals.get(k) is not None)
    if kind == "conflict":
        return f"Resolve “{g['label']}” to {vals['value']}"
    if kind == "phd_awarded":
        return f"PhD awarded in {vals['year']}"
    return f"“{g['label']}”: " + ", ".join(f"{k} = {v}" for k, v in vals.items())


def _patches(kind, g, vals, profile):
    if kind == "degree":
        return [{"op": "add", "section": "degrees", "item": {"level": "phd", "field": vals.get("field"), "institution": vals.get("institution"),
                                                             "year": vals.get("year"), "status": "completed", "expected_year": None, "evidence": []}}]
    if kind == "teaching":
        return [{"op": "add", "section": "teaching", "item": {"course": vals.get("course") or "Teaching", "institution": vals.get("institution"),
                                                              "role": vals.get("role"), "university": True, "start": vals.get("start"),
                                                              "end": vals.get("end"), "evidence": []}}]
    if kind == "conflict":
        return [{"op": "resolve", "conflict": g["request"]["conflict"][0]["id"], "value": vals["value"]}]
    if kind == "phd_awarded":
        i = next((j for j, d in enumerate(profile.get("degrees", [])) if d.get("level") == "phd"), None)
        if i is None:
            raise ToolError("No doctoral degree is on record to update.")
        return [{"op": "set", "section": "degrees", "index": i, "field": "status", "value": "completed"},
                {"op": "set", "section": "degrees", "index": i, "field": "year", "value": vals["year"]}]
    out = [{"op": "set", "section": g["section"], "index": g["item_index"], "field": k, "value": v} for k, v in vals.items()]
    if kind == "publication" and vals.get("type") and vals["type"] != "preprint":
        out.append({"op": "set", "section": "publications", "index": g["item_index"], "field": "peer_reviewed", "value": True})
    return out


class ReplyRun(ToolBox):
    TOOLS = TOOLS
    MAX_CALLS = 40

    def __init__(self, cid, text):
        super().__init__()
        from . import pipeline
        self.pipeline, self.cid, self.text = pipeline, cid, text
        self.text_norm = extraction._norm(text)
        self.proposals, self.unanswered = {}, {}

    def _gaps(self):
        d = self.pipeline.candidate_detail(self.cid)
        e = d.get("evaluation") or {}
        gaps = e.get("gaps", [])
        # An eligibility question on the degree covers the 'degree not stated' score gap (as in the interface).
        ec = {g["criterion"] for g in gaps if g["type"] == "eligibility" and g.get("code") in ("unstated", "implied")}
        return [g for g in gaps if not (g["type"].endswith("_unstated") and g["criterion"] in ec)], d.get("profile") or {}

    def get_open_items(self):
        gaps, _ = self._gaps()
        items = []
        for g in gaps:
            k = _kind(g)
            item = {"gap_id": g["id"], "label": g["label"], "missing": g.get("detail"), "answer_fields": FIELDS.get(k) if k else "cannot be recorded from a reply"}
            if k == "conflict":
                item["recorded_values"] = [v.get("value") for v in g["request"]["conflict"][0].get("values", [])]
            items.append(item)
        return {"applicant": db.get_candidate(self.cid).get("name"), "open_items": items}

    def propose_answer(self, gap_id, answers, quote):
        if not isinstance(answers, list) or not all(isinstance(a, dict) and "field" in a for a in answers):
            raise ToolError("'answers' must be a list of {field, value}.")
        values = {str(a["field"]).strip(): a.get("value") for a in answers}
        gaps, profile = self._gaps()
        g = next((x for x in gaps if x["id"] == gap_id), None)
        if not g:
            raise ToolError(f"'{gap_id}' is not an open item. Call get_open_items.")
        kind = _kind(g)
        if not kind:
            raise ToolError("This item cannot be recorded from a reply; mark it unanswered and the committee will handle it.")
        if extraction.check_quote(quote, self.text_norm) == "missing":
            raise ToolError("The quote was not found in the reply. Quote the applicant's exact words.")
        if not isinstance(values, dict) or not values:
            raise ToolError("Give at least one value.")
        spec = FIELDS[kind]
        bad = [k for k in values if k not in spec]
        if bad:
            raise ToolError(f"Fields {bad} are not allowed for this item. Allowed: {list(spec)}.")
        if kind == "conflict":
            recorded = [v.get("value") for v in g["request"]["conflict"][0].get("values", [])]
            m = next((r for r in recorded if str(r).strip().lower() == str(values["value"]).strip().lower()), None)
            if m is None:
                raise ToolError(f"A conflict can only be resolved to a recorded value: {recorded}. Otherwise mark it unanswered.")
            vals = {"value": m}
        else:
            vals = {k: _check_value(spec[k], k, v) for k, v in values.items() if v not in (None, "")}
        pid = f"P{len(self.proposals) + 1}"
        for k_, p in list(self.proposals.items()):
            if p["gap_id"] == gap_id:
                self.proposals.pop(k_)
        self.proposals[pid] = {"id": pid, "gap_id": gap_id, "label": g["label"], "change": _describe(kind, g, vals), "values": vals,
                               "quote": quote.strip(), "patches": _patches(kind, g, vals, profile)}
        self.unanswered.pop(gap_id, None)
        return {"proposal_id": pid, "change": self.proposals[pid]["change"], "status": "awaiting committee approval"}

    def mark_unanswered(self, gap_id, reason):
        gaps, _ = self._gaps()
        g = next((x for x in gaps if x["id"] == gap_id), None)
        if not g:
            raise ToolError(f"'{gap_id}' is not an open item.")
        self.unanswered[gap_id] = {"gap_id": gap_id, "label": g["label"], "reason": reason}
        return {"ok": True}

    def _trace(self, name, args, res, err):
        if err:
            self.note("error", f"{name}: {res['error']}")
        elif name == "get_open_items":
            self.note("tool", f"Looked at {len(res['open_items'])} open item(s).")
        elif name == "propose_answer":
            self.note("decision", f"Proposed: {res['change']} — “{args.get('quote', '')[:120]}”")
        elif name == "mark_unanswered":
            self.note("tool", f"Not answered: {self.unanswered[args['gap_id']]['label']} — {args.get('reason', '')}")


def propose(cid, text):
    c = db.get_candidate(cid)
    if not c or not c.get("profile_base"):
        raise llm.LLMError("This application has not been extracted yet.")
    if not (text or "").strip():
        raise llm.LLMError("Paste the applicant's reply first.")
    r = ReplyRun(cid, text)
    chat = llm.tool_chat(SYSTEM, TOOLS, f"The applicant's reply:\n<reply>\n{text[:20000]}\n</reply>")
    if not chat:
        raise llm.LLMError("Reading replies needs an AI model. Choose a provider under 1 · Position & parameters → AI model.")
    try:
        _drive_model(r, chat)
    except llm.LLMError as ex:
        r.note("error", f"The agent stopped: {ex}")
    pending = {"at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(), "model": llm.active_label(), "text": text,
               "proposals": list(r.proposals.values()), "unanswered": list(r.unanswered.values()), "summary": r.summary, "log": r.log}
    c = db.get_candidate(cid)
    c["pending_reply"] = pending
    db.save_candidate(cid, r.pipeline._pid_of(cid), c)
    db.audit(cid, "reply_agent_proposals", {"proposals": [{k: p[k] for k in ("gap_id", "change", "quote")} for p in pending["proposals"]],
                                            "model": pending["model"]})
    return pending


def apply(cid, proposal_ids):
    from . import pipeline
    c = db.get_candidate(cid)
    pending = (c or {}).get("pending_reply")
    if not pending:
        raise llm.LLMError("There are no proposals to apply.")
    chosen = [p for p in pending["proposals"] if p["id"] in set(proposal_ids or [])]
    for p in chosen:
        for patch in p["patches"]:
            pipeline.record_reply(cid, patch, note=f"“{p['quote']}” (read by AI, approved by the committee)")
    c = db.get_candidate(cid)
    c["pending_reply"] = None
    db.save_candidate(cid, pipeline._pid_of(cid), c)
    db.audit(cid, "reply_agent_applied", {"applied": [p["change"] for p in chosen], "rejected": [p["change"] for p in pending["proposals"] if p not in chosen]})
    return {"applied": [p["change"] for p in chosen]}
