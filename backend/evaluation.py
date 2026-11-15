"""Evaluation harness: the evidence-aware screening compared with two common baselines on the synthetic applications.

Ground truth: each synthetic application has a hidden truth (`truth.json`): the facts the documents left out.
Scoring the documented profile *plus* that truth with the same rules gives each applicant's true score and eligibility,
and so the true shortlist. Methods only ever see the documents.

Methods
* evidence_aware   - this system: score ranges, three requirement states, robust / uncertain / robust-out shortlist.
* missing_absent   - common point-scoring practice: anything not stated counts as absent, so a required item that is not
                     established makes the applicant ineligible. Same scoring rules, so the difference isolates the
                     handling of missing information.
* keyword          - keyword similarity between the application documents and the job advert (TF-IDF cosine), as in
                     simple ATS keyword matching.
* evidence_aware_clarified - this system after asking ONLY the applicants it flags (clarification requests for
                     priority 1-3 gaps), simulated by revealing their hidden truth.

Metrics (shortlist size k from the template)
* shortlist precision / recall against the true shortlist; Kendall tau of the order against the true order
* wrongful exclusions: truly eligible applicants a method marks ineligible
* for evidence_aware: errors among confident decisions (robust_in not truly in, robust_out truly in),
  share of applicants flagged uncertain, score-range coverage (true score inside [supported, possible]),
  agreement of requirement states with the gold labels, number of applicants who would be asked a question
* optional extraction accuracy when a position's demo applications were extracted by a real model
"""
import json
import math
import re
from collections import Counter

from . import extraction, patches, scoring, template as tmpl
from .config import SYNTHETIC_DIR
from .parsing import clean

REQUIRED_KINDS = None  # filled from the template


# ------------------------------------------------------------------------------------------------
# Data
# ------------------------------------------------------------------------------------------------
def load_cases():
    manifest = json.loads((SYNTHETIC_DIR / "manifest.json").read_text(encoding="utf-8"))
    cases = []
    for m in manifest:
        d = SYNTHETIC_DIR / m["id"]
        docs = [{"doc_type": f.stem, "filename": f.name, "text": clean(f.read_text(encoding="utf-8"))} for f in sorted(d.glob("*.txt"))]
        gold = extraction.normalise(json.loads((d / "gold_profile.json").read_text(encoding="utf-8")))
        extraction.verify_evidence(gold, docs)  # same quote check as a real extraction
        cases.append({
            "id": m["id"], "name": m["name"], "scenario": m["scenario"], "gold": gold, "docs": docs,
            "truth": json.loads((d / "truth.json").read_text(encoding="utf-8")),
            "text": "\n".join(x["text"] for x in docs),
        })
    return cases


# ------------------------------------------------------------------------------------------------
# Keyword baseline (TF-IDF cosine, no external libraries)
# ------------------------------------------------------------------------------------------------
_STOP = set("a an and the of in on for to with by at or as is are be was were from this that it its their our we will "
            "who which have has had at least all any also into than per".split())


def _tokens(text):
    return [w for w in re.findall(r"[a-z][a-z\-]+", text.lower()) if w not in _STOP and len(w) > 2]


def keyword_scores(docs, query):
    """docs: {id: text}. Returns {id: cosine similarity * 100}."""
    toks = {k: Counter(_tokens(v)) for k, v in docs.items()}
    q = Counter(_tokens(query))
    n = len(docs)
    df = Counter(w for c in toks.values() for w in c)
    idf = {w: math.log((1 + n) / (1 + df[w])) + 1 for w in set(df) | set(q)}

    def vec(c):
        return {w: (1 + math.log(f)) * idf[w] for w, f in c.items()}

    qv = vec(q)
    qn = math.sqrt(sum(v * v for v in qv.values())) or 1
    out = {}
    for k, c in toks.items():
        dv = vec(c)
        dn = math.sqrt(sum(v * v for v in dv.values())) or 1
        out[k] = round(100 * sum(qv[w] * dv.get(w, 0) for w in qv) / (qn * dn), 2)
    return out


# ------------------------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------------------------
def _top_k(scores, eligible, k):
    """scores: {id: score}; eligible: set of ids allowed. Ordered ids and the top-k set."""
    order = sorted(scores, key=lambda i: (-(i in eligible), -scores[i], i))
    return order, {i for i in order[:k] if i in eligible}


def _prf(pred, true, acceptable=None):
    """acceptable: the true shortlist plus anyone tied with its last member (either choice is correct)."""
    acc = acceptable or true
    tp = len(pred & acc)
    return {"precision": round(tp / len(pred), 3) if pred else None, "recall": round(min(tp, len(true)) / len(true), 3) if true else None,
            "true_positives": tp}


def _tau(order, true_order):
    return round(scoring.kendall_tau(order, true_order), 3)


# ------------------------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------------------------
def run(template=None, extracted=None):
    """template: scoring template (default: the example position). extracted: optional {demo_id: profile} from a
    real extraction; when given, methods use those profiles and extraction accuracy is reported."""
    t = tmpl.validate_template(template or tmpl.default_template())
    k = int(t["shortlist_size"])
    cases = load_cases()
    names = {c["id"]: c["name"] for c in cases}
    required = [r["id"] for r in t["requirements"] if r["tier"] == "required"]

    documented = {c["id"]: (extracted or {}).get(c["id"], c["gold"]) for c in cases}
    truth_prof = {c["id"]: patches.apply(c["gold"], c["truth"].get("patches")) for c in cases}

    # Ground truth -------------------------------------------------------------------------------
    true_ev = {e["candidate_id"]: e for e in scoring.run(truth_prof, t)}
    true_score = {i: e["lo"] for i, e in true_ev.items()}
    true_elig = {i for i, e in true_ev.items() if e["eligibility"] == "eligible"}
    true_order, true_short = _top_k(true_score, true_elig, k)
    cut = min((true_score[i] for i in true_short), default=None)
    tied = {i for i in true_elig if cut is not None and abs(true_score[i] - cut) < 1e-6}
    acceptable = true_short | tied

    # Evidence-aware --------------------------------------------------------------------------------
    ranked = scoring.run(documented, t)
    ev = {e["candidate_id"]: e for e in ranked}
    ea_order = [e["candidate_id"] for e in ranked]
    ea_short = {i for i, e in ev.items() if e["provisional_shortlist"]}
    status = {i: e["shortlist_status"] for i, e in ev.items()}
    confident_wrong = [names[i] for i, s in status.items()
                       if (s == "robust_in" and i not in acceptable) or (s == "robust_out" and i in true_short - tied)
                       or (s == "ineligible" and i in true_elig)]
    coverage = [i for i in ev if ev[i]["lo"] - 0.01 <= true_score[i] <= ev[i]["hi"] + 0.01]
    flagged = {i for i, e in ev.items() if any(g.get("priority", 9) <= 3 for g in e["gaps"])}

    req_total = req_agree = 0
    req_errors = []
    for c in cases:
        gold = c["truth"].get("gold_requirements") or {}
        got = {r["id"]: r["status"] for r in ev[c["id"]]["requirements"]}
        for rid, g in gold.items():
            if rid in got:
                req_total += 1
                req_agree += got[rid] == g
                if got[rid] != g:
                    req_errors.append(f"{c['name']} {rid}: {got[rid]} (gold {g})")

    ea = {
        "shortlist": _prf(ea_short, true_short, acceptable), "kendall_tau": _tau(ea_order, true_order),
        "wrongful_exclusions": [names[i] for i, e in ev.items() if e["eligibility"] == "ineligible" and i in true_elig],
        "confident_decisions": sum(s in ("robust_in", "robust_out", "ineligible") for s in status.values()),
        "confident_decision_errors": confident_wrong,
        "uncertain": [names[i] for i, s in status.items() if s == "uncertain"],
        "range_coverage": round(len(coverage) / len(ev), 3),
        "outside_range": [f"{names[i]} (true {true_score[i]}, range {ev[i]['lo']}–{ev[i]['hi']})" for i in ev if i not in coverage],
        "requirement_state_accuracy": round(req_agree / req_total, 3) if req_total else None,
        "requirement_state_errors": req_errors,
        "applicants_asked": len(flagged),
    }

    # Evidence-aware after clarifying only the flagged applicants --------------------------------------
    clarified = {i: (truth_prof[i] if i in flagged else documented[i]) for i in documented}
    ranked_c = scoring.run(clarified, t)
    cl_short = {e["candidate_id"] for e in ranked_c if e["provisional_shortlist"]}
    eac = {"shortlist": _prf(cl_short, true_short, acceptable), "kendall_tau": _tau([e["candidate_id"] for e in ranked_c], true_order),
           "applicants_asked": len(flagged), "of": len(cases)}

    # Missing = absent ------------------------------------------------------------------------------------
    ma_elig = {i for i, e in ev.items() if all(r["status"] == "met" for r in e["requirements"] if r["id"] in required)}
    ma_order, ma_short = _top_k({i: e["lo"] for i, e in ev.items()}, ma_elig, k)
    ma = {"shortlist": _prf(ma_short, true_short, acceptable), "kendall_tau": _tau(ma_order, true_order),
          "wrongful_exclusions": sorted(names[i] for i in true_elig - ma_elig)}

    # Keyword similarity ------------------------------------------------------------------------------------
    advert = t["position"]["description"] + "\n" + "\n".join(r["text"] for r in t["requirements"])
    kw = keyword_scores({c["id"]: c["text"] for c in cases}, advert)
    kw_order, kw_short = _top_k(kw, set(kw), k)
    kwr = {"shortlist": _prf(kw_short, true_short, acceptable), "kendall_tau": _tau(kw_order, true_order),
           "shortlisted_but_truly_ineligible": sorted(names[i] for i in kw_short - true_elig)}

    out = {
        "status": "ok", "applications": len(cases), "shortlist_size": k,
        "true_shortlist": sorted(names[i] for i in true_short),
        "tied_at_cutoff": sorted(names[i] for i in tied) if len(tied) > 1 else [],
        "methods": {"evidence_aware": ea, "evidence_aware_clarified": eac, "missing_absent": ma, "keyword": kwr},
        "per_applicant": [{"id": i, "name": names[i], "true_score": true_score[i], "truly_eligible": i in true_elig,
                           "truly_shortlisted": i in true_short, "supported": ev[i]["lo"], "possible": ev[i]["hi"],
                           "status": status[i], "keyword_score": kw[i]} for i in true_order],
    }
    if extracted:
        out["extraction"] = extraction_accuracy(extracted, {c["id"]: c["gold"] for c in cases})
    return out


# ------------------------------------------------------------------------------------------------
# Extraction accuracy (real model vs gold extraction)
# ------------------------------------------------------------------------------------------------
def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _match(items, gold_items, key):
    used, hits = set(), []
    for g in gold_items:
        best = None
        for j, it in enumerate(items):
            if j not in used and _norm(it.get(key)) and _norm(it.get(key))[:40] == _norm(g.get(key))[:40]:
                best = j
                break
        if best is not None:
            used.add(best)
            hits.append((items[best], g))
    return hits


FIELDS = {"degrees": ("level", ["year", "field"]), "positions": ("title", ["start", "end"]), "publications": ("title", ["year", "type"]),
          "teaching": ("course", ["start", "end", "role"]), "grants": ("title", ["role", "year"])}


def extraction_accuracy(extracted, gold):
    """Item recall and precision per section, and field accuracy on matched items."""
    rows = {}
    for sec, (key, fields) in FIELDS.items():
        g_n = p_n = m_n = f_ok = f_n = 0
        for i, gp in gold.items():
            if i not in extracted:
                continue
            gi, pi = gp.get(sec) or [], extracted[i].get(sec) or []
            hits = _match(pi, gi, key)
            g_n, p_n, m_n = g_n + len(gi), p_n + len(pi), m_n + len(hits)
            for it, g in hits:
                for f in fields:
                    if f in g:
                        f_n += 1
                        f_ok += _norm(it.get(f)) == _norm(g.get(f))
        rows[sec] = {"gold_items": g_n, "extracted_items": p_n, "recall": round(m_n / g_n, 3) if g_n else None,
                     "precision": round(m_n / p_n, 3) if p_n else None, "field_accuracy": round(f_ok / f_n, 3) if f_n else None}
    return rows


def report(res):
    """Plain-text summary for the command line."""
    m = res["methods"]
    L = [f"Evaluation on {res['applications']} synthetic applications, shortlist size {res['shortlist_size']}",
         f"True shortlist: {', '.join(res['true_shortlist'])}"
         + (f" (tied at the cut-off, either counts: {', '.join(res['tied_at_cutoff'])})" if res.get("tied_at_cutoff") else ""), "",
         f"{'Method':<34}{'Shortlist P':>12}{'Recall':>8}{'Kendall τ':>11}{'Wrongly excluded':>18}"]
    for key, label in (("keyword", "Keyword similarity (ATS-style)"), ("missing_absent", "Missing = absent (point scoring)"),
                       ("evidence_aware", "Evidence-aware (documents only)"), ("evidence_aware_clarified", "Evidence-aware + clarifications")):
        x = m[key]
        we = x.get("wrongful_exclusions")
        L.append(f"{label:<34}{x['shortlist']['precision']!s:>12}{x['shortlist']['recall']!s:>8}{x['kendall_tau']!s:>11}"
                 f"{(str(len(we)) if we is not None else '-'):>18}")
    ea = m["evidence_aware"]
    L += ["", "Evidence-aware details:",
          f"  confident decisions: {ea['confident_decisions']} of {res['applications']}, errors among them: {len(ea['confident_decision_errors'])}"
          + (f" ({', '.join(ea['confident_decision_errors'])})" if ea["confident_decision_errors"] else ""),
          f"  flagged uncertain: {len(ea['uncertain'])} ({', '.join(ea['uncertain'])})",
          f"  true score inside the score range: {ea['range_coverage']:.0%}"
          + (f" (outside: {'; '.join(ea['outside_range'])})" if ea["outside_range"] else ""),
          f"  requirement states matching gold labels: {ea['requirement_state_accuracy']:.0%}",
          f"  applicants who would be asked a question: {ea['applicants_asked']} of {res['applications']}",
          f"  missing = absent wrongly excludes: {', '.join(m['missing_absent']['wrongful_exclusions']) or 'nobody'}",
          f"  keyword matching shortlists truly ineligible: {', '.join(m['keyword']['shortlisted_but_truly_ineligible']) or 'nobody'}"]
    if res.get("extraction"):
        L += ["", "Extraction accuracy (model vs gold):"]
        L += [f"  {s:<13} recall {r['recall']}  precision {r['precision']}  field accuracy {r['field_accuracy']}" for s, r in res["extraction"].items()]
    return "\n".join(L)
