"""Targeted clarification requests: one short message per applicant, asking only about gaps that
could change eligibility or the shortlist."""


def _q(g):
    r = g.get("request") or {}
    k = r.get("kind") or g["type"]
    item = r.get("item") or g.get("label")
    if g["type"] == "eligibility":
        code = r.get("code")
        req = r.get("requirement")
        if code in ("unstated", "implied") and "phd" in (req or "").lower():
            return ("Your application does not state a doctoral degree. Please confirm whether you hold a PhD (or equivalent), "
                    "its field, the awarding institution and the year it was awarded.")
        if code == "unstated":
            return f"Your application does not mention the following, which is an essential requirement: {req}. Please tell us whether you meet it, with dates."
        if code == "in_progress":
            return "Please confirm the expected date of your PhD award and whether it will be awarded before the start date."
        if code == "field_unstated":
            return "Please state the field (discipline) of your PhD."
        if code == "incomplete":
            return f"To check the essential requirement '{req}', we need the missing details listed below."
        return f"Please provide information showing whether you meet: {req}."
    if k == "degree_unstated":
        return "Please confirm whether you hold a PhD, with field, institution and year awarded."
    if k == "publication_details":
        miss = ", ".join(r.get("missing") or ["details"])
        return f"For the publication '{item}', please give the {miss} (and a DOI if available)."
    if k == "dates":
        return f"Your application lists '{item}' without complete dates. Please give the start and end month and year."
    if k == "grant_role":
        return f"For the grant '{item}', please state your role (Principal Investigator or Co-Investigator)."
    if k == "supervision_details":
        return "Please state how many students you have supervised, at which level (PhD, MSc), and whether they completed."
    if k == "conflict":
        cs = r.get("conflict") or []
        if cs:
            c = cs[0]
            vals = " and ".join(f"'{v.get('value')}' ({v.get('doc')})" for v in c.get("values", []))
            return f"Your documents give different information for {c.get('topic', 'one item').lower()}: {vals}. Please confirm which is correct."
        return f"Your documents disagree about '{item}'. Please confirm the correct details."
    if k == "unsupported":
        return f"We could not find supporting text for '{item}' in your documents. Please point us to it or provide details."
    if k == "teaching_unstated":
        return "Please describe your university teaching: courses, institution, your role and dates."
    return f"Please provide more detail about '{item}'."


def build_requests(evaluation, position_title, max_priority=3):
    """Return the clarification message for one candidate, or None if no gap is worth asking about."""
    gaps = [g for g in evaluation["gaps"] if g.get("priority", 9) <= max_priority]
    # Avoid asking twice: an eligibility question on the degree covers the 'degree not stated' score gap.
    elig_crit = {g["criterion"] for g in gaps if g["type"] == "eligibility" and g.get("code") in ("unstated", "implied")}
    gaps = [g for g in gaps if not (g["type"].endswith("_unstated") and g["criterion"] in elig_crit)]
    if not gaps:
        return None
    lines, seen = [], set()
    for g in gaps:
        q = _q(g)
        if q in seen:
            continue
        seen.add(q)
        lines.append({"gap_id": g["id"], "priority": g["priority"], "question": q, "why": g.get("priority_label"), "impact": g.get("impact", [])})
    name = evaluation.get("name") or "applicant"
    body = (f"Dear {name},\n\nThank you for your application for the post of {position_title}. "
            "To complete the assessment we need to confirm a few details that are missing or unclear in the documents you submitted:\n\n"
            + "\n".join(f"{i + 1}. {l['question']}" for i, l in enumerate(lines))
            + "\n\nPlease reply within 7 days. Supporting documents (for example a degree certificate) are welcome.\n\nKind regards,\nRecruitment Committee")
    return {"candidate_id": evaluation["candidate_id"], "name": name, "questions": lines, "message": body}
