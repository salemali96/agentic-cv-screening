"""Canonical candidate profile: helpers for possible values, durations and evidence support.

A field can be in one of three states:
  * known       - a single value stated in the documents (or verified externally)
  * conflicting - several values from different documents or sources (kept, never silently resolved)
  * unknown     - not stated (None). An unknown is never treated as a negative fact.
"""
from itertools import product

from .config import CURRENT_YEAR

LIST_SECTIONS = ["degrees", "positions", "teaching", "leadership", "publications", "grants", "supervision"]


def empty_profile():
    p = {"name": None, "orcid": None, "title_prefix": None, "current_position": None,
         "indicators": {"phd_indicated": False, "notes": []}, "conflicts": []}
    for s in LIST_SECTIONS:
        p[s] = []
    return p


def attach_alternatives(profile):
    """Index conflicts onto items as item['_alts'][field] = [values...] so scoring can enumerate them."""
    for s in LIST_SECTIONS:
        for it in profile.get(s, []):
            it["_alts"] = {}
    for c in profile.get("conflicts", []):
        sec, idx, field = c.get("item_type"), c.get("item_index"), c.get("field")
        if sec in LIST_SECTIONS and isinstance(idx, int) and 0 <= idx < len(profile.get(sec, [])) and field:
            vals = [v.get("value") for v in c.get("values", [])]
            vals = [_coerce(field, v) for v in vals]
            item = profile[sec][idx]
            item["_alts"].setdefault(field, [])
            for v in vals:
                if v not in item["_alts"][field]:
                    item["_alts"][field].append(v)
    return profile


def _coerce(field, v):
    if field in ("start", "end", "year", "expected_year", "count"):
        if isinstance(v, str) and v.strip().lower() in ("present", "current", "now", "ongoing"):
            return "present"
        try:
            return int(str(v).strip()[:4]) if v is not None else None
        except (TypeError, ValueError):
            return None
    return v


def values(item, field):
    """All possible values of a field. [None] means unknown."""
    alts = (item.get("_alts") or {}).get(field)
    if alts:
        vs = list(alts)
        base = item.get(field)
        if base is not None and base not in vs:
            vs.append(base)
        return vs
    return [item.get(field)]


def has_conflict(item, field=None):
    alts = item.get("_alts") or {}
    if field:
        return len(values(item, field)) > 1
    return any(len(values(item, f)) > 1 for f in alts)


def year_of(v):
    if v == "present":
        return CURRENT_YEAR
    return v


def duration_bounds(item, unc):
    """(lo, hi, status) in years for an item with start/end. status: clear | conflict | partial | missing."""
    starts, ends = values(item, "start"), values(item, "end")
    lo_u, hi_u = float(unc.get("undated_role_min_years", 0)), float(unc.get("undated_role_max_years", 4))
    known_s = [year_of(s) for s in starts if s is not None]
    known_e = [year_of(e) for e in ends if e is not None]
    if known_s and known_e and None not in starts and None not in ends:
        durs = [max(e - s, 0.5) if e >= s else 0.0 for s, e in product(known_s, known_e)]
        status = "conflict" if len(durs) > 1 and min(durs) != max(durs) else "clear"
        return min(durs), max(durs), status
    if known_s and not known_e:
        # start known, end not stated: anywhere from the minimum up to the present
        return lo_u, max(lo_u, CURRENT_YEAR - min(known_s)), "partial"
    if known_e and not known_s:
        return lo_u, hi_u, "partial"
    return lo_u, hi_u, "missing"


def supported(item, unc):
    """A fact supports the 'supported' score only if its evidence was found in a document or verified externally."""
    ev = item.get("evidence") or []
    if any(e.get("check") in ("exact", "approx", "external") for e in ev):
        return True
    if unc.get("unverified_quote_counts") and ev:
        return True
    return False


def evidence_list(item):
    return [e for e in (item.get("evidence") or []) if e.get("quote")]


def matches_any(text, keywords):
    t = (text or "").lower()
    return any(k.lower() in t for k in keywords)


def label_for(section, item):
    if section == "degrees":
        lvl = {"phd": "PhD", "masters": "Master's", "bachelors": "Bachelor's"}.get(item.get("level"), item.get("level") or "Degree")
        return f"{lvl}{' in ' + item['field'] if item.get('field') else ''}{', ' + item['institution'] if item.get('institution') else ''}"
    if section == "publications":
        return item.get("title") or "Untitled publication"
    if section == "grants":
        return item.get("title") or item.get("funder") or "Grant"
    if section == "teaching":
        return item.get("course") or "Teaching"
    if section in ("positions", "leadership"):
        t = item.get("title") or item.get("role") or "Role"
        return f"{t}{', ' + item['organisation'] if item.get('organisation') else ''}"
    if section == "supervision":
        return f"{item.get('level') or 'Research'} student supervision"
    return section
