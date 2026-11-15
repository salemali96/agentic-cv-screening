"""Structured extraction from all of an applicant's documents, with evidence quotes that are checked
against the source text.

The model is told to separate 'stated', 'not stated' and 'conflicting'. Afterwards every quote is
checked deterministically: exact match, close match, or not found. A fact whose quote is not found
does not count toward the supported score.
"""
import re
from difflib import SequenceMatcher

from .llm import complete_json
from .profile import LIST_SECTIONS, empty_profile

SCHEMA = """{
  "name": "string or null",
  "orcid": "ORCID iD if written in the documents, else null",
  "title_prefix": "\\"Dr\\" if the applicant uses the title, else null",
  "current_position": "string or null",
  "degrees": [{"level": "phd|masters|bachelors|other|null", "field": "string or null", "institution": "string or null",
               "year": "int or null (year awarded)", "status": "completed|in_progress|null (null = not stated)",
               "expected_year": "int or null", "evidence": [EVIDENCE]}],
  "positions": [{"title": "...", "organisation": "...", "category": "academic|research|industry|other|null",
                 "start": "int year or null", "end": "int year, \\"present\\", or null", "evidence": [EVIDENCE]}],
  "teaching": [{"course": "...", "institution": "...", "role": "lead|assistant|null", "university": "true|false|null",
                "start": "int or null", "end": "int, \\"present\\" or null", "evidence": [EVIDENCE]}],
  "leadership": [{"role": "...", "organisation": "...", "start": "int or null", "end": "int, \\"present\\" or null", "evidence": [EVIDENCE]}],
  "publications": [{"title": "...", "venue": "string or null", "year": "int or null",
                    "type": "journal|conference|book|chapter|preprint|other|null", "peer_reviewed": "true|false|null",
                    "authors": ["..."] , "doi": "string or null", "evidence": [EVIDENCE]}],
  "grants": [{"title": "...", "funder": "...", "role": "PI|Co-I|null", "amount": "string or null", "year": "int or null", "evidence": [EVIDENCE]}],
  "supervision": [{"level": "phd|masters|undergraduate|null", "status": "completed|ongoing|null", "count": "int or null", "evidence": [EVIDENCE]}],
  "indicators": {"phd_indicated": "true if the documents imply a doctorate without stating one (postdoc post, 'Dr' title, assistant professor), else false",
                 "notes": ["short reasons for phd_indicated"]},
  "conflicts": [{"topic": "what disagrees", "item_type": "degrees|positions|teaching|leadership|publications|grants|supervision",
                 "item_index": "index of the item in that list", "field": "the field that disagrees",
                 "values": [{"value": "...", "doc": "document id", "quote": "exact words"}]}]
}
EVIDENCE = {"quote": "words copied exactly from the document, at most 30 words", "doc": "document id, e.g. cv"}"""

RULES = """Rules:
1. Use only what the documents state. Never guess, infer or fill in a value. If a value is not stated, use null.
   A degree, date, role or count that is not mentioned is NOT the same as one that does not exist: leave it null.
2. Copy every evidence quote exactly, character for character, from the document it comes from, and give that document's id.
3. Read all documents. If two documents (or two places in one document) give different values for the same fact,
   do not choose one: keep the CV's value in the item and add an entry to "conflicts" listing every value with its quote.
4. Dates: "2019 - present" gives start 2019, end "present". "Since 2021" gives start 2021, end "present".
   A role with no dates gets start null and end null. A single year for a role gives start and end null and a conflict-free note is not needed.
5. A PhD marked "in progress", "candidate" or "expected" has status "in_progress" with expected_year if given.
6. Leadership includes directing, chairing, heading, coordinating or leading a unit, programme, lab or committee.
   List it under leadership even if it also appears as a position.
7. Teaching: role "lead" for lecturer, instructor, course or module leader; "assistant" for teaching assistant, tutor or demonstrator.
8. Do not extract age, date of birth, gender, marital status, religion, nationality, photos, or home address.
9. Reply with the JSON object only."""


def build_prompt(docs):
    blocks = []
    for d in docs:
        blocks.append(f'<document id="{d["doc_type"]}" filename="{d["filename"]}">\n{d["text"][:60000]}\n</document>')
    return ("You extract structured facts from an academic job application so a committee can screen it.\n\n"
            f"{RULES}\n\nReturn JSON with this structure:\n{SCHEMA}\n\nDocuments:\n" + "\n\n".join(blocks))


# ------------------------------------------------------------------------------------------------
# Quote verification
# ------------------------------------------------------------------------------------------------
def _norm(s):
    s = (s or "").lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-")
    return re.sub(r"[^a-z0-9؀-ۿ]+", " ", s).strip()


def check_quote(quote, doc_text_norm):
    q = _norm(quote)
    if not q:
        return "missing"
    if q in doc_text_norm:
        return "exact"
    toks = q.split()
    if len(toks) >= 3:
        hits = sum(1 for t in toks if f" {t} " in f" {doc_text_norm} ")
        if hits / len(toks) >= 0.85:
            # confirm the words also appear close together
            window = len(q) + 40
            best = 0.0
            step = max(10, len(q) // 4)
            for i in range(0, max(1, len(doc_text_norm) - len(q) + 1), step):
                best = max(best, SequenceMatcher(None, q, doc_text_norm[i:i + window]).ratio())
                if best > 0.85:
                    break
            if best > 0.8:
                return "approx"
    return "missing"


def verify_evidence(profile, docs):
    """Annotate every evidence quote with check = exact | approx | missing."""
    norm = {d["doc_type"]: _norm(d["text"]) for d in docs}
    allnorm = " ".join(norm.values())
    stats = {"exact": 0, "approx": 0, "missing": 0}
    for sec in LIST_SECTIONS:
        for it in profile.get(sec, []):
            for e in it.get("evidence") or []:
                if e.get("check") == "external" or e.get("source") == "external":
                    continue
                target = norm.get(e.get("doc")) or allnorm
                res = check_quote(e.get("quote"), target)
                if res == "missing" and e.get("doc") in norm:
                    res2 = check_quote(e.get("quote"), allnorm)
                    if res2 != "missing":
                        res = res2
                e["check"] = res
                stats[res] += 1
    for c in profile.get("conflicts", []):
        for v in c.get("values", []):
            v["check"] = check_quote(v.get("quote"), norm.get(v.get("doc")) or allnorm)
    return stats


# ------------------------------------------------------------------------------------------------
# Normalisation of model output
# ------------------------------------------------------------------------------------------------
def _int(v):
    if v is None:
        return None
    if isinstance(v, str) and v.strip().lower() in ("present", "current", "now", "ongoing"):
        return "present"
    m = re.search(r"(19|20)\d{2}", str(v))
    if m:
        return int(m.group(0))
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _enum(v, allowed):
    if v is None:
        return None
    s = str(v).strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {"co_i": "Co-I", "coi": "Co-I", "co_investigator": "Co-I", "pi": "PI", "principal_investigator": "PI",
               "doctorate": "phd", "ph.d.": "phd", "msc": "masters", "master": "masters", "ma": "masters", "bsc": "bachelors",
               "bachelor": "bachelors", "ba": "bachelors", "in_progress": "in_progress", "ongoing": "ongoing", "current": "ongoing"}
    s = aliases.get(s, s)
    for a in allowed:
        if s == a.lower() or s == a:
            return a
    return None


def _bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return {"true": True, "false": False}.get(v.strip().lower())
    return None


def _ev(lst):
    out = []
    for e in lst or []:
        if isinstance(e, str):
            out.append({"quote": e, "doc": None})
        elif isinstance(e, dict) and e.get("quote"):
            out.append({"quote": str(e["quote"])[:400], "doc": e.get("doc")})
    return out


def normalise(raw):
    p = empty_profile()
    raw = raw or {}
    for k in ("name", "orcid", "current_position"):
        p[k] = raw.get(k) or None
    p["title_prefix"] = "Dr" if str(raw.get("title_prefix") or "").lower().startswith("dr") else None
    for d in raw.get("degrees") or []:
        p["degrees"].append({"level": _enum(d.get("level"), ["phd", "masters", "bachelors", "other"]), "field": d.get("field") or None,
                             "institution": d.get("institution") or None, "year": _int(d.get("year")),
                             "status": _enum(d.get("status"), ["completed", "in_progress"]), "expected_year": _int(d.get("expected_year")),
                             "evidence": _ev(d.get("evidence"))})
    for x in raw.get("positions") or []:
        p["positions"].append({"title": x.get("title"), "organisation": x.get("organisation"),
                               "category": _enum(x.get("category"), ["academic", "research", "industry", "other"]),
                               "start": _int(x.get("start")), "end": _int(x.get("end")), "evidence": _ev(x.get("evidence"))})
    for x in raw.get("teaching") or []:
        p["teaching"].append({"course": x.get("course"), "institution": x.get("institution"), "role": _enum(x.get("role"), ["lead", "assistant"]),
                              "university": _bool(x.get("university")), "start": _int(x.get("start")), "end": _int(x.get("end")),
                              "evidence": _ev(x.get("evidence"))})
    for x in raw.get("leadership") or []:
        p["leadership"].append({"role": x.get("role"), "organisation": x.get("organisation"), "start": _int(x.get("start")),
                                "end": _int(x.get("end")), "evidence": _ev(x.get("evidence"))})
    for x in raw.get("publications") or []:
        p["publications"].append({"title": x.get("title"), "venue": x.get("venue") or None, "year": _int(x.get("year")),
                                  "type": _enum(x.get("type"), ["journal", "conference", "book", "chapter", "preprint", "other"]),
                                  "peer_reviewed": _bool(x.get("peer_reviewed")), "authors": x.get("authors") or None,
                                  "doi": x.get("doi") or None, "evidence": _ev(x.get("evidence"))})
    for x in raw.get("grants") or []:
        p["grants"].append({"title": x.get("title"), "funder": x.get("funder"), "role": _enum(x.get("role"), ["PI", "Co-I"]),
                            "amount": x.get("amount"), "year": _int(x.get("year")), "evidence": _ev(x.get("evidence"))})
    for x in raw.get("supervision") or []:
        cnt = x.get("count")
        p["supervision"].append({"level": _enum(x.get("level"), ["phd", "masters", "undergraduate"]),
                                 "status": _enum(x.get("status"), ["completed", "ongoing"]),
                                 "count": cnt if isinstance(cnt, int) else _int(cnt) if cnt and str(cnt).isdigit() else None,
                                 "evidence": _ev(x.get("evidence"))})
    ind = raw.get("indicators") or {}
    p["indicators"] = {"phd_indicated": bool(_bool(ind.get("phd_indicated"))), "notes": [str(n) for n in (ind.get("notes") or [])][:4]}
    for i, c in enumerate(raw.get("conflicts") or []):
        vals = [{"value": v.get("value"), "doc": v.get("doc"), "quote": v.get("quote")} for v in c.get("values") or [] if isinstance(v, dict)]
        if len(vals) >= 2:
            idx = c.get("item_index")
            p["conflicts"].append({"id": f"C{i + 1}", "topic": c.get("topic"), "item_type": c.get("item_type"),
                                   "item_index": idx if isinstance(idx, int) else _int(idx), "field": c.get("field"),
                                   "values": vals, "source": "documents"})
    # If the model used the 'Dr' title but forgot the indicator, record it (it is evidence a PhD may be omitted).
    if p["title_prefix"] == "Dr" and not any(d["level"] == "phd" for d in p["degrees"]):
        p["indicators"]["phd_indicated"] = True
        p["indicators"]["notes"].append("uses the title Dr")
    return p


def extract(docs, offline_key=None, fresh=False):
    prompt = build_prompt(docs)
    raw, meta = complete_json(prompt, "extract", offline_key=offline_key, fresh=fresh)
    profile = normalise(raw)
    stats = verify_evidence(profile, docs)
    return profile, {**meta, "quote_check": stats}
