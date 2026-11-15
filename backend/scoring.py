"""Evidence-aware scoring.

For each candidate the engine produces:
  * requirement statuses: met / not_met / not_established (+ reason, evidence, conflict flag)
  * eligibility: eligible / ineligible / unresolved
  * per-criterion score ranges [supported, possible] on 0-10 with item-level explanations
  * overall supported score and possible score on 0-100
  * gaps: every unresolved fact with the score width it controls

Across candidates it produces the ranking, a shortlist-reliability status for each candidate,
and a priority order of gaps (which clarification could change the shortlist).

Design rules (from the supervision brief):
  * An omitted fact is never treated as a negative fact. Only positive evidence gives not_met.
  * Conflicting values are kept; the score range covers every value.
  * The supported score uses only facts whose evidence was found in a document or verified externally.
"""
from copy import deepcopy

from .config import CURRENT_YEAR
from .profile import (attach_alternatives, duration_bounds, evidence_list, has_conflict, label_for,
                      matches_any, supported, values, year_of)

STATUS = ("met", "not_met", "not_established")
LEVEL_RANK = {"bachelors": 1, "masters": 2, "phd": 3}


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------
def _field_matches(field, fields):
    return bool(field) and matches_any(field, fields)


def _req(template, kind):
    for r in template["requirements"]:
        if r["kind"] == kind and r["tier"] == "required":
            return r
    return None


def _ev(items):
    out = []
    for it in items:
        out.extend(evidence_list(it))
    return out[:4]


def _gap(cid, kind, criterion, section, idx, label, detail, lo, hi, request, verifiable=None, item=None):
    return {
        "id": f"{cid}:{criterion}:{section}:{idx}:{kind}",
        "candidate_id": cid, "type": kind, "criterion": criterion, "section": section, "item_index": idx,
        "label": label, "detail": detail, "lo_pts": lo, "hi_pts": hi,
        "request": request, "verifiable": verifiable or [],
        "evidence": evidence_list(item) if item else [],
    }


# --------------------------------------------------------------------------------------------
# Criterion rules. Each returns raw points per item as (lo, hi); aggregation and caps come after.
# --------------------------------------------------------------------------------------------
def crit_qualifications(p, t, cid):
    spec = t["criteria"]["qualifications"]
    pts, factor = spec["points"], spec["unrelated_field_factor"]
    r1 = _req(t, "degree")
    fields = (r1 or {}).get("params", {}).get("fields", [])
    items, gaps = [], []
    unc = t["uncertainty"]
    phd_established = False
    for i, d in enumerate(p["degrees"]):
        los, his = [], []
        for level, status, field in [(l, s, f) for l in values(d, "level") for s in values(d, "status") for f in values(d, "field")]:
            if level == "phd":
                if status == "completed":
                    base_lo = base_hi = pts["phd"]
                elif status == "in_progress":
                    base_lo = base_hi = pts["phd_in_progress"]
                else:  # status not stated
                    base_lo, base_hi = pts["phd_in_progress"], pts["phd"]
            elif level in ("masters", "bachelors"):
                base_lo = base_hi = pts[level]
            else:
                base_lo = base_hi = 0
            if field is None:
                f_lo, f_hi = factor, 1.0
            else:
                f_lo = f_hi = 1.0 if _field_matches(field, fields) or not fields else factor
            los.append(base_lo * f_lo)
            his.append(base_hi * f_hi)
        lo, hi = min(los), max(his)
        ok = supported(d, unc)
        if not ok:
            lo = 0
        note = []
        if d.get("level") == "phd" and d.get("status") == "completed" and ok and _field_matches(d.get("field"), fields):
            phd_established = True
        if d.get("level") == "phd" and d.get("status") not in ("completed", "in_progress"):
            note.append("completion not stated")
        if d.get("field") is None and d.get("level") in ("phd", "masters"):
            note.append("field not stated")
        if has_conflict(d):
            note.append("documents disagree")
        if not ok:
            note.append("evidence not found in the documents")
        items.append({"label": label_for("degrees", d), "lo": lo, "hi": hi, "note": "; ".join(note), "evidence": evidence_list(d)})
        if hi > lo:
            kind = "conflict" if has_conflict(d) else ("unsupported" if not ok else "degree_details")
            gaps.append(_gap(cid, kind, "qualifications", "degrees", i, label_for("degrees", d),
                             "Degree " + ("; ".join(note) or "details incomplete"), lo, hi,
                             {"kind": kind, "item": label_for("degrees", d), "missing": note,
                              "conflict": [c for c in p["conflicts"] if c.get("item_type") == "degrees" and c.get("item_index") == i]},
                             ["orcid_education"], d))
    # Unstated doctorate: the possible score assumes the required minimum (a PhD in a listed field).
    if not phd_established and r1 and unc.get("unstated_required_assumes_minimum") and not any(d.get("level") == "phd" for d in p["degrees"]):
        why = "Doctoral-level roles suggest a PhD, but no PhD is stated" if p["indicators"].get("phd_indicated") else "No doctoral degree is mentioned in any document"
        items.append({"label": "PhD (not stated)", "lo": 0, "hi": pts["phd"], "note": why, "evidence": []})
        gaps.append(_gap(cid, "degree_unstated", "qualifications", "degrees", -1, "Doctoral degree", why, 0, pts["phd"],
                         {"kind": "degree_unstated", "item": r1["text"]}, ["orcid_education"]))
    return {"agg": "max", "cap": 10, "items": items, "gaps": gaps}


def crit_publications(p, t, cid):
    spec = t["criteria"]["publications"]
    pts, window = spec["points"], spec["recency_years"]
    unc = t["uncertainty"]
    items, gaps = [], []
    reviewed_types = [k for k in pts if k not in ("preprint", "other")]
    best_type = max(pts[k] for k in ("journal", "conference"))
    for i, pub in enumerate(p["publications"]):
        los, his = [], []
        for typ, year, pr in [(a, b, c) for a in values(pub, "type") for b in values(pub, "year") for c in values(pub, "peer_reviewed")]:
            if pr is False:
                tp_lo = tp_hi = pts["preprint"]
            elif typ in pts:
                tp_lo = tp_hi = pts[typ]
            else:
                tp_lo, tp_hi = min(pts.values()), best_type
            if year is None:
                los.append(0)
                his.append(tp_hi)
            elif year_of(year) > CURRENT_YEAR - window:
                los.append(tp_lo)
                his.append(tp_hi)
            else:
                los.append(0)
                his.append(0)
        lo, hi = min(los), max(his)
        ok = supported(pub, unc)
        if not ok:
            lo = 0
        missing = [f for f in ("year", "venue", "type") if pub.get(f) is None]
        note = []
        if missing:
            note.append("missing " + ", ".join(missing))
        if has_conflict(pub):
            note.append("sources disagree")
        if not ok:
            note.append("evidence not found in the documents")
        if pub.get("year") is not None and year_of(pub["year"]) <= CURRENT_YEAR - window and not has_conflict(pub, "year"):
            note.append(f"older than {window} years")
        items.append({"label": label_for("publications", pub), "lo": lo, "hi": hi, "note": "; ".join(note), "evidence": evidence_list(pub)})
        if hi > lo:
            kind = "conflict" if has_conflict(pub) else ("unsupported" if not ok else "publication_details")
            gaps.append(_gap(cid, kind, "publications", "publications", i, label_for("publications", pub),
                             "Publication " + "; ".join(note), lo, hi,
                             {"kind": kind, "item": pub.get("title"), "missing": missing,
                              "conflict": [c for c in p["conflicts"] if c.get("item_type") == "publications" and c.get("item_index") == i]},
                             ["crossref", "openalex", "orcid_works"], pub))
    r3 = _req(t, "publications_recent")
    if not p["publications"] and r3 and unc.get("unstated_required_assumes_minimum"):
        n = r3["params"].get("min_count", 3)
        hi = n * min(pts[k] for k in reviewed_types)
        items.append({"label": "Publications (none listed)", "lo": 0, "hi": hi, "note": "No publication list was found in any document", "evidence": []})
        gaps.append(_gap(cid, "publications_unstated", "publications", "publications", -1, "Publication list",
                         "No publications are listed", 0, hi, {"kind": "publications_unstated", "item": r3["text"]}, ["orcid_works"]))
    return {"agg": "sum", "cap": spec["cap"], "items": items, "gaps": gaps}


def _dated_sum(p, t, cid, section, criterion, rate_fn, select=lambda it: True, verif=None):
    unc = t["uncertainty"]
    items, gaps = [], []
    for i, it in enumerate(p[section]):
        sel = select(it)
        if sel is False:
            continue
        d_lo, d_hi, dstatus = duration_bounds(it, unc)
        r_lo, r_hi = rate_fn(it)
        lo, hi = d_lo * r_lo, d_hi * r_hi
        if sel is None:  # unclear whether it qualifies (e.g. university vs school teaching)
            lo = 0
        ok = supported(it, unc)
        if not ok:
            lo = 0
        note = []
        if dstatus == "missing":
            note.append("no dates given")
        elif dstatus == "partial":
            note.append("dates incomplete")
        elif dstatus == "conflict":
            note.append("dates differ between sources")
        if r_lo != r_hi:
            note.append("role level not stated")
        if sel is None:
            note.append("unclear whether it counts")
        if not ok:
            note.append("evidence not found in the documents")
        yrs = f"{d_lo:g} yr" if d_lo == d_hi else f"{d_lo:g}–{d_hi:g} yr"
        items.append({"label": label_for(section, it), "lo": lo, "hi": hi, "note": "; ".join(note), "years": yrs, "evidence": evidence_list(it)})
        if hi > lo:
            kind = "conflict" if dstatus == "conflict" else ("unsupported" if not ok else ("dates" if dstatus in ("missing", "partial") else "role_details"))
            gaps.append(_gap(cid, kind, criterion, section, i, label_for(section, it), f"{label_for(section, it)}: " + "; ".join(note),
                             lo, hi, {"kind": kind, "item": label_for(section, it), "missing": note,
                                      "conflict": [c for c in p["conflicts"] if c.get("item_type") == section and c.get("item_index") == i]},
                             verif or ["orcid_employment"], it))
    return items, gaps


def crit_teaching(p, t, cid):
    spec = t["criteria"]["teaching"]
    rates = spec["points_per_year"]

    def rate(it):
        vs = values(it, "role")
        rs = [rates.get(v) if v in rates else None for v in vs]
        if None in rs:
            return rates["assistant"], rates["lead"]
        return min(rs), max(rs)

    items, gaps = _dated_sum(p, t, cid, "teaching", "teaching", rate, select=lambda it: it.get("university", True))
    r2 = _req(t, "teaching_years")
    if not p["teaching"] and r2 and t["uncertainty"].get("unstated_required_assumes_minimum"):
        hi = r2["params"].get("min_years", 2) * rates["assistant"]
        items.append({"label": "University teaching (none listed)", "lo": 0, "hi": hi, "note": "No teaching is mentioned in any document", "evidence": []})
        gaps.append(_gap(cid, "teaching_unstated", "teaching", "teaching", -1, "University teaching", "No teaching experience is listed",
                         0, hi, {"kind": "teaching_unstated", "item": r2["text"]}, []))
    return {"agg": "sum", "cap": spec["cap"], "items": items, "gaps": gaps}


def crit_research_experience(p, t, cid):
    spec = t["criteria"]["research_experience"]
    r = spec["points_per_year"]

    def select(it):
        cats = values(it, "category")
        if all(c in ("academic", "research") for c in cats):
            return True
        if any(c in ("academic", "research") for c in cats) or None in cats:
            return None
        return False

    items, gaps = _dated_sum(p, t, cid, "positions", "research_experience", lambda it: (r, r), select=select)
    return {"agg": "sum", "cap": spec["cap"], "items": items, "gaps": gaps}


def crit_leadership(p, t, cid):
    spec = t["criteria"]["leadership"]
    r = spec["points_per_year"]
    items, gaps = _dated_sum(p, t, cid, "leadership", "leadership", lambda it: (r, r))
    return {"agg": "sum", "cap": spec["cap"], "items": items, "gaps": gaps}


def crit_funding(p, t, cid):
    spec = t["criteria"]["funding"]
    pts = spec["points"]
    unc = t["uncertainty"]
    items, gaps = [], []
    for i, g in enumerate(p["grants"]):
        vs = [pts.get(v) for v in values(g, "role")]
        if None in vs:
            lo, hi = min(pts.values()), max(pts.values())
        else:
            lo, hi = min(vs), max(vs)
        ok = supported(g, unc)
        if not ok:
            lo = 0
        note = []
        if g.get("role") is None:
            note.append("role (PI or Co-I) not stated")
        if has_conflict(g):
            note.append("sources disagree")
        if not ok:
            note.append("evidence not found in the documents")
        items.append({"label": label_for("grants", g), "lo": lo, "hi": hi, "note": "; ".join(note), "evidence": evidence_list(g)})
        if hi > lo:
            kind = "conflict" if has_conflict(g) else ("unsupported" if not ok else "grant_role")
            gaps.append(_gap(cid, kind, "funding", "grants", i, label_for("grants", g), "Grant: " + "; ".join(note), lo, hi,
                             {"kind": kind, "item": label_for("grants", g), "missing": note}, ["orcid_funding"], g))
    return {"agg": "sum", "cap": spec["cap"], "items": items, "gaps": gaps}


def crit_supervision(p, t, cid):
    spec = t["criteria"]["supervision"]
    pts = spec["points"]
    unc = t["uncertainty"]
    items, gaps = [], []
    for i, s in enumerate(p["supervision"]):
        per = []
        for lvl in values(s, "level"):
            for st in values(s, "status"):
                if lvl == "phd":
                    per += [pts["phd_completed"]] if st == "completed" else ([pts["phd_ongoing"]] if st == "ongoing" else [pts["phd_ongoing"], pts["phd_completed"]])
                elif lvl in ("masters", "undergraduate"):
                    per.append(pts[lvl])
                else:
                    per += [pts["undergraduate"], pts["masters"]]
        counts = [c for c in values(s, "count") if c is not None]
        c_lo, c_hi = (min(counts), max(counts)) if counts and None not in values(s, "count") else (1, spec["unknown_count_max"])
        lo, hi = min(per) * c_lo, max(per) * c_hi
        ok = supported(s, unc)
        if not ok:
            lo = 0
        note = []
        if s.get("count") is None:
            note.append("number of students not stated")
        if s.get("level") is None:
            note.append("level not stated")
        if not ok:
            note.append("evidence not found in the documents")
        items.append({"label": label_for("supervision", s), "lo": lo, "hi": hi, "note": "; ".join(note), "evidence": evidence_list(s)})
        if hi > lo:
            gaps.append(_gap(cid, "unsupported" if not ok else "supervision_details", "supervision", "supervision", i,
                             label_for("supervision", s), "Supervision: " + "; ".join(note), lo, hi,
                             {"kind": "supervision_details", "item": label_for("supervision", s), "missing": note}, [], s))
    return {"agg": "sum", "cap": spec["cap"], "items": items, "gaps": gaps}


CRITERIA = {
    "qualifications": crit_qualifications,
    "publications": crit_publications,
    "teaching": crit_teaching,
    "research_experience": crit_research_experience,
    "leadership": crit_leadership,
    "funding": crit_funding,
    "supervision": crit_supervision,
}


def _aggregate(c):
    """Turn item points into a 0-10 criterion range, and compute each gap's marginal effect on that range."""
    cap = c["cap"] or 1
    if c["agg"] == "max":
        lo_raw = max([it["lo"] for it in c["items"]], default=0)
        hi_raw = max([it["hi"] for it in c["items"]], default=0)
        for g in c["gaps"]:
            g["crit_gain"] = max(min(max(lo_raw, g["hi_pts"]), cap) - min(lo_raw, cap), 0) / cap * 10
    else:
        lo_raw = sum(it["lo"] for it in c["items"])
        hi_raw = sum(it["hi"] for it in c["items"])
        for g in c["gaps"]:
            g["crit_gain"] = max(min(lo_raw + g["hi_pts"] - g["lo_pts"], cap) - min(lo_raw, cap), 0) / cap * 10
    c["lo"] = min(lo_raw, cap) / cap * 10
    c["hi"] = min(hi_raw, cap) / cap * 10
    c["raw_lo"], c["raw_hi"] = lo_raw, hi_raw
    return c


# --------------------------------------------------------------------------------------------
# Requirement rules (three-state)
# --------------------------------------------------------------------------------------------
def req_status(r, p, t, crits):
    kind, prm, unc = r["kind"], r.get("params", {}), t["uncertainty"]
    if r["tier"] == "excluded":
        return {"status": "not_used", "reason": "Excluded from screening.", "evidence": []}
    if kind == "manual":
        return {"status": "manual", "reason": "To be judged by the committee.", "evidence": []}

    if kind == "degree":
        fields, by_year = prm.get("fields", []), prm.get("by_year")
        phds = [d for d in p["degrees"] if "phd" in values(d, "level")]
        if not phds:
            if p["indicators"].get("phd_indicated"):
                return {"status": "not_established", "reason": "No PhD is stated, but the documents imply one (" + "; ".join(p["indicators"].get("notes", [])[:2]) + "). An omitted degree is not treated as absent.", "evidence": [], "code": "implied"}
            return {"status": "not_established", "reason": "No doctoral degree is mentioned in any document. An omitted degree is not treated as absent.", "evidence": [], "code": "unstated"}
        best = None
        for d in phds:
            ok = supported(d, unc)
            st_vals, f_vals = values(d, "status"), values(d, "field")
            conflict = has_conflict(d)
            if not ok:
                cand = ("not_established", "The PhD is mentioned but the quoted evidence could not be found in the documents.", "unsupported")
            elif st_vals == ["in_progress"]:
                exp = d.get("expected_year")
                if exp and by_year and exp > by_year:
                    cand = ("not_met", f"PhD is in progress, expected {exp}, after the {by_year} deadline.", "expected_late")
                else:
                    cand = ("not_established", f"PhD is in progress{', expected ' + str(exp) if exp else ', no expected date given'}. Completion by {by_year} needs confirming.", "in_progress")
            elif "completed" not in st_vals:
                cand = ("not_established", "A PhD is listed but it is not stated whether it has been awarded.", "status_unstated")
            elif None in f_vals:
                cand = ("not_established", "PhD awarded, but the field is not stated.", "field_unstated")
            elif all(_field_matches(f, fields) for f in f_vals):
                cand = ("met", f"PhD in {' / '.join(str(f) for f in f_vals)}" + (" (sources disagree on details, but every version meets the requirement)" if conflict else "."), "met")
            elif any(_field_matches(f, fields) for f in f_vals):
                cand = ("not_established", "Sources disagree on the PhD field; one version is in a listed field and one is not.", "conflict")
            else:
                cand = ("not_established", f"PhD field ({d.get('field')}) is not in the listed related fields; relevance needs committee judgement.", "field_relevance")
            order = {"met": 3, "not_established": 2, "not_met": 1}
            if best is None or order[cand[0]] > order[best[0]]:
                best = cand + (d,)
        st, reason, code, d = best
        return {"status": st, "reason": reason, "evidence": evidence_list(d), "code": code, "conflict": has_conflict(d)}

    if kind == "teaching_years":
        need = prm.get("min_years", 2)
        uni = [it for it in p["teaching"] if it.get("university", True) is not False]
        if not uni:
            return {"status": "not_established", "reason": "No university teaching is mentioned. An omission is not treated as absence.", "evidence": [], "code": "unstated"}
        lo = sum(duration_bounds(it, unc)[0] for it in uni if supported(it, unc) and it.get("university", True) is True)
        hi = sum(duration_bounds(it, unc)[1] for it in uni)
        all_clear = all(duration_bounds(it, unc)[2] == "clear" for it in uni) and all(it.get("university") is True for it in uni)
        ev = _ev(uni)
        if lo >= need:
            return {"status": "met", "reason": f"At least {lo:g} years of university teaching are documented.", "evidence": ev, "code": "met"}
        if hi < need and all_clear:
            return {"status": "not_met", "reason": f"All teaching is fully dated and totals {hi:g} years, below the {need}-year minimum.", "evidence": ev, "code": "documented_below"}
        return {"status": "not_established", "reason": f"Documented teaching is {lo:g}–{hi:g} years because some dates are missing or disagree; the minimum is {need}.", "evidence": ev, "code": "incomplete", "conflict": any(has_conflict(it) for it in uni)}

    if kind == "publications_recent":
        need, window = prm.get("min_count", 3), prm.get("years", 6)
        pubs = p["publications"]
        if not pubs:
            return {"status": "not_established", "reason": "No publications are listed in any document.", "evidence": [], "code": "unstated"}
        lo = hi = 0
        reviewed = ("journal", "conference", "book", "chapter")
        for pub in pubs:
            ys, ts, prs = values(pub, "year"), values(pub, "type"), values(pub, "peer_reviewed")
            certain_recent = None not in ys and all(year_of(y) > CURRENT_YEAR - window for y in ys)
            maybe_recent = None in ys or any(year_of(y) > CURRENT_YEAR - window for y in ys if y is not None)
            certain_rev = False not in prs and (True in prs or all(tp in reviewed for tp in ts))
            maybe_rev = False not in prs or True in prs
            if certain_recent and certain_rev and supported(pub, unc):
                lo += 1
            if maybe_recent and maybe_rev:
                hi += 1
        ev = _ev(pubs)
        if lo >= need:
            return {"status": "met", "reason": f"{lo} recent peer-reviewed publications are documented (minimum {need}).", "evidence": ev, "code": "met"}
        if hi < need:
            return {"status": "not_met", "reason": f"Even counting every incomplete entry, at most {hi} could be recent and peer-reviewed (minimum {need}).", "evidence": ev, "code": "documented_below"}
        return {"status": "not_established", "reason": f"{lo} publications are confirmed as recent and peer-reviewed; up to {hi} could be once missing details are filled (minimum {need}).", "evidence": ev, "code": "incomplete"}

    if kind == "leadership_any":
        ok = [it for it in p["leadership"] if supported(it, unc)]
        if ok:
            return {"status": "met", "reason": f"{len(ok)} leadership or service role(s) documented.", "evidence": _ev(ok), "code": "met"}
        return {"status": "not_established", "reason": "No leadership or service role is mentioned.", "evidence": [], "code": "unstated"}

    if kind == "funding_any":
        roles = prm.get("roles", ["PI", "Co-I"])
        gs = p["grants"]
        hit = [g for g in gs if supported(g, unc) and all(v in roles for v in values(g, "role"))]
        if hit:
            return {"status": "met", "reason": f"Funding held as {', '.join(sorted({str(g.get('role')) for g in hit}))}.", "evidence": _ev(hit), "code": "met"}
        if gs:
            return {"status": "not_established", "reason": "Grants are listed but the applicant's role is not stated.", "evidence": _ev(gs), "code": "role_unstated"}
        return {"status": "not_established", "reason": "No research funding is mentioned.", "evidence": [], "code": "unstated"}

    if kind == "supervision_any":
        ok = [s for s in p["supervision"] if supported(s, unc)]
        if ok:
            return {"status": "met", "reason": "Supervision of research students documented.", "evidence": _ev(ok), "code": "met"}
        return {"status": "not_established", "reason": "No supervision is mentioned.", "evidence": [], "code": "unstated"}

    if kind == "teaching_topic":
        kws = prm.get("keywords", [])
        hit = [it for it in p["teaching"] if matches_any(" " + (it.get("course") or "") + " ", [f" {k} " if len(k) <= 3 else k for k in kws])]
        if hit:
            return {"status": "met", "reason": "Taught: " + "; ".join(h.get("course") for h in hit[:3]), "evidence": _ev(hit), "code": "met"}
        if p["teaching"]:
            return {"status": "not_established", "reason": "Teaching is listed but no matching course title is named.", "evidence": [], "code": "no_match"}
        return {"status": "not_established", "reason": "No teaching is mentioned.", "evidence": [], "code": "unstated"}

    return {"status": "not_established", "reason": "Unknown requirement type.", "evidence": []}


# --------------------------------------------------------------------------------------------
# Candidate evaluation
# --------------------------------------------------------------------------------------------
def evaluate_candidate(cid, profile, template):
    p = attach_alternatives(deepcopy(profile))
    t = template
    weights = {k: max(0.0, float(v.get("weight", 0))) for k, v in t["criteria"].items()}
    wsum = sum(weights.values()) or 1.0
    crits, gaps = {}, []
    for name, fn in CRITERIA.items():
        c = _aggregate(fn(p, t, cid))
        w = weights.get(name, 0) / wsum
        c["weight"], c["weight_norm"] = weights.get(name, 0), w
        c["contrib_lo"], c["contrib_hi"] = w * c["lo"] * 10, w * c["hi"] * 10
        for g in c["gaps"]:
            g["width"] = round(w * g["crit_gain"] * 10, 2)  # effect on the overall 0-100 score
        gaps.extend(c["gaps"])
        crits[name] = c
    lo = sum(c["contrib_lo"] for c in crits.values())
    hi = sum(c["contrib_hi"] for c in crits.values())

    reqs = []
    for r in t["requirements"]:
        s = req_status(r, p, t, crits)
        reqs.append({"id": r["id"], "tier": r["tier"], "kind": r["kind"], "text": r["text"], **s})
    required = [r for r in reqs if r["tier"] == "required"]
    if any(r["status"] == "not_met" for r in required):
        elig = "ineligible"
    elif any(r["status"] == "not_established" for r in required):
        elig = "unresolved"
    else:
        elig = "eligible"
    # Eligibility gaps: required items that are not established.
    for r in required:
        if r["status"] == "not_established":
            linked = {"degree": "qualifications", "teaching_years": "teaching", "publications_recent": "publications"}.get(r["kind"])
            width = sum(g["width"] for g in gaps if g["criterion"] == linked)
            gaps.append({"id": f"{cid}:eligibility:{r['id']}", "candidate_id": cid, "type": "eligibility", "criterion": linked,
                         "section": None, "item_index": None, "label": r["text"], "detail": r["reason"],
                         "lo_pts": 0, "hi_pts": 0, "width": round(width, 2), "requirement_id": r["id"], "code": r.get("code"),
                         "request": {"kind": "eligibility", "requirement": r["text"], "code": r.get("code"), "reason": r["reason"]},
                         "verifiable": {"degree": ["orcid_education"], "publications_recent": ["crossref", "openalex", "orcid_works"]}.get(r["kind"], []),
                         "evidence": r.get("evidence", [])})
    conflicts = profile.get("conflicts", [])
    return {
        "candidate_id": cid, "name": profile.get("name"), "lo": round(lo, 2), "hi": round(hi, 2),
        "criteria": {k: _public_crit(v) for k, v in crits.items()},
        "requirements": reqs, "eligibility": elig, "gaps": gaps, "conflicts": conflicts,
    }


def _public_crit(c):
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in c.items() if k not in ("gaps", "agg")}


# --------------------------------------------------------------------------------------------
# Ranking, shortlist reliability and gap priority
# --------------------------------------------------------------------------------------------
def rank(evals, k):
    """Order by supported score; decide for each candidate whether its shortlist place is robust."""
    pool = [e for e in evals if e["eligibility"] != "ineligible"]
    ordered = sorted(pool, key=lambda e: (-e["lo"], -e["hi"], str(e.get("name"))))
    ordered += sorted([e for e in evals if e["eligibility"] == "ineligible"], key=lambda e: (-e["lo"], str(e.get("name"))))
    provisional = {e["candidate_id"] for e in ordered[:k] if e["eligibility"] != "ineligible"}
    for i, e in enumerate(ordered):
        e["rank"] = i + 1
        e["provisional_shortlist"] = e["candidate_id"] in provisional
        if e["eligibility"] == "ineligible":
            e["shortlist_status"], e["status_reason"] = "ineligible", "A required item is not met, based on evidence in the documents."
            e["best_rank"] = e["worst_rank"] = None
            continue
        others = [o for o in pool if o is not e]
        # Best case: this candidate at its possible score, others at supported; only certainly-eligible others count.
        best = 1 + sum(1 for o in others if o["eligibility"] == "eligible" and o["lo"] > e["hi"])
        # Worst case: this candidate at its supported score, every other candidate that could be eligible at its possible score.
        worst = 1 + sum(1 for o in others if o["hi"] > e["lo"])
        e["best_rank"], e["worst_rank"] = best, worst
        if best > k:
            e["shortlist_status"], e["status_reason"] = "robust_out", f"Even at its possible score ({e['hi']:.1f}) it cannot reach the top {k}."
        elif e["eligibility"] == "eligible" and worst <= k:
            e["shortlist_status"], e["status_reason"] = "robust_in", f"In the top {k} under every resolution of the open information."
        else:
            why = []
            if e["eligibility"] == "unresolved":
                why.append("eligibility is not established")
            if worst > k and e["hi"] > e["lo"]:
                why.append(f"its own range ({e['lo']:.1f}–{e['hi']:.1f}) crosses the cut-off")
            elif worst > k:
                why.append("other candidates' open information could overtake it")
            e["shortlist_status"] = "uncertain"
            e["status_reason"] = f"Could rank anywhere from {best} to {worst}: " + " and ".join(why) + "."
    _prioritise_gaps(ordered, pool, k)
    return ordered


def _in_top_k(score, cid, pool, k):
    ahead = sum(1 for o in pool if o["candidate_id"] != cid and o["lo"] > score)
    return ahead < k


def _prioritise_gaps(ordered, pool, k):
    for e in ordered:
        for g in e["gaps"]:
            g["decisive"], g["impact"] = False, []
            if e["eligibility"] == "ineligible":
                g["priority"], g["priority_label"] = 4, "Not pursued: candidate is ineligible on documented evidence"
                continue
            if g["type"] == "eligibility":
                could_be_in = e["best_rank"] is not None and e["best_rank"] <= k
                if e["provisional_shortlist"]:
                    g["impact"].append("If not met, the candidate leaves the shortlist")
                if could_be_in and not e["provisional_shortlist"]:
                    g["impact"].append("If met, the candidate could enter the shortlist")
                if could_be_in:
                    g["decisive"] = True
                    g["priority"], g["priority_label"] = 1, "Eligibility of a shortlist contender"
                else:
                    g["priority"], g["priority_label"] = 4, "Not pursued: cannot reach the shortlist even if met"
                continue
            up = e["lo"] + g["width"]
            if not e["provisional_shortlist"] and _in_top_k(up, e["candidate_id"], pool, k):
                g["decisive"] = True
                g["impact"].append(f"Alone, it could lift the candidate from {e['lo']:.1f} to {up:.1f} and into the top {k}")
                g["priority"], g["priority_label"] = 2, "Could change the shortlist on its own"
            elif e["shortlist_status"] == "uncertain" and g["width"] > 0:
                g["priority"], g["priority_label"] = 3, "Could change the shortlist together with other gaps"
            else:
                g["priority"], g["priority_label"] = 4, ("Not pursued: shortlist decision is robust" if e["shortlist_status"] in ("robust_in", "robust_out") else "Not pursued: no effect on the shortlist")
        e["gaps"].sort(key=lambda g: (g["priority"], -g["width"]))


def run(profiles, template):
    """profiles: {candidate_id: profile}. Returns ranked evaluations."""
    evals = [evaluate_candidate(cid, p, template) for cid, p in profiles.items()]
    return rank(evals, int(template.get("shortlist_size", 5)))


# --------------------------------------------------------------------------------------------
# Comparison between two parameter settings and sensitivity analysis
# --------------------------------------------------------------------------------------------
def compare(profiles, template_a, template_b, names=None):
    A = {e["candidate_id"]: e for e in run(profiles, template_a)}
    B = {e["candidate_id"]: e for e in run(profiles, template_b)}
    crit_names = list(CRITERIA)
    mean_delta = {}
    for c in crit_names:
        ds = [B[i]["criteria"][c]["contrib_lo"] - A[i]["criteria"][c]["contrib_lo"] for i in A]
        mean_delta[c] = sum(ds) / len(ds) if ds else 0
    changes = []
    for cid in A:
        a, b = A[cid], B[cid]
        rel = []
        for c in crit_names:
            d = b["criteria"][c]["contrib_lo"] - a["criteria"][c]["contrib_lo"]
            rel.append((c, d - mean_delta[c], d, a["criteria"][c]["lo"], b["criteria"][c]["lo"],
                        a["criteria"][c]["weight"], b["criteria"][c]["weight"]))
        rel.sort(key=lambda x: -abs(x[1]))
        why = []
        for c, r, d, sa, sb, wa, wb in rel[:2]:
            if abs(r) < 0.05:
                continue
            avg = sum(A[i]["criteria"][c]["lo"] for i in A) / len(A)
            parts = []
            if wa != wb:
                parts.append(f"{c.replace('_', ' ')} weight {wa:g} → {wb:g}")
            if abs(sa - sb) > 0.01:
                parts.append(f"its {c.replace('_', ' ')} score changed {sa:.1f} → {sb:.1f}")
            pos = "above" if sb >= avg else "below"
            why.append(f"{'; '.join(parts) or c.replace('_', ' ') + ' share changed'} (its score {sb:.1f}/10 is {pos} the average {avg:.1f}) → {r:+.1f} points relative to others")
        changes.append({
            "candidate_id": cid, "name": a.get("name"), "rank_a": a["rank"], "rank_b": b["rank"], "move": a["rank"] - b["rank"],
            "lo_a": a["lo"], "lo_b": b["lo"], "hi_a": a["hi"], "hi_b": b["hi"],
            "status_a": a["shortlist_status"], "status_b": b["shortlist_status"], "why": why,
        })
    changes.sort(key=lambda c: c["rank_b"])
    return {"changes": changes}


def kendall_tau(order_a, order_b):
    pos = {c: i for i, c in enumerate(order_b)}
    items = [c for c in order_a if c in pos]
    n = len(items)
    if n < 2:
        return 1.0
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            s = (pos[items[i]] - pos[items[j]])
            if s < 0:
                conc += 1
            elif s > 0:
                disc += 1
    return (conc - disc) / (n * (n - 1) / 2)


def sensitivity(profiles, template, draws=200, spread=0.2, seed=7):
    """Random weight perturbations (each weight x U[1-spread, 1+spread]) and one-at-a-time sweeps."""
    import random
    rnd = random.Random(seed)
    base = run(profiles, template)
    k = int(template.get("shortlist_size", 5))
    base_order = [e["candidate_id"] for e in base]
    base_short = {e["candidate_id"] for e in base if e["provisional_shortlist"]}
    # Criterion scores do not depend on weights, so evaluate once and re-weight.
    evals = {e["candidate_id"]: e for e in base}
    crit_names = list(CRITERIA)
    freq = {cid: 0 for cid in evals}
    taus, jacc = [], []

    def order_for(weights):
        ws = sum(weights.values()) or 1
        scored = []
        for cid, e in evals.items():
            s = sum(weights[c] / ws * e["criteria"][c]["lo"] * 10 for c in crit_names)
            scored.append((cid, s, e["eligibility"]))
        el = sorted([x for x in scored if x[2] != "ineligible"], key=lambda x: -x[1])
        inel = sorted([x for x in scored if x[2] == "ineligible"], key=lambda x: -x[1])
        order = [x[0] for x in el + inel]
        return order, set(x[0] for x in el[:k])

    w0 = {c: float(template["criteria"][c]["weight"]) for c in crit_names}
    for _ in range(draws):
        w = {c: w0[c] * rnd.uniform(1 - spread, 1 + spread) for c in crit_names}
        order, short = order_for(w)
        taus.append(kendall_tau(base_order, order))
        jacc.append(len(short & base_short) / max(1, len(short | base_short)))
        for cid in short:
            freq[cid] += 1
    oat = []
    for c in crit_names:
        row = {"criterion": c, "weight": w0[c]}
        for f in (0.5, 1.5):
            w = dict(w0)
            w[c] = w0[c] * f
            order, short = order_for(w)
            row[f"x{f}"] = {"tau": round(kendall_tau(base_order, order), 3),
                            "entered": sorted(evals[x]["name"] or x for x in short - base_short),
                            "left": sorted(evals[x]["name"] or x for x in base_short - short)}
        oat.append(row)
    n = len(taus) or 1
    return {
        "draws": draws, "spread": spread,
        "kendall_tau_mean": round(sum(taus) / n, 3), "kendall_tau_min": round(min(taus) if taus else 1, 3),
        "shortlist_jaccard_mean": round(sum(jacc) / n, 3),
        "shortlist_frequency": sorted([{"candidate_id": cid, "name": evals[cid]["name"], "freq": round(freq[cid] / n, 3),
                                        "in_base": cid in base_short} for cid in evals], key=lambda x: -x["freq"]),
        "one_at_a_time": oat,
    }
