import re
from pathlib import Path

import pytest

from pipeline.ingest import ingest_case

CASE_DIR = Path("cases/bevredeau")

EXPECTED_PAGES = {
    "denial_letter.pdf": 2,
    "medical_policy_MP-214.pdf": 2,
    "mri_report.pdf": 2,
    "pt_discharge_summary.pdf": 3,
    "surgeon_consult_note.pdf": 4,
}

# (file, page, regex that must match on that page)
ANCHORS = [
    ("denial_letter.pdf", 1, r"L5-S1"),
    ("denial_letter.pdf", 1, r"03/14/2026"),
    ("denial_letter.pdf", 2, r"6 months"),
    ("denial_letter.pdf", 2, r"4 weeks"),
    ("medical_policy_MP-214.pdf", 1, r"3 months"),
    ("mri_report.pdf", 1, r"January 20, 2026"),
    ("mri_report.pdf", 1, r"Grade I(?!I)"),
    ("pt_discharge_summary.pdf", 1, r"current smoker"),
    ("pt_discharge_summary.pdf", 2, r"\b24\b"),
    ("pt_discharge_summary.pdf", 3, r"5/5"),
    ("surgeon_consult_note.pdf", 1, r"2019"),
    ("surgeon_consult_note.pdf", 2, r"12/17/2025"),
    ("surgeon_consult_note.pdf", 3, r"Grade II"),
    ("surgeon_consult_note.pdf", 3, r"4/5"),
    ("surgeon_consult_note.pdf", 4, r"03/21/2026"),
]


@pytest.fixture(scope="module")
def case():
    return ingest_case(CASE_DIR)


def test_all_files_present(case):
    assert set(case) == set(EXPECTED_PAGES)


@pytest.mark.parametrize("name,count", EXPECTED_PAGES.items())
def test_page_numbers(case, name, count):
    assert [p["page"] for p in case[name]] == list(range(1, count + 1))


def test_every_page_has_text(case):
    for name, pages in case.items():
        for p in pages:
            assert len(p["text"].strip()) > 150, f"{name} p{p['page']}: little or no text"


def test_footer_on_every_page(case):
    for name, pages in case.items():
        for p in pages:
            assert "SYNTHETIC DOCUMENT" in p["text"], f"{name} p{p['page']}: footer missing"


@pytest.mark.parametrize("name,page,pattern", ANCHORS)
def test_anchor_on_expected_page(case, name, page, pattern):
    text = case[name][page - 1]["text"]
    assert re.search(pattern, text, re.IGNORECASE), f"{name} p{page}: no match for {pattern}"