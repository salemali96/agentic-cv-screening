"""Position template: requirements (eligibility and preferences) and scoring criteria with explicit rules.

Every number that influences a score lives here, so the interface can show and edit it and the
evaluation harness can perturb it. Nothing in scoring.py is a hidden constant.
"""
from copy import deepcopy

REQ_TIERS = ["required", "preferred", "nice", "hr", "excluded"]
TIER_LABELS = {
    "required": "Required (eligibility)",
    "preferred": "Preferred",
    "nice": "Good to have",
    "hr": "HR / committee judgement",
    "excluded": "Not used in screening",
}

# Requirement kinds that the rule engine can check from extracted facts.
REQ_KINDS = {
    "degree": "Holds a degree at or above a level, in a listed field, by a date",
    "teaching_years": "Minimum years of university teaching",
    "publications_recent": "Minimum number of peer-reviewed publications in a recent window",
    "leadership_any": "Has held a leadership or service role",
    "funding_any": "Has held research funding in one of the listed roles",
    "supervision_any": "Has supervised research students",
    "teaching_topic": "Has taught a course whose title matches a keyword",
    "manual": "Judged by a person (not checked automatically)",
}

CRITERIA_INFO = {
    "qualifications": "Highest relevant degree",
    "publications": "Recent research publications",
    "teaching": "University teaching experience",
    "research_experience": "Academic and research positions",
    "leadership": "Leadership and service",
    "funding": "Research funding",
    "supervision": "Research supervision",
}

RELATED_FIELDS = [
    "computer science", "computing", "computer engineering", "software engineering", "informatics",
    "information technology", "data science", "artificial intelligence", "machine learning",
    "information systems", "electrical and computer engineering", "computational",
]

DEFAULT_TEMPLATE = {
    "position": {
        "title": "Assistant Professor in Computer Science (Machine Learning)",
        "institution": "Faculty of Computing (example position)",
        "start_year": 2027,
        "description": (
            "The Faculty of Computing invites applications for an Assistant Professor in Computer Science "
            "with a focus on machine learning. The post holder will teach undergraduate and postgraduate "
            "courses, lead an independent research programme, supervise research students and contribute "
            "to departmental service.\n\nEssential: a PhD in Computer Science or a closely related field, "
            "awarded by the start date; at least two years of university teaching; at least three "
            "peer-reviewed publications in the last six years.\n\nDesirable: leadership or service roles; "
            "research funding as PI or Co-I; supervision of research students; experience teaching machine "
            "learning or AI courses."
        ),
    },
    "shortlist_size": 5,
    "requirements": [
        {"id": "R1", "tier": "required", "kind": "degree", "text": "PhD in Computer Science or a related field, awarded by the start date",
         "params": {"min_level": "phd", "fields": RELATED_FIELDS, "by_year": 2027}},
        {"id": "R2", "tier": "required", "kind": "teaching_years", "text": "At least 2 years of university teaching",
         "params": {"min_years": 2}},
        {"id": "R3", "tier": "required", "kind": "publications_recent", "text": "At least 3 peer-reviewed publications in the last 6 years",
         "params": {"min_count": 3, "years": 6}},
        {"id": "R4", "tier": "preferred", "kind": "leadership_any", "text": "Leadership or service role", "params": {}},
        {"id": "R5", "tier": "preferred", "kind": "funding_any", "text": "Research funding as PI or Co-I", "params": {"roles": ["PI", "Co-I"]}},
        {"id": "R6", "tier": "nice", "kind": "supervision_any", "text": "Supervision of research students", "params": {}},
        {"id": "R7", "tier": "nice", "kind": "teaching_topic", "text": "Has taught machine learning or AI",
         "params": {"keywords": ["machine learning", "artificial intelligence", "deep learning", "neural", "ai"]}},
        {"id": "R8", "tier": "hr", "kind": "manual", "text": "Fit with the department's research priorities", "params": {}},
        {"id": "R9", "tier": "hr", "kind": "manual", "text": "Teaching demonstration at interview", "params": {}},
    ],
    # Weights are relative; they are normalised to sum to 1 when scoring.
    "criteria": {
        "qualifications": {
            "weight": 10,
            "points": {"phd": 10, "phd_in_progress": 4, "masters": 3, "bachelors": 1},
            "unrelated_field_factor": 0.5,
        },
        "publications": {
            "weight": 30,
            "points": {"journal": 2.0, "conference": 1.5, "book": 3.0, "chapter": 1.0, "preprint": 0.25, "other": 0.25},
            "recency_years": 6,
            "cap": 12,
        },
        "teaching": {
            "weight": 20,
            "points_per_year": {"lead": 2.5, "assistant": 1.0},
            "cap": 10,
        },
        "research_experience": {
            "weight": 15,
            "points_per_year": 2.0,
            "cap": 10,
        },
        "leadership": {
            "weight": 10,
            "points_per_year": 2.0,
            "cap": 10,
        },
        "funding": {
            "weight": 10,
            "points": {"PI": 4.0, "Co-I": 2.0},
            "cap": 10,
        },
        "supervision": {
            "weight": 5,
            "points": {"phd_completed": 3.0, "phd_ongoing": 1.5, "masters": 1.0, "undergraduate": 0.25},
            "unknown_count_max": 3,
            "cap": 10,
        },
    },
    # Rules for incomplete information. These define the "possible" end of every score range.
    "uncertainty": {
        "undated_role_min_years": 0.0,   # a role with no dates counts this many years in the supported score
        "undated_role_max_years": 4.0,   # ...and at most this many years in the possible score
        "unverified_quote_counts": False, # if a quote can't be found in the document, the fact is not supported
        "unstated_required_assumes_minimum": True,  # possible score assumes an unstated required item is just met
    },
}


def default_template():
    return deepcopy(DEFAULT_TEMPLATE)


def parameter_guide(t=None):
    """Human-readable description of every adjustable parameter and how it moves the score."""
    t = t or DEFAULT_TEMPLATE
    c = t["criteria"]
    return [
        {"param": "Criterion weights", "where": "criteria.*.weight",
         "effect": "Overall score = sum over criteria of (weight / total weight) x criterion score (0-10) x 10. "
                   "Raising a weight helps candidates who score above average on that criterion and hurts those below."},
        {"param": "Shortlist size (k)", "where": "shortlist_size",
         "effect": "The top k eligible candidates by supported score form the shortlist. A candidate whose score range "
                   "crosses the k-th place is marked 'uncertain'."},
        {"param": "Degree points", "where": "criteria.qualifications.points",
         "effect": f"PhD {c['qualifications']['points']['phd']}, PhD in progress {c['qualifications']['points']['phd_in_progress']}, "
                   f"Master's {c['qualifications']['points']['masters']} (out of 10). A degree outside the listed fields is multiplied by "
                   f"{c['qualifications']['unrelated_field_factor']}."},
        {"param": "Publication points and recency", "where": "criteria.publications",
         "effect": f"Each publication from the last {c['publications']['recency_years']} years earns points by type "
                   f"(journal {c['publications']['points']['journal']}, conference {c['publications']['points']['conference']}, ...). "
                   f"The total is capped at {c['publications']['cap']} and scaled to 0-10. Shortening the window removes older papers."},
        {"param": "Teaching points per year", "where": "criteria.teaching.points_per_year",
         "effect": "Years as lead instructor and as assistant earn different points per year, capped and scaled to 0-10."},
        {"param": "Research experience points per year", "where": "criteria.research_experience.points_per_year",
         "effect": "Years in academic or research posts (postdoc, lecturer, research scientist) earn points per year."},
        {"param": "Leadership points per year", "where": "criteria.leadership.points_per_year",
         "effect": "Years in leadership or service roles earn points per year, capped and scaled to 0-10."},
        {"param": "Funding points", "where": "criteria.funding.points",
         "effect": "Each grant earns points by role (PI or Co-I). An unstated role gives a range between the two."},
        {"param": "Supervision points", "where": "criteria.supervision.points",
         "effect": "Points per student by level. 'Several students' with no count gives a range from 1 to the unknown-count maximum."},
        {"param": "Undated roles", "where": "uncertainty.undated_role_min_years / max_years",
         "effect": "A role with no dates counts the minimum in the supported score and the maximum in the possible score. "
                   "Widening this range makes more candidates 'uncertain'."},
        {"param": "Requirement tiers and thresholds", "where": "requirements[*]",
         "effect": "Required items gate eligibility: not met = ineligible, not established = eligibility unresolved. "
                   "Preferred and good-to-have items are reported but do not change the score directly."},
    ]


def validate_template(t):
    """Fill missing keys from the default so older saved templates keep working."""
    base = default_template()
    out = deepcopy(t or {})
    for k, v in base.items():
        if k not in out:
            out[k] = deepcopy(v)
    for name, spec in base["criteria"].items():
        out["criteria"].setdefault(name, deepcopy(spec))
        for k, v in spec.items():
            out["criteria"][name].setdefault(k, deepcopy(v))
    for k, v in base["uncertainty"].items():
        out["uncertainty"].setdefault(k, v)
    for r in out["requirements"]:
        r.setdefault("params", {})
        r.setdefault("tier", "preferred")
        r.setdefault("kind", "manual")
    return out
