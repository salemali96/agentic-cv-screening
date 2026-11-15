"""Recorded source responses for the synthetic set (same JSON shape as the real Crossref and ORCID APIs).
All records are fictional. They exercise: a fill with ORCID identity, a fill with name + affiliation identity,
a same-surname record that must be rejected, and an ORCID record that disagrees with the CV."""
import json
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "fixtures" / "verification_fixtures.json"


def cr_url(title, family):
    return f"https://api.crossref.org/works?query.bibliographic={quote_plus(title)}&query.author={quote_plus(family)}&rows=3"


def cr_item(title, venue, year, typ, doi, authors):
    return {"DOI": doi, "type": typ, "title": [title], "container-title": [venue] if venue else [],
            "issued": {"date-parts": [[year]]}, "author": authors}


YOUSSEF = {"given": "Youssef", "family": "Adel", "ORCID": "https://orcid.org/0000-0002-5555-0404",
           "affiliation": [{"name": "Delta University"}]}
fx = {
    cr_url("Graph attention for traffic forecasting", "adel"): {"message": {"items": [
        cr_item("Graph attention for traffic forecasting", "Journal of Intelligent Transport Systems", 2024, "journal-article", "10.5555/adel.2024.traffic",
                [YOUSSEF, {"given": "Mariam", "family": "Saber", "affiliation": [{"name": "Delta University"}]}])]}},
    cr_url("Quantised message passing", "adel"): {"message": {"items": [
        cr_item("Quantised message passing", "Journal of Efficient Computing", 2022, "journal-article", "10.5555/adel.2022.quant",
                [{"given": "Youssef", "family": "Adel", "affiliation": [{"name": "Faculty of Computing, Delta University"}]}])]}},
    cr_url("Benchmarking temporal graph models", "adel"): {"message": {"items": [
        cr_item("Benchmarking temporal graph models", "Journal of Graph Learning", 2023, "journal-article", "10.5555/adel.2023.temporal",
                [YOUSSEF, {"given": "Rana", "family": "Hamdy"}])]}},
    # Same title, different person: must be rejected by the identity check.
    cr_url("Spectral sparsification revisited", "adel"): {"message": {"items": [
        cr_item("Spectral sparsification revisited", "Journal of Numerical Graph Theory", 2024, "journal-article", "10.5555/yasmin.2024.spectral",
                [{"given": "Yasmin", "family": "Adel", "ORCID": "https://orcid.org/0000-0003-5555-9999", "affiliation": [{"name": "Coastal Polytechnic"}]}])]}},
    # Partial names in the CV: no record in any source.
    cr_url("Vehicle routing with transformers", "hassan"): {"message": {"items": []}},
    cr_url("A survey of neural combinatorial optimisation", "hassan"): {"message": {"items": []}},
    # Rami Aziz's ORCID record lists one paper a year earlier than his CV.
    "https://pub.orcid.org/v3.0/0000-0001-5555-1212/works": {"group": [
        {"work-summary": [{"title": {"title": {"value": "Safe exploration via shielding"}}, "type": "journal-article",
                           "publication-date": {"year": {"value": "2021"}}, "journal-title": {"value": "Journal of Autonomous Systems Learning"},
                           "external-ids": {"external-id": [{"external-id-type": "doi", "external-id-value": "10.5555/rami.2022.shield"}]}}]},
        {"work-summary": [{"title": {"title": {"value": "Model-based exploration with priors"}}, "type": "journal-article",
                           "publication-date": {"year": {"value": "2025"}}, "journal-title": {"value": "Journal of Reinforcement Learning Research"}}]}]},
    "https://pub.orcid.org/v3.0/0000-0002-5555-0404/works": {"group": []},
    "https://pub.orcid.org/v3.0/0000-0002-5555-0404/educations": {"affiliation-group": [{"summaries": [{"education-summary": {
        "role-title": "PhD in Computer Science", "department-name": "Computer Science", "organization": {"name": "Delta University"},
        "end-date": {"year": {"value": "2018"}}}}]}]},
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(fx, indent=2), encoding="utf-8")
print(f"Wrote {len(fx)} recorded responses to {OUT}")
