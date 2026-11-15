"""External verification against an approved list of scholarly sources.

Process for each prioritised gap (see pipeline.resolve):
  1. Query only the sources the committee has approved for this position.
  2. Check the record belongs to this applicant (ORCID iD, or full name plus a shared affiliation).
     A record that fails the identity check is logged and never used.
  3. Record every retrieved claim with its evidence, source, URL, retrieval date and identity basis.
  4. Fill a value only where the documents are silent. If the source disagrees with a document,
     add a conflict; never overwrite.
  5. If nothing is found, the gap stays 'not established'.

Transport is 'live' (real HTTP) or 'fixture' (recorded responses, used for the synthetic set and tests).
"""
import datetime as dt
import json
import re
from difflib import SequenceMatcher
from urllib.parse import quote_plus

import httpx

from . import config

SOURCES = {
    "crossref": "Crossref (publisher metadata)",
    "openalex": "OpenAlex (scholarly index)",
    "orcid_works": "ORCID public record: works",
    "orcid_education": "ORCID public record: education",
    "orcid_employment": "ORCID public record: employment",
}


class Transport:
    def __init__(self, mode="fixture"):
        self.mode = mode
        self._fixtures = None

    def get_json(self, url, headers=None):
        if self.mode == "fixture":
            if self._fixtures is None:
                try:
                    self._fixtures = json.loads(config.FIXTURES_PATH.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    self._fixtures = {}
            return self._fixtures.get(url)
        h = {"User-Agent": "cvscreen-research-prototype" + (f" (mailto:{config.CONTACT_EMAIL})" if config.CONTACT_EMAIL else "")}
        h.update(headers or {})
        r = httpx.get(url, headers=h, timeout=30, follow_redirects=True)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def title_similarity(a, b):
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _name_parts(full):
    toks = [t for t in re.split(r"[\s.]+", full or "") if t and t.lower() not in ("dr", "prof", "phd")]
    if not toks:
        return "", ""
    return toks[0].lower(), toks[-1].lower()


def _orgs(profile):
    out = set()
    for sec, key in (("positions", "organisation"), ("teaching", "institution"), ("degrees", "institution"), ("leadership", "organisation")):
        for it in profile.get(sec, []):
            if it.get(key):
                out.add(_norm(it[key]))
    return out


def identity_check(profile, authors, affiliations=None):
    """authors: [{given, family, orcid}]. Returns (result, basis) with result match | uncertain | mismatch."""
    given, family = _name_parts(profile.get("name"))
    cand_orcid = (profile.get("orcid") or "").strip()
    fam_hits = [a for a in authors if (a.get("family") or "").lower() == family]
    if cand_orcid:
        for a in authors:
            if a.get("orcid") and a["orcid"].endswith(cand_orcid):
                return "match", [f"ORCID iD {cand_orcid} is listed on the record"]
        for a in fam_hits:
            if a.get("orcid") and not a["orcid"].endswith(cand_orcid):
                return "mismatch", [f"author {a.get('given')} {a.get('family')} has a different ORCID iD ({a['orcid'].split('/')[-1]})"]
    if not fam_hits:
        return "mismatch", [f"no author with surname '{family.title()}' on the record"]
    orgs = _orgs(profile)
    shared = [x for x in (affiliations or []) if any(o and (o in _norm(x) or _norm(x) in o) for o in orgs)]
    for a in fam_hits:
        g = (a.get("given") or "").lower().strip(". ")
        if not g:
            continue
        if len(g) > 2 and g.split()[0] != given:
            return "mismatch", [f"same surname but different first name ({a.get('given')} {a.get('family')})"]
        if len(g) > 2 and shared:
            return "match", [f"full name {a.get('given')} {a.get('family')} matches", f"shared affiliation: {shared[0]}"]
        if len(g) > 2:
            return "uncertain", [f"full name matches but no shared affiliation or ORCID iD"]
        if g[0] == given[:1] and shared:
            return "uncertain", [f"initial and surname match ({a.get('given')} {a.get('family')}), shared affiliation {shared[0]}"]
    return "uncertain", ["only the surname and initial match"]


# ------------------------------------------------------------------------------------------------
# Source adapters: each returns a list of normalised records
# ------------------------------------------------------------------------------------------------
def crossref_search(tr, title, family):
    url = f"https://api.crossref.org/works?query.bibliographic={quote_plus(title)}&query.author={quote_plus(family)}&rows=3"
    j = tr.get_json(url) or {}
    out = []
    for it in (j.get("message") or {}).get("items", []):
        authors = [{"given": a.get("given"), "family": a.get("family"), "orcid": a.get("ORCID")} for a in it.get("author", [])]
        affs = [af.get("name") for a in it.get("author", []) for af in a.get("affiliation", []) if af.get("name")]
        year = None
        for k in ("published-print", "published-online", "issued"):
            dp = (it.get(k) or {}).get("date-parts")
            if dp and dp[0] and dp[0][0]:
                year = dp[0][0]
                break
        typ = {"journal-article": "journal", "proceedings-article": "conference", "book": "book", "book-chapter": "chapter", "posted-content": "preprint"}.get(it.get("type"), "other")
        out.append({"source": "crossref", "url": f"https://doi.org/{it.get('DOI')}" if it.get("DOI") else url, "query_url": url,
                    "title": (it.get("title") or [""])[0], "venue": (it.get("container-title") or [None])[0], "year": year,
                    "type": typ, "doi": it.get("DOI"), "authors": authors, "affiliations": affs})
    return out


def openalex_search(tr, title, family):
    url = f"https://api.openalex.org/works?search={quote_plus(title)}&per-page=3"
    j = tr.get_json(url) or {}
    out = []
    for it in j.get("results", []):
        authors, affs = [], []
        for a in it.get("authorships", []):
            name = (a.get("author") or {}).get("display_name") or ""
            g, f = (name.rsplit(" ", 1) + [""])[:2] if " " in name else ("", name)
            authors.append({"given": g, "family": f, "orcid": (a.get("author") or {}).get("orcid")})
            affs += [i.get("display_name") for i in a.get("institutions", []) if i.get("display_name")]
        src = ((it.get("primary_location") or {}).get("source") or {})
        typ = {"article": "journal", "proceedings-article": "conference", "book": "book", "book-chapter": "chapter", "preprint": "preprint"}.get(it.get("type"), "other")
        if typ == "journal" and src.get("type") == "conference":
            typ = "conference"
        out.append({"source": "openalex", "url": it.get("id") or url, "query_url": url, "title": it.get("title") or it.get("display_name"),
                    "venue": src.get("display_name"), "year": it.get("publication_year"), "type": typ,
                    "doi": (it.get("doi") or "").replace("https://doi.org/", "") or None, "authors": authors, "affiliations": affs})
    return out


def orcid_works(tr, orcid):
    url = f"https://pub.orcid.org/v3.0/{orcid}/works"
    j = tr.get_json(url, {"Accept": "application/json"}) or {}
    out = []
    for g in j.get("group", []):
        s = (g.get("work-summary") or [{}])[0]
        year = ((s.get("publication-date") or {}).get("year") or {}).get("value")
        typ = {"journal-article": "journal", "conference-paper": "conference", "book": "book", "book-chapter": "chapter", "preprint": "preprint"}.get(s.get("type"), "other")
        doi = None
        for x in ((s.get("external-ids") or {}).get("external-id") or []):
            if x.get("external-id-type") == "doi":
                doi = x.get("external-id-value")
        out.append({"source": "orcid_works", "url": f"https://orcid.org/{orcid}", "query_url": url,
                    "title": ((s.get("title") or {}).get("title") or {}).get("value"), "venue": (s.get("journal-title") or {}).get("value"),
                    "year": int(year) if year else None, "type": typ, "doi": doi,
                    "authors": [{"given": None, "family": None, "orcid": f"https://orcid.org/{orcid}"}], "affiliations": [], "orcid_record": True})
    return out


def orcid_affiliations(tr, orcid, kind):
    url = f"https://pub.orcid.org/v3.0/{orcid}/{kind}"
    j = tr.get_json(url, {"Accept": "application/json"}) or {}
    out = []
    key = "education-summary" if kind == "educations" else "employment-summary"
    for g in j.get("affiliation-group", []):
        for s in g.get("summaries", []):
            e = s.get(key) or {}
            yr = lambda d: int(((e.get(d) or {}).get("year") or {}).get("value")) if ((e.get(d) or {}).get("year") or {}).get("value") else None
            out.append({"source": f"orcid_{'education' if kind == 'educations' else 'employment'}", "url": f"https://orcid.org/{orcid}", "query_url": url,
                        "role": e.get("role-title"), "department": e.get("department-name"), "organisation": (e.get("organization") or {}).get("name"),
                        "start": yr("start-date"), "end": yr("end-date"), "orcid_record": True})
    return out


# ------------------------------------------------------------------------------------------------
# Gap handlers
# ------------------------------------------------------------------------------------------------
def _now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _prov(gap, rec, claim, identity, basis, outcome, fields=None):
    return {"gap_id": gap["id"], "claim": claim, "source": rec.get("source") if rec else None,
            "source_label": SOURCES.get(rec.get("source")) if rec else None, "url": rec.get("url") if rec else None,
            "query_url": rec.get("query_url") if rec else None, "retrieved_at": _now(), "identity": identity, "identity_basis": basis,
            "outcome": outcome, "fields": fields or {}, "record": {k: rec.get(k) for k in ("title", "venue", "year", "type", "doi", "role", "organisation", "start", "end") if rec and rec.get(k) is not None}}


def verify_publication(profile, gap, tr, enabled, recs=None, min_similarity=0.9):
    """Fill missing year/venue/type for one listed publication; flag disagreements.

    recs: records already retrieved (e.g. by the agent's own search query); when None, the default
    title + surname query is run against the enabled sources. The identity and fill rules are the same either way."""
    i = gap["item_index"]
    pub = profile["publications"][i]
    _, family = _name_parts(profile.get("name"))
    provs, patches = [], []
    if recs is None:
        recs = []
        if "crossref" in enabled:
            recs += crossref_search(tr, pub.get("title") or "", family)
        if "openalex" in enabled:
            recs += openalex_search(tr, pub.get("title") or "", family)
        if "orcid_works" in enabled and profile.get("orcid"):
            recs += orcid_works(tr, profile["orcid"])
    recs = [r for r in recs if r.get("title") and title_similarity(r["title"], pub.get("title")) >= min_similarity]
    if not recs:
        provs.append(_prov(gap, {"source": ",".join(s for s in enabled if s in ("crossref", "openalex", "orcid_works"))}, f"Publication '{pub.get('title')}'",
                           "n/a", ["no record with a matching title"], "not_found"))
        return provs, patches
    used = False
    for r in recs:
        if r.get("orcid_record"):
            ident, basis = "match", [f"listed on the applicant's own ORCID record ({profile.get('orcid')})"]
        else:
            ident, basis = identity_check(profile, r["authors"], r.get("affiliations"))
        if ident != "match":
            provs.append(_prov(gap, r, f"Publication '{pub.get('title')}'", ident, basis, "rejected" if ident == "mismatch" else "needs_human_check"))
            continue
        fills, conflicts = {}, []
        for f in ("year", "venue", "type"):
            if r.get(f) is None:
                continue
            if pub.get(f) is None and f not in fills:
                fills[f] = r[f]
            elif pub.get(f) is not None and str(pub.get(f)).lower() != str(r[f]).lower() and f != "venue":
                conflicts.append(f)
        prov = _prov(gap, r, f"Publication '{pub.get('title')}'", ident, basis, "filled" if fills else ("conflict" if conflicts else "confirmed"), fills)
        provs.append(prov)
        quote = f"{SOURCES[r['source']]}: {r.get('title')} ({r.get('venue') or 'venue n/a'}, {r.get('year') or 'year n/a'})"
        evid = {"quote": quote, "doc": r["source"], "check": "external", "source": "external", "url": r.get("url"), "provenance_id": prov.get("id")}
        if not used:
            for f, v in fills.items():
                patches.append({"op": "set", "section": "publications", "index": i, "field": f, "value": v, "evidence": evid, "provenance": prov})
                if f == "type" and v in ("journal", "conference", "book", "chapter"):
                    patches.append({"op": "set", "section": "publications", "index": i, "field": "peer_reviewed", "value": True, "provenance": prov})
            used = used or bool(fills)
        for f in conflicts:
            patches.append({"op": "conflict", "provenance": prov, "conflict": {
                "topic": f"Publication {f}: '{pub.get('title')}'", "item_type": "publications", "item_index": i, "field": f, "source": "external",
                "values": [{"value": pub.get(f), "doc": "documents", "quote": (pub.get("evidence") or [{}])[0].get("quote")},
                           {"value": r[f], "doc": r["source"], "quote": quote, "url": r.get("url")}]}})
    return provs, patches


def verify_degree(profile, gap, tr, enabled):
    provs, patches = [], []
    if "orcid_education" not in enabled:
        return provs, patches
    if not profile.get("orcid"):
        provs.append(_prov(gap, {"source": "orcid_education"}, "Doctoral degree", "n/a", ["no ORCID iD in the documents, so the record cannot be identified safely"], "not_attempted"))
        return provs, patches
    recs = orcid_affiliations(tr, profile["orcid"], "educations")
    phd = [r for r in recs if re.search(r"\b(phd|ph\.d|doctor|doctorate|dphil)\b", (r.get("role") or "").lower())]
    if not phd:
        provs.append(_prov(gap, {"source": "orcid_education", "url": f"https://orcid.org/{profile['orcid']}"}, "Doctoral degree", "match",
                           ["applicant's own ORCID record"], "not_found"))
        return provs, patches
    r = phd[0]
    prov = _prov(gap, r, "Doctoral degree", "match", ["applicant's own ORCID record"], "filled", {"level": "phd", "year": r.get("end")})
    provs.append(prov)
    field = r.get("department") or (r.get("role") or "").split(" in ")[-1] if " in " in (r.get("role") or "") else r.get("department")
    patches.append({"op": "add", "section": "degrees", "provenance": prov, "item": {
        "level": "phd", "field": field, "institution": r.get("organisation"), "year": r.get("end"), "status": "completed" if r.get("end") else None,
        "expected_year": None, "evidence": [{"quote": f"ORCID education: {r.get('role')}, {r.get('organisation')}, {r.get('end') or 'no end date'}",
                                             "doc": "orcid_education", "check": "external", "source": "external", "url": r.get("url")}]}})
    return provs, patches


def verify_role_dates(profile, gap, tr, enabled):
    provs, patches = [], []
    if "orcid_employment" not in enabled:
        return provs, patches
    if not profile.get("orcid"):
        provs.append(_prov(gap, {"source": "orcid_employment"}, gap["label"], "n/a", ["no ORCID iD in the documents"], "not_attempted"))
        return provs, patches
    sec, i = gap["section"], gap["item_index"]
    item = profile[sec][i]
    recs = orcid_affiliations(tr, profile["orcid"], "employments")
    title = (item.get("title") or item.get("role") or item.get("course") or "")
    best = max(recs, key=lambda r: title_similarity(r.get("role") or "", title), default=None)
    if not best or title_similarity(best.get("role") or "", title) < 0.6:
        provs.append(_prov(gap, {"source": "orcid_employment", "url": f"https://orcid.org/{profile['orcid']}"}, gap["label"], "match", ["applicant's own ORCID record"], "not_found"))
        return provs, patches
    fills = {f: best[f] for f in ("start", "end") if item.get(f) is None and best.get(f) is not None}
    prov = _prov(gap, best, gap["label"], "match", ["applicant's own ORCID record"], "filled" if fills else "confirmed", fills)
    provs.append(prov)
    for f, v in fills.items():
        patches.append({"op": "set", "section": sec, "index": i, "field": f, "value": v, "provenance": prov,
                        "evidence": {"quote": f"ORCID employment: {best.get('role')}, {best.get('organisation')}, {best.get('start')}–{best.get('end') or 'present'}",
                                     "doc": "orcid_employment", "check": "external", "source": "external", "url": best.get("url")}})
    return provs, patches


def spot_check_publications(profile, tr, enabled):
    """For shortlisted applicants with an ORCID iD: compare listed publications with the ORCID record."""
    provs, patches = [], []
    if "orcid_works" not in enabled or not profile.get("orcid"):
        return provs, patches
    recs = orcid_works(tr, profile["orcid"])
    for i, pub in enumerate(profile["publications"]):
        match = max(recs, key=lambda r: title_similarity(r.get("title"), pub.get("title")), default=None)
        if not match or title_similarity(match.get("title"), pub.get("title")) < 0.9:
            continue
        gap = {"id": f"spotcheck:{i}", "label": pub.get("title")}
        diffs = [f for f in ("year",) if pub.get(f) is not None and match.get(f) is not None and pub[f] != match[f]]
        prov = _prov(gap, match, f"Publication '{pub.get('title')}'", "match", ["applicant's own ORCID record"], "conflict" if diffs else "confirmed")
        provs.append(prov)
        for f in diffs:
            patches.append({"op": "conflict", "provenance": prov, "conflict": {
                "topic": f"Publication {f}: '{pub.get('title')}'", "item_type": "publications", "item_index": i, "field": f, "source": "external",
                "values": [{"value": pub[f], "doc": "publications", "quote": (pub.get("evidence") or [{}])[0].get("quote")},
                           {"value": match[f], "doc": "orcid_works", "quote": f"ORCID record lists {match.get('title')} ({match[f]})", "url": match.get("url")}]}})
    return provs, patches


HANDLERS = {
    "publication_details": verify_publication,
    "unsupported_pub": verify_publication,
    "degree_unstated": verify_degree,
    "dates": verify_role_dates,
}


def handler_for(gap):
    if gap["type"] in ("publication_details",) or (gap["type"] in ("unsupported", "conflict") and gap.get("section") == "publications"):
        return verify_publication
    if gap["type"] == "degree_unstated" or (gap["type"] == "eligibility" and gap.get("code") in ("unstated", "implied")):
        return verify_degree
    if gap["type"] == "dates" and gap.get("section") in ("positions", "leadership"):
        return verify_role_dates
    return None
