"""Build the synthetic academic application set used for demos and evaluation.

All people, institutions, grants and publications are fictional. DOIs use the 10.5555 test prefix.

Each application folder contains:
  cv.txt / cover_letter.txt / publications.txt  - the submitted documents
  gold_profile.json  - what a correct extraction of the documents contains (with exact evidence quotes)
  truth.json         - the hidden full facts (patches to the profile) and gold requirement labels
The set is designed around incomplete information: unstated qualifications, undated leadership,
incomplete publication details, and documents that conflict.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "synthetic"


def ev(quote, doc="cv"):
    return [{"quote": quote, "doc": doc}]


def pub(title, venue, year, typ, authors, quote, doc="publications", doi=None, peer=True):
    return {"title": title, "venue": venue, "year": year, "type": typ, "peer_reviewed": peer if typ else None,
            "authors": authors, "doi": doi, "evidence": ev(quote, doc)}


APPS = []

# ------------------------------------------------------------------------------------------------
APPS.append(dict(
    id="A01", name="Layla Haddad", scenario="Complete, strong application (control)",
    cv="""LAYLA HADDAD, PhD
Senior Lecturer in Computer Science, University of Northbridge
ORCID: 0000-0003-5555-0101

EDUCATION
PhD in Computer Science, University of Northbridge, 2016
MSc in Artificial Intelligence, Eastgate University, 2012

ACADEMIC POSITIONS
Senior Lecturer, School of Computing, University of Northbridge, 2018 - present
Postdoctoral Research Fellow, Northbridge Vision Lab, 2016 - 2018

TEACHING
Module lead, Machine Learning (MSc), University of Northbridge, 2018 - present

LEADERSHIP AND SERVICE
Programme Director, MSc Artificial Intelligence, 2021 - 2024

RESEARCH FUNDING
Principal Investigator, Northbridge Research Council grant "Robust Vision Models", 2022
Co-Investigator, Regional Health Data Fund project "Federated Diagnostics", 2023

SUPERVISION
Supervised 2 PhD students to completion (2022, 2024).
Supervised 3 MSc dissertations.
""",
    cover="""Dear Selection Committee,
I am applying for the Assistant Professor position in Machine Learning. Since my PhD in 2016 I have built a research group in robust computer vision and have led the MSc Machine Learning module since 2018.
Yours sincerely, Layla Haddad""",
    pubs="""PUBLICATIONS (peer reviewed)
1. L. Haddad, M. Osei. Robust attention for medical images. Journal of Machine Vision Research, 2025.
2. L. Haddad. Certified defences for vision transformers. Transactions on Learning Systems, 2024.
3. L. Haddad, P. Lind. Federated diagnostics at scale. Journal of Health Informatics Computing, 2023.
4. L. Haddad, K. Ito. Calibration under shift. Journal of Machine Vision Research, 2022.
5. L. Haddad, R. Moss. Sparse adversarial training. Proceedings of the Conference on Learning Representations, 2024.
6. L. Haddad. Data-efficient robustness. Proceedings of the European Vision Conference, 2023.
7. L. Haddad, T. Blum. Shift-aware evaluation. Proceedings of the Workshop on Reliable ML, 2022.
""",
    profile=dict(
        name="Layla Haddad", orcid="0000-0003-5555-0101", title_prefix="Dr", current_position="Senior Lecturer, University of Northbridge",
        degrees=[{"level": "phd", "field": "Computer Science", "institution": "University of Northbridge", "year": 2016, "status": "completed", "expected_year": None, "evidence": ev("PhD in Computer Science, University of Northbridge, 2016")},
                 {"level": "masters", "field": "Artificial Intelligence", "institution": "Eastgate University", "year": 2012, "status": "completed", "expected_year": None, "evidence": ev("MSc in Artificial Intelligence, Eastgate University, 2012")}],
        positions=[{"title": "Senior Lecturer", "organisation": "University of Northbridge", "category": "academic", "start": 2018, "end": "present", "evidence": ev("Senior Lecturer, School of Computing, University of Northbridge, 2018 - present")},
                   {"title": "Postdoctoral Research Fellow", "organisation": "Northbridge Vision Lab", "category": "research", "start": 2016, "end": 2018, "evidence": ev("Postdoctoral Research Fellow, Northbridge Vision Lab, 2016 - 2018")}],
        teaching=[{"course": "Machine Learning (MSc)", "institution": "University of Northbridge", "role": "lead", "university": True, "start": 2018, "end": "present", "evidence": ev("Module lead, Machine Learning (MSc), University of Northbridge, 2018 - present")}],
        leadership=[{"role": "Programme Director, MSc Artificial Intelligence", "organisation": "University of Northbridge", "start": 2021, "end": 2024, "evidence": ev("Programme Director, MSc Artificial Intelligence, 2021 - 2024")}],
        publications=[
            pub("Robust attention for medical images", "Journal of Machine Vision Research", 2025, "journal", ["L. Haddad", "M. Osei"], "Robust attention for medical images. Journal of Machine Vision Research, 2025"),
            pub("Certified defences for vision transformers", "Transactions on Learning Systems", 2024, "journal", ["L. Haddad"], "Certified defences for vision transformers. Transactions on Learning Systems, 2024"),
            pub("Federated diagnostics at scale", "Journal of Health Informatics Computing", 2023, "journal", ["L. Haddad", "P. Lind"], "Federated diagnostics at scale. Journal of Health Informatics Computing, 2023"),
            pub("Calibration under shift", "Journal of Machine Vision Research", 2022, "journal", ["L. Haddad", "K. Ito"], "Calibration under shift. Journal of Machine Vision Research, 2022"),
            pub("Sparse adversarial training", "Conference on Learning Representations", 2024, "conference", ["L. Haddad", "R. Moss"], "Sparse adversarial training. Proceedings of the Conference on Learning Representations, 2024"),
            pub("Data-efficient robustness", "European Vision Conference", 2023, "conference", ["L. Haddad"], "Data-efficient robustness. Proceedings of the European Vision Conference, 2023"),
            pub("Shift-aware evaluation", "Workshop on Reliable ML", 2022, "conference", ["L. Haddad", "T. Blum"], "Shift-aware evaluation. Proceedings of the Workshop on Reliable ML, 2022")],
        grants=[{"title": "Robust Vision Models", "funder": "Northbridge Research Council", "role": "PI", "amount": None, "year": 2022, "evidence": ev('Principal Investigator, Northbridge Research Council grant "Robust Vision Models", 2022')},
                {"title": "Federated Diagnostics", "funder": "Regional Health Data Fund", "role": "Co-I", "amount": None, "year": 2023, "evidence": ev('Co-Investigator, Regional Health Data Fund project "Federated Diagnostics", 2023')}],
        supervision=[{"level": "phd", "status": "completed", "count": 2, "evidence": ev("Supervised 2 PhD students to completion (2022, 2024).")},
                     {"level": "masters", "status": "completed", "count": 3, "evidence": ev("Supervised 3 MSc dissertations.")}],
        indicators={"phd_indicated": True, "notes": []}, conflicts=[]),
    truth=[], gold={"R1": "met", "R2": "met", "R3": "met"}))

# ------------------------------------------------------------------------------------------------
APPS.append(dict(
    id="A02", name="Omar Farouk", scenario="Required qualification unstated: PhD never mentioned, but postdoc and lecturer roles imply it",
    cv="""OMAR FAROUK
Lecturer in Computer Science, Riverside University

EDUCATION
MSc in Computer Science, Delta University, 2015
BSc in Computer Engineering, Delta University, 2012

EXPERIENCE
Lecturer in Computer Science, Riverside University, 2021 - present
Postdoctoral Researcher, Riverside Machine Learning Group, 2020 - 2021

TEACHING
Lead lecturer, Introduction to Machine Learning, Riverside University, 2021 - present

FUNDING
Co-Investigator, Riverside Seed Fund project "Low-resource Arabic NLP", 2023

SUPERVISION
Supervised 2 MSc students (completed).
""",
    cover="""Dear Committee,
I lead the Introduction to Machine Learning course at Riverside University and work on low-resource language models. I would welcome the chance to build a group in your faculty.
Kind regards, Omar Farouk""",
    pubs="""SELECTED PUBLICATIONS
- O. Farouk, S. Amin. Tokenisation for Arabic dialects. Journal of Language Technology, 2025.
- O. Farouk. Small models for low-resource translation. Computational Linguistics Letters, 2024.
- O. Farouk, H. Badr. Evaluating dialect robustness. Journal of Language Technology, 2023.
- O. Farouk, N. Riad. Cross-lingual transfer for Nubian. Transactions on Speech and Language, 2023.
- O. Farouk. Data augmentation for Egyptian Arabic. Journal of Natural Language Engineering Studies, 2022.
- O. Farouk, S. Amin. Benchmarks for Arabic code-switching. Language Resources Journal, 2021.
""",
    profile=dict(
        name="Omar Farouk", orcid=None, title_prefix=None, current_position="Lecturer in Computer Science, Riverside University",
        degrees=[{"level": "masters", "field": "Computer Science", "institution": "Delta University", "year": 2015, "status": "completed", "expected_year": None, "evidence": ev("MSc in Computer Science, Delta University, 2015")},
                 {"level": "bachelors", "field": "Computer Engineering", "institution": "Delta University", "year": 2012, "status": "completed", "expected_year": None, "evidence": ev("BSc in Computer Engineering, Delta University, 2012")}],
        positions=[{"title": "Lecturer in Computer Science", "organisation": "Riverside University", "category": "academic", "start": 2021, "end": "present", "evidence": ev("Lecturer in Computer Science, Riverside University, 2021 - present")},
                   {"title": "Postdoctoral Researcher", "organisation": "Riverside Machine Learning Group", "category": "research", "start": 2020, "end": 2021, "evidence": ev("Postdoctoral Researcher, Riverside Machine Learning Group, 2020 - 2021")}],
        teaching=[{"course": "Introduction to Machine Learning", "institution": "Riverside University", "role": "lead", "university": True, "start": 2021, "end": "present", "evidence": ev("Lead lecturer, Introduction to Machine Learning, Riverside University, 2021 - present")}],
        leadership=[],
        publications=[
            pub("Tokenisation for Arabic dialects", "Journal of Language Technology", 2025, "journal", ["O. Farouk", "S. Amin"], "Tokenisation for Arabic dialects. Journal of Language Technology, 2025"),
            pub("Small models for low-resource translation", "Computational Linguistics Letters", 2024, "journal", ["O. Farouk"], "Small models for low-resource translation. Computational Linguistics Letters, 2024"),
            pub("Evaluating dialect robustness", "Journal of Language Technology", 2023, "journal", ["O. Farouk", "H. Badr"], "Evaluating dialect robustness. Journal of Language Technology, 2023"),
            pub("Cross-lingual transfer for Nubian", "Transactions on Speech and Language", 2023, "journal", ["O. Farouk", "N. Riad"], "Cross-lingual transfer for Nubian. Transactions on Speech and Language, 2023"),
            pub("Data augmentation for Egyptian Arabic", "Journal of Natural Language Engineering Studies", 2022, "journal", ["O. Farouk"], "Data augmentation for Egyptian Arabic. Journal of Natural Language Engineering Studies, 2022"),
            pub("Benchmarks for Arabic code-switching", "Language Resources Journal", 2021, "journal", ["O. Farouk", "S. Amin"], "Benchmarks for Arabic code-switching. Language Resources Journal, 2021")],
        grants=[{"title": "Low-resource Arabic NLP", "funder": "Riverside Seed Fund", "role": "Co-I", "amount": None, "year": 2023, "evidence": ev('Co-Investigator, Riverside Seed Fund project "Low-resource Arabic NLP", 2023')}],
        supervision=[{"level": "masters", "status": "completed", "count": 2, "evidence": ev("Supervised 2 MSc students (completed).")}],
        indicators={"phd_indicated": True, "notes": ["holds a postdoctoral post (2020 - 2021)", "lecturer since 2021"]}, conflicts=[]),
    truth=[{"op": "add", "section": "degrees", "item": {"level": "phd", "field": "Computer Science", "institution": "Delta University", "year": 2020, "status": "completed", "expected_year": None, "evidence": [{"quote": "(clarification reply) PhD in Computer Science, Delta University, 2020", "doc": "clarification", "check": "external"}]}}],
    gold={"R1": "not_established", "R2": "met", "R3": "met"}, gold_truth={"R1": "met"}))

# ------------------------------------------------------------------------------------------------
APPS.append(dict(
    id="A03", name="Sara Mansour", scenario="Leadership role with no dates; near the shortlist cut-off",
    cv="""DR SARA MANSOUR
Senior Lecturer, Department of Computer Science, Eastgate University

EDUCATION
PhD, Computer Science, Eastgate University, 2015

POSITIONS
Senior Lecturer, Eastgate University, 2019 - present
Lecturer, Eastgate University, 2016 - 2019

TEACHING
Course leader, Artificial Intelligence (BSc year 3), Eastgate University, 2019 - present

LEADERSHIP
Director, Applied AI Lab, Eastgate University

GRANTS
PI, Eastgate Innovation Grant "Explainable triage", 2023

SUPERVISION
Currently supervising 2 PhD students.
""",
    cover="""Dear Members of the Committee,
I direct the Applied AI Lab at Eastgate University, where I coordinate eight researchers, and I have taught Artificial Intelligence to final-year students for several years.
Sincerely, Sara Mansour""",
    pubs="""PUBLICATIONS
[1] S. Mansour, D. Vale. Explainable triage models. Journal of Clinical AI Systems, 2024.
[2] S. Mansour. Counterfactual explanations at the bedside. Proceedings of the Health ML Conference, 2025.
[3] S. Mansour, L. Grey. Auditing triage fairness. Proceedings of the Conference on Fair Computing, 2023.
[4] S. Mansour. Rule extraction from ensembles. Proceedings of the Symposium on Interpretable AI, 2022.
""",
    profile=dict(
        name="Sara Mansour", orcid=None, title_prefix="Dr", current_position="Senior Lecturer, Eastgate University",
        degrees=[{"level": "phd", "field": "Computer Science", "institution": "Eastgate University", "year": 2015, "status": "completed", "expected_year": None, "evidence": ev("PhD, Computer Science, Eastgate University, 2015")}],
        positions=[{"title": "Senior Lecturer", "organisation": "Eastgate University", "category": "academic", "start": 2019, "end": "present", "evidence": ev("Senior Lecturer, Eastgate University, 2019 - present")},
                   {"title": "Lecturer", "organisation": "Eastgate University", "category": "academic", "start": 2016, "end": 2019, "evidence": ev("Lecturer, Eastgate University, 2016 - 2019")}],
        teaching=[{"course": "Artificial Intelligence (BSc year 3)", "institution": "Eastgate University", "role": "lead", "university": True, "start": 2019, "end": "present", "evidence": ev("Course leader, Artificial Intelligence (BSc year 3), Eastgate University, 2019 - present")}],
        leadership=[{"role": "Director, Applied AI Lab", "organisation": "Eastgate University", "start": None, "end": None, "evidence": ev("Director, Applied AI Lab, Eastgate University")}],
        publications=[
            pub("Explainable triage models", "Journal of Clinical AI Systems", 2024, "journal", ["S. Mansour", "D. Vale"], "Explainable triage models. Journal of Clinical AI Systems, 2024"),
            pub("Counterfactual explanations at the bedside", "Health ML Conference", 2025, "conference", ["S. Mansour"], "Counterfactual explanations at the bedside. Proceedings of the Health ML Conference, 2025"),
            pub("Auditing triage fairness", "Conference on Fair Computing", 2023, "conference", ["S. Mansour", "L. Grey"], "Auditing triage fairness. Proceedings of the Conference on Fair Computing, 2023"),
            pub("Rule extraction from ensembles", "Symposium on Interpretable AI", 2022, "conference", ["S. Mansour"], "Rule extraction from ensembles. Proceedings of the Symposium on Interpretable AI, 2022")],
        grants=[{"title": "Explainable triage", "funder": "Eastgate Innovation Grant", "role": "PI", "amount": None, "year": 2023, "evidence": ev('PI, Eastgate Innovation Grant "Explainable triage", 2023')}],
        supervision=[{"level": "phd", "status": "ongoing", "count": 2, "evidence": ev("Currently supervising 2 PhD students.")}],
        indicators={"phd_indicated": True, "notes": []}, conflicts=[]),
    truth=[{"op": "set", "section": "leadership", "index": 0, "field": "start", "value": 2022},
           {"op": "set", "section": "leadership", "index": 0, "field": "end", "value": "present"}],
    gold={"R1": "met", "R2": "met", "R3": "met"}))

# ------------------------------------------------------------------------------------------------
APPS.append(dict(
    id="A04", name="Youssef Adel", scenario="Publication list incomplete: four entries without year or venue; one external match belongs to another person",
    cv="""YOUSSEF ADEL
Assistant Professor, Faculty of Computing, Delta University
ORCID: 0000-0002-5555-0404

EDUCATION
PhD in Computer Science, Delta University, 2018

POSITIONS
Assistant Professor, Delta University, 2020 - present
Postdoctoral Fellow, Delta AI Centre, 2018 - 2020

TEACHING
Lecturer in charge, Deep Learning, Delta University, 2020 - present

SUPERVISION
Supervised 3 MSc theses.
""",
    cover="""Dear Committee,
My research is on efficient graph neural networks. My full publication list is attached; some recent papers are listed in short form.
Best regards, Youssef Adel""",
    pubs="""PUBLICATIONS
1. Y. Adel, F. Nour. Message passing on sparse hardware. Journal of Graph Learning, 2023.
2. Y. Adel. Pruning graph networks without retraining. Journal of Efficient Computing, 2021.
3. Y. Adel, M. Saber. Graph attention for traffic forecasting.
4. Y. Adel. Quantised message passing.
5. Y. Adel, R. Hamdy. Benchmarking temporal graph models.
6. Y. Adel. Spectral sparsification revisited.
""",
    profile=dict(
        name="Youssef Adel", orcid="0000-0002-5555-0404", title_prefix=None, current_position="Assistant Professor, Delta University",
        degrees=[{"level": "phd", "field": "Computer Science", "institution": "Delta University", "year": 2018, "status": "completed", "expected_year": None, "evidence": ev("PhD in Computer Science, Delta University, 2018")}],
        positions=[{"title": "Assistant Professor", "organisation": "Delta University", "category": "academic", "start": 2020, "end": "present", "evidence": ev("Assistant Professor, Delta University, 2020 - present")},
                   {"title": "Postdoctoral Fellow", "organisation": "Delta AI Centre", "category": "research", "start": 2018, "end": 2020, "evidence": ev("Postdoctoral Fellow, Delta AI Centre, 2018 - 2020")}],
        teaching=[{"course": "Deep Learning", "institution": "Delta University", "role": "lead", "university": True, "start": 2020, "end": "present", "evidence": ev("Lecturer in charge, Deep Learning, Delta University, 2020 - present")}],
        leadership=[],
        publications=[
            pub("Message passing on sparse hardware", "Journal of Graph Learning", 2023, "journal", ["Y. Adel", "F. Nour"], "Message passing on sparse hardware. Journal of Graph Learning, 2023"),
            pub("Pruning graph networks without retraining", "Journal of Efficient Computing", 2021, "journal", ["Y. Adel"], "Pruning graph networks without retraining. Journal of Efficient Computing, 2021"),
            pub("Graph attention for traffic forecasting", None, None, None, ["Y. Adel", "M. Saber"], "Y. Adel, M. Saber. Graph attention for traffic forecasting."),
            pub("Quantised message passing", None, None, None, ["Y. Adel"], "Y. Adel. Quantised message passing."),
            pub("Benchmarking temporal graph models", None, None, None, ["Y. Adel", "R. Hamdy"], "Y. Adel, R. Hamdy. Benchmarking temporal graph models."),
            pub("Spectral sparsification revisited", None, None, None, ["Y. Adel"], "Y. Adel. Spectral sparsification revisited.")],
        grants=[],
        supervision=[{"level": "masters", "status": "completed", "count": 3, "evidence": ev("Supervised 3 MSc theses.")}],
        indicators={"phd_indicated": True, "notes": []}, conflicts=[]),
    truth=[{"op": "set", "section": "publications", "index": 2, "field": "year", "value": 2024}, {"op": "set", "section": "publications", "index": 2, "field": "type", "value": "journal"}, {"op": "set", "section": "publications", "index": 2, "field": "venue", "value": "Journal of Intelligent Transport Systems"},
           {"op": "set", "section": "publications", "index": 3, "field": "year", "value": 2022}, {"op": "set", "section": "publications", "index": 3, "field": "type", "value": "journal"}, {"op": "set", "section": "publications", "index": 3, "field": "venue", "value": "Journal of Efficient Computing"},
           {"op": "set", "section": "publications", "index": 4, "field": "year", "value": 2023}, {"op": "set", "section": "publications", "index": 4, "field": "type", "value": "journal"}, {"op": "set", "section": "publications", "index": 4, "field": "venue", "value": "Journal of Graph Learning"},
           {"op": "set", "section": "publications", "index": 5, "field": "year", "value": 2015}, {"op": "set", "section": "publications", "index": 5, "field": "type", "value": "conference"}, {"op": "set", "section": "publications", "index": 5, "field": "venue", "value": "Workshop on Graph Signal Processing"}],
    gold={"R1": "met", "R2": "met", "R3": "not_established"}, gold_truth={"R3": "met"}))

# ------------------------------------------------------------------------------------------------
APPS.append(dict(
    id="A05", name="Nadia Karim", scenario="Documents conflict: CV and cover letter disagree on PhD year, teaching start and leadership length",
    cv="""NADIA KARIM
Lecturer, Computer Science, Al-Noor Institute of Technology

EDUCATION
PhD in Computer Science, Al-Noor Institute of Technology, awarded 2019

EMPLOYMENT
Lecturer, Al-Noor Institute of Technology, 2021 - present
Research Associate, Al-Noor Data Lab, 2019 - 2021

TEACHING
Lecturer, Data Mining and Machine Learning, Al-Noor Institute of Technology, 2021 - present

SERVICE
Head of the Quality Assurance Unit, Faculty of Computing, 2020 - 2024

FUNDING
Co-I, Al-Noor Research Fund "Mining clinical notes", 2022

SUPERVISION
2 MSc students supervised to completion.
""",
    cover="""Dear Selection Committee,
Since completing my PhD in 2021 I have focused on text mining for health records. I have taught Data Mining and Machine Learning for the past three years, and I led our faculty's Quality Assurance Unit for one year.
Sincerely, Nadia Karim""",
    pubs="""PUBLICATIONS
1. N. Karim, A. Zaki. Mining clinical notes with weak labels. Journal of Medical Text Analytics, 2024.
2. N. Karim. Temporal phenotyping from records. Journal of Health Data Science, 2023.
3. N. Karim, O. Lutfi. Privacy-preserving topic models. Journal of Data Privacy Engineering, 2022.
4. N. Karim. Active learning for de-identification. Proceedings of the Clinical NLP Conference, 2025.
""",
    profile=dict(
        name="Nadia Karim", orcid=None, title_prefix=None, current_position="Lecturer, Al-Noor Institute of Technology",
        degrees=[{"level": "phd", "field": "Computer Science", "institution": "Al-Noor Institute of Technology", "year": 2019, "status": "completed", "expected_year": None, "evidence": ev("PhD in Computer Science, Al-Noor Institute of Technology, awarded 2019")}],
        positions=[{"title": "Lecturer", "organisation": "Al-Noor Institute of Technology", "category": "academic", "start": 2021, "end": "present", "evidence": ev("Lecturer, Al-Noor Institute of Technology, 2021 - present")},
                   {"title": "Research Associate", "organisation": "Al-Noor Data Lab", "category": "research", "start": 2019, "end": 2021, "evidence": ev("Research Associate, Al-Noor Data Lab, 2019 - 2021")}],
        teaching=[{"course": "Data Mining and Machine Learning", "institution": "Al-Noor Institute of Technology", "role": "lead", "university": True, "start": 2021, "end": "present", "evidence": ev("Lecturer, Data Mining and Machine Learning, Al-Noor Institute of Technology, 2021 - present")}],
        leadership=[{"role": "Head of the Quality Assurance Unit", "organisation": "Faculty of Computing", "start": 2020, "end": 2024, "evidence": ev("Head of the Quality Assurance Unit, Faculty of Computing, 2020 - 2024")}],
        publications=[
            pub("Mining clinical notes with weak labels", "Journal of Medical Text Analytics", 2024, "journal", ["N. Karim", "A. Zaki"], "Mining clinical notes with weak labels. Journal of Medical Text Analytics, 2024"),
            pub("Temporal phenotyping from records", "Journal of Health Data Science", 2023, "journal", ["N. Karim"], "Temporal phenotyping from records. Journal of Health Data Science, 2023"),
            pub("Privacy-preserving topic models", "Journal of Data Privacy Engineering", 2022, "journal", ["N. Karim", "O. Lutfi"], "Privacy-preserving topic models. Journal of Data Privacy Engineering, 2022"),
            pub("Active learning for de-identification", "Clinical NLP Conference", 2025, "conference", ["N. Karim"], "Active learning for de-identification. Proceedings of the Clinical NLP Conference, 2025")],
        grants=[{"title": "Mining clinical notes", "funder": "Al-Noor Research Fund", "role": "Co-I", "amount": None, "year": 2022, "evidence": ev('Co-I, Al-Noor Research Fund "Mining clinical notes", 2022')}],
        supervision=[{"level": "masters", "status": "completed", "count": 2, "evidence": ev("2 MSc students supervised to completion.")}],
        indicators={"phd_indicated": True, "notes": []},
        conflicts=[
            {"id": "C1", "topic": "Year the PhD was awarded", "item_type": "degrees", "item_index": 0, "field": "year", "source": "documents",
             "values": [{"value": 2019, "doc": "cv", "quote": "awarded 2019"}, {"value": 2021, "doc": "cover_letter", "quote": "Since completing my PhD in 2021"}]},
            {"id": "C2", "topic": "Start of university teaching", "item_type": "teaching", "item_index": 0, "field": "start", "source": "documents",
             "values": [{"value": 2021, "doc": "cv", "quote": "Data Mining and Machine Learning, Al-Noor Institute of Technology, 2021 - present"}, {"value": 2023, "doc": "cover_letter", "quote": "taught Data Mining and Machine Learning for the past three years"}]},
            {"id": "C3", "topic": "Length of Quality Assurance Unit leadership", "item_type": "leadership", "item_index": 0, "field": "start", "source": "documents",
             "values": [{"value": 2020, "doc": "cv", "quote": "Head of the Quality Assurance Unit, Faculty of Computing, 2020 - 2024"}, {"value": 2023, "doc": "cover_letter", "quote": "led our faculty's Quality Assurance Unit for one year"}]}]),
    truth=[{"op": "resolve", "conflict": "C1", "value": 2019}, {"op": "resolve", "conflict": "C2", "value": 2021}, {"op": "resolve", "conflict": "C3", "value": 2020}],
    gold={"R1": "met", "R2": "met", "R3": "met"}))

# ------------------------------------------------------------------------------------------------
APPS.append(dict(
    id="A06", name="Karim Saleh", scenario="Evidence that a requirement is NOT met: PhD expected after the start date",
    cv="""KARIM SALEH
PhD candidate, Department of Computer Science, University of Northbridge

EDUCATION
PhD in Computer Science (in progress), University of Northbridge, expected 2028
MSc in Data Science, Eastgate University, 2022

TEACHING
Teaching assistant, Machine Learning, University of Northbridge, 2023 - 2025
""",
    cover="""Dear Committee,
I am in the third year of my PhD and expect to submit my thesis in 2028. I am applying to be considered for future openings.
Regards, Karim Saleh""",
    pubs="""PUBLICATIONS
1. K. Saleh, L. Haddad. Robust tabular learning. Journal of Machine Vision Research, 2025.
2. K. Saleh. Shift detection with kernels. Proceedings of the Conference on Learning Representations, 2024.
3. K. Saleh, R. Moss. Calibrated ensembles. Proceedings of the Workshop on Reliable ML, 2023.
""",
    profile=dict(
        name="Karim Saleh", orcid=None, title_prefix=None, current_position="PhD candidate, University of Northbridge",
        degrees=[{"level": "phd", "field": "Computer Science", "institution": "University of Northbridge", "year": None, "status": "in_progress", "expected_year": 2028, "evidence": ev("PhD in Computer Science (in progress), University of Northbridge, expected 2028")},
                 {"level": "masters", "field": "Data Science", "institution": "Eastgate University", "year": 2022, "status": "completed", "expected_year": None, "evidence": ev("MSc in Data Science, Eastgate University, 2022")}],
        positions=[],
        teaching=[{"course": "Machine Learning", "institution": "University of Northbridge", "role": "assistant", "university": True, "start": 2023, "end": 2025, "evidence": ev("Teaching assistant, Machine Learning, University of Northbridge, 2023 - 2025")}],
        leadership=[],
        publications=[
            pub("Robust tabular learning", "Journal of Machine Vision Research", 2025, "journal", ["K. Saleh", "L. Haddad"], "Robust tabular learning. Journal of Machine Vision Research, 2025"),
            pub("Shift detection with kernels", "Conference on Learning Representations", 2024, "conference", ["K. Saleh"], "Shift detection with kernels. Proceedings of the Conference on Learning Representations, 2024"),
            pub("Calibrated ensembles", "Workshop on Reliable ML", 2023, "conference", ["K. Saleh", "R. Moss"], "Calibrated ensembles. Proceedings of the Workshop on Reliable ML, 2023")],
        grants=[], supervision=[], indicators={"phd_indicated": False, "notes": []}, conflicts=[]),
    truth=[], gold={"R1": "not_met", "R2": "met", "R3": "met"}))

# ------------------------------------------------------------------------------------------------
APPS.append(dict(
    id="A07", name="Hana Ibrahim", scenario="Complete, mid-ranked application (control)",
    cv="""DR HANA IBRAHIM
Lecturer, Department of Computer Engineering, Riverside University

EDUCATION
PhD in Computer Engineering, Riverside University, 2019

POSITIONS
Lecturer, Riverside University, 2019 - present

TEACHING
Course lead, Operating Systems, Riverside University, 2019 - present
Course lead, Computer Networks, Riverside University, 2021 - present

SUPERVISION
Supervised 2 MSc projects.
""",
    cover="""Dear Committee,
I teach systems courses and research energy-efficient edge inference. I would like to bring this work to your machine learning group.
Yours, Hana Ibrahim""",
    pubs="""PUBLICATIONS
1. H. Ibrahim. Energy-aware edge inference. Journal of Embedded Intelligence, 2024.
2. H. Ibrahim, K. Fahmy. Scheduling DNNs on microcontrollers. Journal of Systems Architecture Studies, 2022.
3. H. Ibrahim. TinyML for irrigation sensing. Proceedings of the Edge Computing Conference, 2023.
4. H. Ibrahim, W. Nasr. Compressing keyword spotters. Proceedings of the Edge Computing Conference, 2021.
""",
    profile=dict(
        name="Hana Ibrahim", orcid=None, title_prefix="Dr", current_position="Lecturer, Riverside University",
        degrees=[{"level": "phd", "field": "Computer Engineering", "institution": "Riverside University", "year": 2019, "status": "completed", "expected_year": None, "evidence": ev("PhD in Computer Engineering, Riverside University, 2019")}],
        positions=[{"title": "Lecturer", "organisation": "Riverside University", "category": "academic", "start": 2019, "end": "present", "evidence": ev("Lecturer, Riverside University, 2019 - present")}],
        teaching=[{"course": "Operating Systems", "institution": "Riverside University", "role": "lead", "university": True, "start": 2019, "end": "present", "evidence": ev("Course lead, Operating Systems, Riverside University, 2019 - present")},
                  {"course": "Computer Networks", "institution": "Riverside University", "role": "lead", "university": True, "start": 2021, "end": "present", "evidence": ev("Course lead, Computer Networks, Riverside University, 2021 - present")}],
        leadership=[],
        publications=[
            pub("Energy-aware edge inference", "Journal of Embedded Intelligence", 2024, "journal", ["H. Ibrahim"], "Energy-aware edge inference. Journal of Embedded Intelligence, 2024"),
            pub("Scheduling DNNs on microcontrollers", "Journal of Systems Architecture Studies", 2022, "journal", ["H. Ibrahim", "K. Fahmy"], "Scheduling DNNs on microcontrollers. Journal of Systems Architecture Studies, 2022"),
            pub("TinyML for irrigation sensing", "Edge Computing Conference", 2023, "conference", ["H. Ibrahim"], "TinyML for irrigation sensing. Proceedings of the Edge Computing Conference, 2023"),
            pub("Compressing keyword spotters", "Edge Computing Conference", 2021, "conference", ["H. Ibrahim", "W. Nasr"], "Compressing keyword spotters. Proceedings of the Edge Computing Conference, 2021")],
        grants=[], supervision=[{"level": "masters", "status": "completed", "count": 2, "evidence": ev("Supervised 2 MSc projects.")}],
        indicators={"phd_indicated": True, "notes": []}, conflicts=[]),
    truth=[], gold={"R1": "met", "R2": "met", "R3": "met"}))

# ------------------------------------------------------------------------------------------------
APPS.append(dict(
    id="A08", name="Tarek Nabil", scenario="Undated teaching, but even the best case cannot reach the shortlist (gap not worth chasing)",
    cv="""TAREK NABIL, PhD
Senior Machine Learning Engineer, Horizon Analytics

EDUCATION
PhD in Computer Science, Eastgate University, 2021

EXPERIENCE
Senior Machine Learning Engineer, Horizon Analytics, 2021 - present

TEACHING
Taught Data Structures and Algorithms at Eastgate University.
""",
    cover="""Dear Committee,
After four years in industry I would like to return to academia.
Best, Tarek Nabil""",
    pubs="""PUBLICATIONS
1. T. Nabil. Ranking with sparse feedback. Proceedings of the Recommender Systems Conference, 2022.
2. T. Nabil, J. Kamal. Fast retrieval for product search. Proceedings of the Information Retrieval Conference, 2023.
3. T. Nabil. Bandits for pricing. Proceedings of the Applied ML Conference, 2024.
""",
    profile=dict(
        name="Tarek Nabil", orcid=None, title_prefix="Dr", current_position="Senior Machine Learning Engineer, Horizon Analytics",
        degrees=[{"level": "phd", "field": "Computer Science", "institution": "Eastgate University", "year": 2021, "status": "completed", "expected_year": None, "evidence": ev("PhD in Computer Science, Eastgate University, 2021")}],
        positions=[{"title": "Senior Machine Learning Engineer", "organisation": "Horizon Analytics", "category": "industry", "start": 2021, "end": "present", "evidence": ev("Senior Machine Learning Engineer, Horizon Analytics, 2021 - present")}],
        teaching=[{"course": "Data Structures and Algorithms", "institution": "Eastgate University", "role": None, "university": True, "start": None, "end": None, "evidence": ev("Taught Data Structures and Algorithms at Eastgate University.")}],
        leadership=[],
        publications=[
            pub("Ranking with sparse feedback", "Recommender Systems Conference", 2022, "conference", ["T. Nabil"], "Ranking with sparse feedback. Proceedings of the Recommender Systems Conference, 2022"),
            pub("Fast retrieval for product search", "Information Retrieval Conference", 2023, "conference", ["T. Nabil", "J. Kamal"], "Fast retrieval for product search. Proceedings of the Information Retrieval Conference, 2023"),
            pub("Bandits for pricing", "Applied ML Conference", 2024, "conference", ["T. Nabil"], "Bandits for pricing. Proceedings of the Applied ML Conference, 2024")],
        grants=[], supervision=[], indicators={"phd_indicated": True, "notes": []}, conflicts=[]),
    truth=[{"op": "set", "section": "teaching", "index": 0, "field": "start", "value": 2019}, {"op": "set", "section": "teaching", "index": 0, "field": "end", "value": 2021},
           {"op": "set", "section": "teaching", "index": 0, "field": "role", "value": "assistant"}],
    gold={"R1": "met", "R2": "not_established", "R3": "met"}, gold_truth={"R2": "met"}))

# ------------------------------------------------------------------------------------------------
APPS.append(dict(
    id="A09", name="Mona Fathy", scenario="Required teaching never mentioned; strong research record",
    cv="""MONA FATHY, PhD
Research Scientist, National Institute for Computing Research

EDUCATION
PhD in Computer Science, Delta University, 2018

POSITIONS
Research Scientist, National Institute for Computing Research, 2018 - present

FUNDING
Principal Investigator, National Science Programme grant "Trustworthy forecasting", 2024
""",
    cover="""Dear Committee,
My research on probabilistic forecasting has produced six journal articles since 2021. I am keen to combine research with teaching in a university setting.
Kind regards, Mona Fathy""",
    pubs="""JOURNAL ARTICLES
1. M. Fathy. Probabilistic load forecasting. Journal of Forecasting Methods, 2025.
2. M. Fathy, A. Sobhy. Conformal intervals for demand. Journal of Forecasting Methods, 2024.
3. M. Fathy. Hierarchical reconciliation at scale. Journal of Applied Statistics and Computing, 2024.
4. M. Fathy, D. Rizk. Drift-aware retraining. Journal of Machine Learning Operations, 2023.
5. M. Fathy. Quantile transformers. Journal of Time Series Learning, 2022.
6. M. Fathy, A. Sobhy. Weather-aware forecasting. Journal of Time Series Learning, 2021.
""",
    profile=dict(
        name="Mona Fathy", orcid=None, title_prefix="Dr", current_position="Research Scientist, National Institute for Computing Research",
        degrees=[{"level": "phd", "field": "Computer Science", "institution": "Delta University", "year": 2018, "status": "completed", "expected_year": None, "evidence": ev("PhD in Computer Science, Delta University, 2018")}],
        positions=[{"title": "Research Scientist", "organisation": "National Institute for Computing Research", "category": "research", "start": 2018, "end": "present", "evidence": ev("Research Scientist, National Institute for Computing Research, 2018 - present")}],
        teaching=[], leadership=[],
        publications=[
            pub("Probabilistic load forecasting", "Journal of Forecasting Methods", 2025, "journal", ["M. Fathy"], "Probabilistic load forecasting. Journal of Forecasting Methods, 2025"),
            pub("Conformal intervals for demand", "Journal of Forecasting Methods", 2024, "journal", ["M. Fathy", "A. Sobhy"], "Conformal intervals for demand. Journal of Forecasting Methods, 2024"),
            pub("Hierarchical reconciliation at scale", "Journal of Applied Statistics and Computing", 2024, "journal", ["M. Fathy"], "Hierarchical reconciliation at scale. Journal of Applied Statistics and Computing, 2024"),
            pub("Drift-aware retraining", "Journal of Machine Learning Operations", 2023, "journal", ["M. Fathy", "D. Rizk"], "Drift-aware retraining. Journal of Machine Learning Operations, 2023"),
            pub("Quantile transformers", "Journal of Time Series Learning", 2022, "journal", ["M. Fathy"], "Quantile transformers. Journal of Time Series Learning, 2022"),
            pub("Weather-aware forecasting", "Journal of Time Series Learning", 2021, "journal", ["M. Fathy", "A. Sobhy"], "Weather-aware forecasting. Journal of Time Series Learning, 2021")],
        grants=[{"title": "Trustworthy forecasting", "funder": "National Science Programme", "role": "PI", "amount": None, "year": 2024, "evidence": ev('Principal Investigator, National Science Programme grant "Trustworthy forecasting", 2024')}],
        supervision=[], indicators={"phd_indicated": True, "notes": []}, conflicts=[]),
    truth=[{"op": "add", "section": "teaching", "item": {"course": "Time Series Analysis (guest lecturer)", "institution": "Delta University", "role": "assistant", "university": True, "start": 2019, "end": 2022, "evidence": [{"quote": "(clarification reply) Guest lecturer, Time Series Analysis, Delta University, 2019 - 2022", "doc": "clarification", "check": "external"}]}}],
    gold={"R1": "met", "R2": "not_established", "R3": "met"}, gold_truth={"R2": "met"}))

# ------------------------------------------------------------------------------------------------
APPS.append(dict(
    id="A10", name="Amr Hassan", scenario="Many gaps, but the best case is still far below the cut-off (no clarification needed)",
    cv="""AMR HASSAN
Postdoctoral Researcher, Riverside University

EDUCATION
PhD, Riverside University, 2024

POSITIONS
Postdoctoral Researcher, Riverside University, 2024 - present

TEACHING
Teaching assistant, Programming 1, Riverside University, 2021 - 2023
""",
    cover="""Dear Committee,
I recently completed my doctorate and am looking for my first faculty post.
Regards, Amr Hassan""",
    pubs="""PUBLICATIONS
1. A. Hassan. Learning to route parcels. Journal of Logistics Computing, 2024.
2. A. Hassan, B. Wahba. Vehicle routing with transformers.
3. A. Hassan. A survey of neural combinatorial optimisation.
""",
    profile=dict(
        name="Amr Hassan", orcid=None, title_prefix=None, current_position="Postdoctoral Researcher, Riverside University",
        degrees=[{"level": "phd", "field": None, "institution": "Riverside University", "year": 2024, "status": "completed", "expected_year": None, "evidence": ev("PhD, Riverside University, 2024")}],
        positions=[{"title": "Postdoctoral Researcher", "organisation": "Riverside University", "category": "research", "start": 2024, "end": "present", "evidence": ev("Postdoctoral Researcher, Riverside University, 2024 - present")}],
        teaching=[{"course": "Programming 1", "institution": "Riverside University", "role": "assistant", "university": True, "start": 2021, "end": 2023, "evidence": ev("Teaching assistant, Programming 1, Riverside University, 2021 - 2023")}],
        leadership=[],
        publications=[
            pub("Learning to route parcels", "Journal of Logistics Computing", 2024, "journal", ["A. Hassan"], "Learning to route parcels. Journal of Logistics Computing, 2024"),
            pub("Vehicle routing with transformers", None, None, None, ["A. Hassan", "B. Wahba"], "A. Hassan, B. Wahba. Vehicle routing with transformers."),
            pub("A survey of neural combinatorial optimisation", None, None, None, ["A. Hassan"], "A. Hassan. A survey of neural combinatorial optimisation.")],
        grants=[], supervision=[], indicators={"phd_indicated": True, "notes": []}, conflicts=[]),
    truth=[{"op": "set", "section": "degrees", "index": 0, "field": "field", "value": "Operations Research"},
           {"op": "set", "section": "publications", "index": 1, "field": "year", "value": 2023}, {"op": "set", "section": "publications", "index": 1, "field": "type", "value": "conference"},
           {"op": "set", "section": "publications", "index": 2, "field": "year", "value": 2025}, {"op": "set", "section": "publications", "index": 2, "field": "type", "value": "preprint"}, {"op": "set", "section": "publications", "index": 2, "field": "peer_reviewed", "value": False}],
    gold={"R1": "not_established", "R2": "met", "R3": "not_established"}, gold_truth={"R1": "not_established", "R3": "not_met"}))

# ------------------------------------------------------------------------------------------------
APPS.append(dict(
    id="A11", name="Dina Samy", scenario="Grant role and number of supervised students not stated",
    cv="""DR DINA SAMY
Assistant Professor of Computer Science, Riverside University

EDUCATION
PhD in Computer Science, Eastgate University, 2017

POSITIONS
Assistant Professor, Riverside University, 2018 - present

TEACHING
Instructor, Machine Learning Foundations, Riverside University, 2018 - present

SERVICE
Member of the Faculty Board, 2021 - 2023

FUNDING
Academy of Scientific Research grant "Fair credit scoring", 2022

SUPERVISION
Supervised several MSc students.
""",
    cover="""Dear Committee,
I work on fairness in machine learning for finance and teach Machine Learning Foundations.
Sincerely, Dina Samy""",
    pubs="""PUBLICATIONS
1. D. Samy. Fair credit scoring under drift. Journal of Responsible Computing, 2024.
2. D. Samy, E. Hosny. Auditing lending models. Journal of Financial Data Science Methods, 2023.
3. D. Samy. Counterfactual fairness in practice. Journal of Responsible Computing, 2021.
4. D. Samy, K. Adly. Group fairness for ranking. Proceedings of the Fairness in ML Conference, 2022.
""",
    profile=dict(
        name="Dina Samy", orcid=None, title_prefix="Dr", current_position="Assistant Professor, Riverside University",
        degrees=[{"level": "phd", "field": "Computer Science", "institution": "Eastgate University", "year": 2017, "status": "completed", "expected_year": None, "evidence": ev("PhD in Computer Science, Eastgate University, 2017")}],
        positions=[{"title": "Assistant Professor", "organisation": "Riverside University", "category": "academic", "start": 2018, "end": "present", "evidence": ev("Assistant Professor, Riverside University, 2018 - present")}],
        teaching=[{"course": "Machine Learning Foundations", "institution": "Riverside University", "role": "lead", "university": True, "start": 2018, "end": "present", "evidence": ev("Instructor, Machine Learning Foundations, Riverside University, 2018 - present")}],
        leadership=[{"role": "Member of the Faculty Board", "organisation": "Riverside University", "start": 2021, "end": 2023, "evidence": ev("Member of the Faculty Board, 2021 - 2023")}],
        publications=[
            pub("Fair credit scoring under drift", "Journal of Responsible Computing", 2024, "journal", ["D. Samy"], "Fair credit scoring under drift. Journal of Responsible Computing, 2024"),
            pub("Auditing lending models", "Journal of Financial Data Science Methods", 2023, "journal", ["D. Samy", "E. Hosny"], "Auditing lending models. Journal of Financial Data Science Methods, 2023"),
            pub("Counterfactual fairness in practice", "Journal of Responsible Computing", 2021, "journal", ["D. Samy"], "Counterfactual fairness in practice. Journal of Responsible Computing, 2021"),
            pub("Group fairness for ranking", "Fairness in ML Conference", 2022, "conference", ["D. Samy", "K. Adly"], "Group fairness for ranking. Proceedings of the Fairness in ML Conference, 2022")],
        grants=[{"title": "Fair credit scoring", "funder": "Academy of Scientific Research", "role": None, "amount": None, "year": 2022, "evidence": ev('Academy of Scientific Research grant "Fair credit scoring", 2022')}],
        supervision=[{"level": "masters", "status": "completed", "count": None, "evidence": ev("Supervised several MSc students.")}],
        indicators={"phd_indicated": True, "notes": []}, conflicts=[]),
    truth=[{"op": "set", "section": "grants", "index": 0, "field": "role", "value": "PI"}, {"op": "set", "section": "supervision", "index": 0, "field": "count", "value": 4}],
    gold={"R1": "met", "R2": "met", "R3": "met"}))

# ------------------------------------------------------------------------------------------------
APPS.append(dict(
    id="A12", name="Rami Aziz", scenario="Complete CV; an external record disagrees with the CV on a publication year",
    cv="""RAMI AZIZ, PhD
Assistant Professor, School of Computing, Eastgate University
ORCID: 0000-0001-5555-1212

EDUCATION
PhD in Computer Science, Eastgate University, 2016

POSITIONS
Assistant Professor, Eastgate University, 2020 - present
Lecturer, Eastgate University, 2016 - 2020

TEACHING
Module leader, Reinforcement Learning, Eastgate University, 2020 - present

LEADERSHIP
Chair, Departmental Examinations Committee, 2023 - present

SUPERVISION
Supervising 1 PhD student.
""",
    cover="""Dear Committee,
I research sample-efficient reinforcement learning and lead the Reinforcement Learning module at Eastgate.
Best wishes, Rami Aziz""",
    pubs="""PUBLICATIONS
1. R. Aziz. Model-based exploration with priors. Journal of Reinforcement Learning Research, 2025.
2. R. Aziz, G. Fouad. Offline policy evaluation in robotics. Journal of Reinforcement Learning Research, 2023.
3. R. Aziz. Safe exploration via shielding. Journal of Autonomous Systems Learning, 2022. doi:10.5555/rami.2022.shield
4. R. Aziz, M. Lotfy. Reward shaping from demonstrations. Journal of Robot Learning, 2024.
5. R. Aziz. Curiosity under partial observability. Proceedings of the Conference on Learning Representations, 2023.
""",
    profile=dict(
        name="Rami Aziz", orcid="0000-0001-5555-1212", title_prefix="Dr", current_position="Assistant Professor, Eastgate University",
        degrees=[{"level": "phd", "field": "Computer Science", "institution": "Eastgate University", "year": 2016, "status": "completed", "expected_year": None, "evidence": ev("PhD in Computer Science, Eastgate University, 2016")}],
        positions=[{"title": "Assistant Professor", "organisation": "Eastgate University", "category": "academic", "start": 2020, "end": "present", "evidence": ev("Assistant Professor, Eastgate University, 2020 - present")},
                   {"title": "Lecturer", "organisation": "Eastgate University", "category": "academic", "start": 2016, "end": 2020, "evidence": ev("Lecturer, Eastgate University, 2016 - 2020")}],
        teaching=[{"course": "Reinforcement Learning", "institution": "Eastgate University", "role": "lead", "university": True, "start": 2020, "end": "present", "evidence": ev("Module leader, Reinforcement Learning, Eastgate University, 2020 - present")}],
        leadership=[{"role": "Chair, Departmental Examinations Committee", "organisation": "Eastgate University", "start": 2023, "end": "present", "evidence": ev("Chair, Departmental Examinations Committee, 2023 - present")}],
        publications=[
            pub("Model-based exploration with priors", "Journal of Reinforcement Learning Research", 2025, "journal", ["R. Aziz"], "Model-based exploration with priors. Journal of Reinforcement Learning Research, 2025"),
            pub("Offline policy evaluation in robotics", "Journal of Reinforcement Learning Research", 2023, "journal", ["R. Aziz", "G. Fouad"], "Offline policy evaluation in robotics. Journal of Reinforcement Learning Research, 2023"),
            pub("Safe exploration via shielding", "Journal of Autonomous Systems Learning", 2022, "journal", ["R. Aziz"], "Safe exploration via shielding. Journal of Autonomous Systems Learning, 2022", doi="10.5555/rami.2022.shield"),
            pub("Reward shaping from demonstrations", "Journal of Robot Learning", 2024, "journal", ["R. Aziz", "M. Lotfy"], "Reward shaping from demonstrations. Journal of Robot Learning, 2024"),
            pub("Curiosity under partial observability", "Conference on Learning Representations", 2023, "conference", ["R. Aziz"], "Curiosity under partial observability. Proceedings of the Conference on Learning Representations, 2023")],
        grants=[], supervision=[{"level": "phd", "status": "ongoing", "count": 1, "evidence": ev("Supervising 1 PhD student.")}],
        indicators={"phd_indicated": True, "notes": []}, conflicts=[]),
    truth=[], gold={"R1": "met", "R2": "met", "R3": "met"}))

# ------------------------------------------------------------------------------------------------
APPS.append(dict(
    id="A13", name="Salma Youssef", scenario="Complete, strong application (control)",
    cv="""SALMA YOUSSEF, PhD
Assistant Professor, Department of Computer Science, Delta University

EDUCATION
PhD in Computer Science, University of Northbridge, 2017

POSITIONS
Assistant Professor, Delta University, 2019 - present
Postdoctoral Researcher, Northbridge AI Institute, 2017 - 2019

TEACHING
Course leader, Deep Learning, Delta University, 2019 - present
Course leader, Data Mining, Delta University, 2020 - present

SERVICE
Undergraduate Admissions Tutor, Delta University, 2022 - present

FUNDING
Co-Investigator, Delta Research Board project "Speech for health", 2024

SUPERVISION
Supervising 1 PhD student; supervised 4 MSc students.
""",
    cover="""Dear Committee,
I lead the Deep Learning course at Delta University and work on speech models for health monitoring.
Yours faithfully, Salma Youssef""",
    pubs="""PUBLICATIONS
1. S. Youssef. Self-supervised cough detection. Journal of Health Audio Processing, 2025.
2. S. Youssef, I. Kamel. Speech biomarkers for fatigue. Journal of Clinical Speech Technology, 2024.
3. S. Youssef. Robust speaker embeddings. Transactions on Speech and Language, 2023.
4. S. Youssef, A. Saad. Low-resource ASR for clinics. Journal of Clinical Speech Technology, 2022.
5. S. Youssef. Domain adaptation for voice. Transactions on Speech and Language, 2021.
""",
    profile=dict(
        name="Salma Youssef", orcid=None, title_prefix="Dr", current_position="Assistant Professor, Delta University",
        degrees=[{"level": "phd", "field": "Computer Science", "institution": "University of Northbridge", "year": 2017, "status": "completed", "expected_year": None, "evidence": ev("PhD in Computer Science, University of Northbridge, 2017")}],
        positions=[{"title": "Assistant Professor", "organisation": "Delta University", "category": "academic", "start": 2019, "end": "present", "evidence": ev("Assistant Professor, Delta University, 2019 - present")},
                   {"title": "Postdoctoral Researcher", "organisation": "Northbridge AI Institute", "category": "research", "start": 2017, "end": 2019, "evidence": ev("Postdoctoral Researcher, Northbridge AI Institute, 2017 - 2019")}],
        teaching=[{"course": "Deep Learning", "institution": "Delta University", "role": "lead", "university": True, "start": 2019, "end": "present", "evidence": ev("Course leader, Deep Learning, Delta University, 2019 - present")},
                  {"course": "Data Mining", "institution": "Delta University", "role": "lead", "university": True, "start": 2020, "end": "present", "evidence": ev("Course leader, Data Mining, Delta University, 2020 - present")}],
        leadership=[{"role": "Undergraduate Admissions Tutor", "organisation": "Delta University", "start": 2022, "end": "present", "evidence": ev("Undergraduate Admissions Tutor, Delta University, 2022 - present")}],
        publications=[
            pub("Self-supervised cough detection", "Journal of Health Audio Processing", 2025, "journal", ["S. Youssef"], "Self-supervised cough detection. Journal of Health Audio Processing, 2025"),
            pub("Speech biomarkers for fatigue", "Journal of Clinical Speech Technology", 2024, "journal", ["S. Youssef", "I. Kamel"], "Speech biomarkers for fatigue. Journal of Clinical Speech Technology, 2024"),
            pub("Robust speaker embeddings", "Transactions on Speech and Language", 2023, "journal", ["S. Youssef"], "Robust speaker embeddings. Transactions on Speech and Language, 2023"),
            pub("Low-resource ASR for clinics", "Journal of Clinical Speech Technology", 2022, "journal", ["S. Youssef", "A. Saad"], "Low-resource ASR for clinics. Journal of Clinical Speech Technology, 2022"),
            pub("Domain adaptation for voice", "Transactions on Speech and Language", 2021, "journal", ["S. Youssef"], "Domain adaptation for voice. Transactions on Speech and Language, 2021")],
        grants=[{"title": "Speech for health", "funder": "Delta Research Board", "role": "Co-I", "amount": None, "year": 2024, "evidence": ev('Co-Investigator, Delta Research Board project "Speech for health", 2024')}],
        supervision=[{"level": "phd", "status": "ongoing", "count": 1, "evidence": ev("Supervising 1 PhD student")},
                     {"level": "masters", "status": "completed", "count": 4, "evidence": ev("supervised 4 MSc students")}],
        indicators={"phd_indicated": True, "notes": []}, conflicts=[]),
    truth=[], gold={"R1": "met", "R2": "met", "R3": "met"}))

# ------------------------------------------------------------------------------------------------
APPS.append(dict(
    id="A14", name="Hossam Ali", scenario="Field of PhD differs between documents (both acceptable); leadership only in the cover letter",
    cv="""HOSSAM ALI, PhD
Lecturer, Faculty of Engineering, Al-Noor Institute of Technology

EDUCATION
PhD (Computer Science), Al-Noor Institute of Technology, 2016

POSITIONS
Lecturer, Al-Noor Institute of Technology, 2016 - present

TEACHING
Lecturer, Pattern Recognition, Al-Noor Institute of Technology, 2016 - present

SUPERVISION
Supervised 1 MSc student.
""",
    cover="""Dear Committee,
With a PhD in Computer Engineering and ten years of teaching, I chaired the faculty accreditation committee from 2018 to 2022 and would bring that experience to your department.
Sincerely, Hossam Ali""",
    pubs="""PUBLICATIONS
1. H. Ali. Handwriting recognition for Arabic forms. Journal of Document Analysis Studies, 2023.
2. H. Ali, S. Gad. Few-shot glyph recognition. Journal of Pattern Recognition Methods, 2022.
3. H. Ali. Layout-aware OCR. Proceedings of the Document Analysis Conference, 2024.
4. H. Ali. Feature learning for scripts. Journal of Pattern Recognition Methods, 2019.
5. H. Ali, S. Gad. Line segmentation revisited. Proceedings of the Document Analysis Conference, 2017.
""",
    profile=dict(
        name="Hossam Ali", orcid=None, title_prefix="Dr", current_position="Lecturer, Al-Noor Institute of Technology",
        degrees=[{"level": "phd", "field": "Computer Science", "institution": "Al-Noor Institute of Technology", "year": 2016, "status": "completed", "expected_year": None, "evidence": ev("PhD (Computer Science), Al-Noor Institute of Technology, 2016")}],
        positions=[{"title": "Lecturer", "organisation": "Al-Noor Institute of Technology", "category": "academic", "start": 2016, "end": "present", "evidence": ev("Lecturer, Al-Noor Institute of Technology, 2016 - present")}],
        teaching=[{"course": "Pattern Recognition", "institution": "Al-Noor Institute of Technology", "role": "lead", "university": True, "start": 2016, "end": "present", "evidence": ev("Lecturer, Pattern Recognition, Al-Noor Institute of Technology, 2016 - present")}],
        leadership=[{"role": "Chair, faculty accreditation committee", "organisation": "Al-Noor Institute of Technology", "start": 2018, "end": 2022, "evidence": ev("chaired the faculty accreditation committee from 2018 to 2022", "cover_letter")}],
        publications=[
            pub("Handwriting recognition for Arabic forms", "Journal of Document Analysis Studies", 2023, "journal", ["H. Ali"], "Handwriting recognition for Arabic forms. Journal of Document Analysis Studies, 2023"),
            pub("Few-shot glyph recognition", "Journal of Pattern Recognition Methods", 2022, "journal", ["H. Ali", "S. Gad"], "Few-shot glyph recognition. Journal of Pattern Recognition Methods, 2022"),
            pub("Layout-aware OCR", "Document Analysis Conference", 2024, "conference", ["H. Ali"], "Layout-aware OCR. Proceedings of the Document Analysis Conference, 2024"),
            pub("Feature learning for scripts", "Journal of Pattern Recognition Methods", 2019, "journal", ["H. Ali"], "Feature learning for scripts. Journal of Pattern Recognition Methods, 2019"),
            pub("Line segmentation revisited", "Document Analysis Conference", 2017, "conference", ["H. Ali", "S. Gad"], "Line segmentation revisited. Proceedings of the Document Analysis Conference, 2017")],
        grants=[], supervision=[{"level": "masters", "status": "completed", "count": 1, "evidence": ev("Supervised 1 MSc student.")}],
        indicators={"phd_indicated": True, "notes": []},
        conflicts=[{"id": "C1", "topic": "Field of the PhD", "item_type": "degrees", "item_index": 0, "field": "field", "source": "documents",
                    "values": [{"value": "Computer Science", "doc": "cv", "quote": "PhD (Computer Science)"}, {"value": "Computer Engineering", "doc": "cover_letter", "quote": "With a PhD in Computer Engineering"}]}]),
    truth=[{"op": "resolve", "conflict": "C1", "value": "Computer Science"}],
    gold={"R1": "met", "R2": "met", "R3": "met"}))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    problems = []
    for a in APPS:
        d = OUT / a["id"]
        d.mkdir(exist_ok=True)
        docs = {"cv": a["cv"], "cover_letter": a["cover"], "publications": a["pubs"]}
        for name, text in docs.items():
            (d / f"{name}.txt").write_text(text.strip() + "\n", encoding="utf-8")
        prof = a["profile"]
        # Validate every gold evidence quote appears verbatim in its document.
        for sec in ("degrees", "positions", "teaching", "leadership", "publications", "grants", "supervision"):
            for it in prof.get(sec, []):
                for e in it.get("evidence", []):
                    if e["quote"] not in docs.get(e["doc"], ""):
                        problems.append(f"{a['id']} {sec}: quote not in {e['doc']}: {e['quote']}")
        for c in prof.get("conflicts", []):
            for v in c["values"]:
                if v["quote"] not in docs.get(v["doc"], ""):
                    problems.append(f"{a['id']} conflict: quote not in {v['doc']}: {v['quote']}")
        (d / "gold_profile.json").write_text(json.dumps(prof, indent=2, ensure_ascii=False), encoding="utf-8")
        (d / "truth.json").write_text(json.dumps({"patches": a["truth"], "gold_requirements": a["gold"],
                                                  "gold_requirements_after_truth": {**a["gold"], **a.get("gold_truth", {})}}, indent=2), encoding="utf-8")
        manifest.append({"id": a["id"], "name": a["name"], "scenario": a["scenario"]})
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if problems:
        print("\n".join(problems))
        sys.exit(1)
    print(f"Wrote {len(APPS)} applications to {OUT}")


if __name__ == "__main__":
    main()
