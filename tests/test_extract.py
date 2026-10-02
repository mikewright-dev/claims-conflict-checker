"""Phase 2 tests: extract key facts from each document as validated JSON.

Offline tests mock the model. Live tests (--live) call the real API once per
document and cache the raw responses under outputs/extract_cache/.

Interface these tests define for pipeline/extract.py:
    MODEL                      "gemini-3.8-flash"
    FIELDS                     tuple of the ten fact field names
    Fact                       Pydantic: value, page, quote (all str/int or None)
    DocExtraction              Pydantic: one Fact per name in FIELDS
    build_prompt(pages)        prompt text for one document's page dicts
    extract_document(pages, client, cache_dir=None) -> DocExtraction
    extract_case(case, client, cache_dir=None)      -> {file name: DocExtraction}
    check_grounding(extraction, pages) -> list[str] of problems (empty = grounded)
"""
import json
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from pipeline.extract import (
    FIELDS,
    MODEL,
    DocExtraction,
    Fact,
    build_prompt,
    check_grounding,
    extract_case,
    extract_document,
)
from pipeline.ingest import ingest_case

CASE_DIR = Path("cases/bevredeau")
CACHE_DIR = Path("outputs/extract_cache")

EXPECTED_FIELDS = [
    "surgery_date",
    "fusion_level",
    "pt_duration",
    "pt_visit_count",
    "conservative_care_required",
    "injections",
    "spondylolisthesis_grade",
    "motor_strength",
    "smoking_status",
    "mri_date",
]

KEY = json.loads((CASE_DIR / "answer_key.json").read_text(encoding="utf-8"))
KEY_ITEMS = {item["id"]: item for item in KEY["items"]}


# ---------------------------------------------------------------- helpers

def fake_client(payload):
    """Mock client whose interactions.create returns `payload` as output_text."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    client = MagicMock()
    client.interactions.create.return_value = SimpleNamespace(output_text=text)
    return client


def fact(value=None, page=None, quote=None):
    return {"value": value, "page": page, "quote": quote}


SYNTH_PAGES = [
    {"file": "synth.pdf", "page": 1, "text": "Planned Date of Service: 03/14/2026\nPatient is a current smoker."},
    {"file": "synth.pdf", "page": 2, "text": "Completed physical therapy for 14 weeks (24 visits)."},
]


@pytest.fixture(scope="module")
def case():
    return ingest_case(CASE_DIR)


# ------------------------------------------------- offline: schema / models

def test_schema_has_exactly_the_ten_fact_fields():
    """DocExtraction has exactly the ten named fields, each typed Fact.
    Fails if a field is missing, renamed, extra, or not a Fact."""
    assert list(FIELDS) == EXPECTED_FIELDS
    assert list(DocExtraction.model_fields) == EXPECTED_FIELDS
    for name, f in DocExtraction.model_fields.items():
        assert f.annotation is Fact, name


def test_empty_object_gives_all_null_facts():
    """Parsing '{}' yields every field present with value/page/quote None.
    Fails if fields are required (no defaults) or default to something non-null."""
    doc = DocExtraction.model_validate_json("{}")
    for name in EXPECTED_FIELDS:
        f = getattr(doc, name)
        assert (f.value, f.page, f.quote) == (None, None, None), name


def test_valid_response_parses_into_model():
    """A well-formed model response is parsed with values, pages, quotes intact.
    Fails if extract_document drops, renames, or coerces fields wrongly."""
    payload = {"surgery_date": fact("03/14/2026", 1, "Planned Date of Service: 03/14/2026")}
    doc = extract_document(SYNTH_PAGES, fake_client(payload))
    assert isinstance(doc, DocExtraction)
    assert doc.surgery_date.value == "03/14/2026"
    assert doc.surgery_date.page == 1
    assert doc.surgery_date.quote == "Planned Date of Service: 03/14/2026"


def test_unstated_fields_are_null_when_model_reports_null():
    """Fields the model reports as null (or omits) stay null after extraction.
    Fails if the code fills in defaults, placeholders like 'N/A', or guesses."""
    payload = {"surgery_date": fact("03/14/2026", 1, "Planned Date of Service: 03/14/2026")}
    doc = extract_document(SYNTH_PAGES, fake_client(payload))
    for name in EXPECTED_FIELDS:
        if name != "surgery_date":
            assert getattr(doc, name).value is None, name
            assert getattr(doc, name).page is None, name
            assert getattr(doc, name).quote is None, name


def test_non_null_fact_without_page_is_rejected():
    """A fact with a value but no page fails validation.
    Fails if Fact allows value without a page citation."""
    bad = {"smoking_status": fact("current smoker", None, "current smoker")}
    with pytest.raises(ValidationError):
        DocExtraction.model_validate(bad)
    with pytest.raises(ValidationError):
        extract_document(SYNTH_PAGES, fake_client(bad))


def test_wrong_types_are_rejected():
    """Non-integer page or non-JSON output raises instead of being silently accepted.
    Fails if validation is lenient (e.g. swallows bad JSON and returns empty facts)."""
    with pytest.raises(ValidationError):
        extract_document(SYNTH_PAGES, fake_client({"surgery_date": fact("x", "first", "x")}))
    with pytest.raises(ValidationError):
        extract_document(SYNTH_PAGES, fake_client("this is not json"))


# ------------------------------------------------------ offline: grounding

def doc_with(**facts):
    return DocExtraction.model_validate(facts)


def test_grounding_passes_when_quote_is_on_cited_page():
    """Quotes that appear on their cited page produce no problems.
    Fails if check_grounding flags correct citations."""
    doc = doc_with(
        surgery_date=fact("03/14/2026", 1, "Planned Date of Service: 03/14/2026"),
        pt_visit_count=fact("24", 2, "24 visits"),
    )
    assert check_grounding(doc, SYNTH_PAGES) == []


def test_grounding_tolerates_whitespace_and_case():
    """Line breaks / extra spaces / case differences between quote and page text are OK.
    Fails if matching is a raw substring test (pdf text wraps lines)."""
    doc = doc_with(smoking_status=fact("current smoker", 1, "03/14/2026  Patient is a\ncurrent SMOKER"))
    assert check_grounding(doc, SYNTH_PAGES) == []


def test_grounding_flags_quote_on_wrong_page():
    """A real quote cited against the wrong page is reported.
    Fails if grounding searches the whole document instead of the cited page."""
    doc = doc_with(pt_visit_count=fact("24", 1, "24 visits"))  # it is on page 2
    problems = check_grounding(doc, SYNTH_PAGES)
    assert len(problems) == 1 and "pt_visit_count" in problems[0]


def test_grounding_flags_fabricated_quote():
    """A quote that appears nowhere is reported.
    Fails if the check is skipped or only looks at the value."""
    doc = doc_with(fusion_level=fact("L4-L5", 1, "Planned procedure: L4-L5 fusion"))
    problems = check_grounding(doc, SYNTH_PAGES)
    assert len(problems) == 1 and "fusion_level" in problems[0]


def test_grounding_flags_page_out_of_range_and_missing_quote():
    """A cited page that does not exist, or a non-null fact with no quote, is reported.
    Fails if these cases raise IndexError or are silently accepted."""
    doc = doc_with(
        mri_date=fact("01/20/2026", 9, "01/20/2026"),
        injections=fact("none", 1, None),
    )
    problems = check_grounding(doc, SYNTH_PAGES)
    assert len(problems) == 2


def test_grounding_ignores_null_facts():
    """All-null extraction has nothing to ground, so no problems.
    Fails if null facts are treated as missing citations."""
    assert check_grounding(DocExtraction(), SYNTH_PAGES) == []


def test_grounding_works_on_real_ingested_page(case):
    """A key-derived quote grounds against the real surgeon note page 2; same quote on page 1 does not.
    Fails if grounding does not work with real ingest output."""
    loc = next(l for l in KEY_ITEMS["C3"]["locations"]
               if l["file"] == "surgeon_consult_note.pdf" and l["page"] == 2)
    pages = case["surgeon_consult_note.pdf"]
    good = doc_with(pt_duration=fact("14 weeks", 2, loc["value"]))
    bad = doc_with(pt_duration=fact("14 weeks", 1, loc["value"]))
    assert check_grounding(good, pages) == []
    assert len(check_grounding(bad, pages)) == 1


# ----------------------------------------------------- offline: model call

def test_calls_interactions_api_with_model_and_json_schema():
    """One interactions.create call with gemini-3.8-flash and a JSON-schema response_format.
    Fails if wrong model, wrong API (generate_content), no schema, or schema lacks the ten fields."""
    client = fake_client({})
    extract_document(SYNTH_PAGES, client)
    client.interactions.create.assert_called_once()
    kw = client.interactions.create.call_args.kwargs
    assert MODEL == "gemini-3.8-flash"
    assert kw["model"] == "gemini-3.8-flash"
    rf = kw["response_format"]
    assert rf["type"] == "text"
    assert rf["mime_type"] == "application/json"
    assert set(rf["schema"]["properties"]) == set(EXPECTED_FIELDS)


def test_does_not_set_temperature():
    """No temperature anywhere in the request (deprecated in the SDK's generation_config).
    Fails if temperature is passed at top level or inside generation_config."""
    client = fake_client({})
    extract_document(SYNTH_PAGES, client)
    kw = client.interactions.create.call_args.kwargs
    assert "temperature" not in kw
    assert "temperature" not in (kw.get("generation_config") or {})


def test_prompt_contains_every_page_with_its_number():
    """The prompt includes each page's text labelled with its page number, so the model can cite pages.
    Fails if pages are dropped, merged without numbers, or numbered differently."""
    prompt = build_prompt(SYNTH_PAGES)
    for p in SYNTH_PAGES:
        assert p["text"] in prompt
        assert re.search(rf"page\s*{p['page']}\b", prompt, re.IGNORECASE)


def test_prompt_is_generic():
    """Prompt, built from neutral pages, has no answer-key terms, case names, or expected values.
    Fails if the prompt mentions conflicts/decoys/answer key/expected, the patient, or any key value."""
    neutral = [{"file": "x.pdf", "page": 1, "text": "NEUTRAL TEXT"}]
    prompt = build_prompt(neutral).lower()
    for word in ["answer key", "answer_key", "conflict", "decoy", "planted", "expected",
                 "bevredeau", "denial", "discrepan", "mismatch"]:
        assert word not in prompt, word
    for item in KEY["items"]:
        for loc in item["locations"]:
            assert loc["value"].lower() not in prompt
    # every specific value token from the key (dates, levels, counts) must be absent
    for token in ["03/14/2026", "03/21/2026", "l5-s1", "l4-l5", "grade ii", "4/5", "5/5", "2019"]:
        assert token not in prompt, token


def test_prompt_tells_model_not_to_guess():
    """Prompt tells the model to use null for unstated fields and to cite a page and verbatim quote.
    Fails if the null / no-guess / page / quote instructions are missing."""
    prompt = build_prompt(SYNTH_PAGES).lower()
    assert "null" in prompt
    assert "guess" in prompt
    assert "page" in prompt
    assert "quote" in prompt and "verbatim" in prompt
    for name in EXPECTED_FIELDS:
        assert name in prompt, name


# ------------------------------------------------- offline: case + caching

def test_extract_case_returns_one_validated_object_per_document(case):
    """Each of the five documents gets one DocExtraction, one API call each.
    Fails if documents are skipped, merged into one call, or results are keyed wrongly."""
    client = fake_client({})
    results = extract_case(case, client)
    assert set(results) == set(case)
    assert all(isinstance(r, DocExtraction) for r in results.values())
    assert client.interactions.create.call_count == len(case)


def test_cache_writes_raw_response_and_skips_second_call(tmp_path):
    """First call writes the raw response under cache_dir; second call reads it without calling the API.
    Fails if nothing is cached or the API is hit again (burns free-tier quota)."""
    payload = {"surgery_date": fact("03/14/2026", 1, "Planned Date of Service: 03/14/2026")}
    c1 = fake_client(payload)
    first = extract_document(SYNTH_PAGES, c1, cache_dir=tmp_path)
    assert c1.interactions.create.call_count == 1
    cached = list(tmp_path.glob("*.json"))
    assert len(cached) == 1
    assert json.loads(cached[0].read_text(encoding="utf-8"))["surgery_date"]["value"] == "03/14/2026"

    c2 = fake_client({})
    second = extract_document(SYNTH_PAGES, c2, cache_dir=tmp_path)
    c2.interactions.create.assert_not_called()
    assert second == first


def test_invalid_response_is_not_cached(tmp_path):
    """A response that fails validation is not written to the cache.
    Fails if bad output gets cached and keeps failing on every rerun."""
    with pytest.raises(ValidationError):
        extract_document(SYNTH_PAGES, fake_client("not json"), cache_dir=tmp_path)
    assert list(tmp_path.glob("*.json")) == []


# --------------------------------------------------------- live (real API)

def key_locations(item_id, file, selector):
    """Answer-key locations of item `item_id` in `file` whose value string matches `selector`."""
    return [l for l in KEY_ITEMS[item_id]["locations"]
            if l["file"] == file and re.search(selector, l["value"], re.IGNORECASE)]


def key_pages(item_id, file, selector):
    """Pages of those key locations."""
    return {l["page"] for l in key_locations(item_id, file, selector)}


def parse_date(text):
    """First date in text, as a date, accepting 'January 20, 2026' or '01/20/2026'. None if absent."""
    m = re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", text)
    if m:
        return datetime.strptime(m.group(), "%m/%d/%Y").date()
    m = re.search(r"\b[A-Z][a-z]+ \d{1,2}, \d{4}\b", text)
    return datetime.strptime(m.group(), "%B %d, %Y").date() if m else None


def date_check(expected):
    return lambda v: parse_date(v) == expected


def rx(*patterns):
    """Value check: every pattern must match."""
    return lambda v: all(re.search(p, v, re.IGNORECASE) for p in patterns)


def rx_not(match, forbid):
    return lambda v: bool(re.search(match, v, re.IGNORECASE)) and not re.search(forbid, v, re.IGNORECASE)


# (file, field, answer-key item, selector that picks exactly ONE key location, value check)
# The selector is a regex searched in the key location's value string; the sync tests
# below enforce that it picks exactly one location and that the check accepts that string.
# Only (file, field) pairs the answer key states a value for are asserted;
# the key says nothing about the other pairs, so they are not tested.
LIVE_EXPECTATIONS = [
    ("denial_letter.pdf", "surgery_date", "C1", r"Date of Service", date_check(datetime(2026, 3, 14).date())),
    ("surgeon_consult_note.pdf", "surgery_date", "C1", r"Surgery date", date_check(datetime(2026, 3, 21).date())),
    ("denial_letter.pdf", "fusion_level", "C2", r"Service Reviewed", rx(r"L5\s*-?\s*S1")),
    ("surgeon_consult_note.pdf", "fusion_level", "C2", r"Planned procedure", rx(r"L4\s*-?\s*L?5")),
    ("denial_letter.pdf", "pt_duration", "C3", r"4 weeks", rx(r"\b4\s*weeks?\b")),
    ("pt_discharge_summary.pdf", "pt_duration", "C3", r"14 weeks", rx(r"\b14\s*weeks?\b")),
    ("surgeon_consult_note.pdf", "pt_duration", "C3", r"14 weeks", rx(r"\b14\s*weeks?\b")),
    ("pt_discharge_summary.pdf", "pt_visit_count", "C3", r"visits", rx(r"\b24\b")),
    ("surgeon_consult_note.pdf", "pt_visit_count", "C3", r"visits", rx(r"\b24\b")),
    ("denial_letter.pdf", "conservative_care_required", "C4", r"6 months", rx(r"\b6\s*months?\b")),
    ("medical_policy_MP-214.pdf", "conservative_care_required", "C4", r"At least 3 months", rx(r"\b3\s*months?\b")),
    ("denial_letter.pdf", "injections", "C5", r"no interventional", rx(r"\b(no|not|none|without)\b")),
    ("surgeon_consult_note.pdf", "injections", "C5", r"11/12/2025", rx(r"11/12/2025", r"12/17/2025")),
    ("mri_report.pdf", "spondylolisthesis_grade", "C6", r"L5$", rx_not(r"\b(grade\s*)?(I|1)\b", r"\b(II|2)\b")),
    ("surgeon_consult_note.pdf", "spondylolisthesis_grade", "C6", r".", rx(r"\b(II|2)\b")),
    ("surgeon_consult_note.pdf", "motor_strength", "C7", r"^Progressive", rx(r"4/5")),
    ("pt_discharge_summary.pdf", "motor_strength", "C7", r"^strength", rx_not(r"5/5", r"4/5")),
    ("surgeon_consult_note.pdf", "smoking_status", "C8", r"former", rx(r"former|quit|denies")),
    ("pt_discharge_summary.pdf", "smoking_status", "C8", r"current smoker", rx_not(r"current", r"former|quit")),
    ("mri_report.pdf", "mri_date", "D1", r"EXAM DATE", date_check(datetime(2026, 1, 20).date())),
    ("surgeon_consult_note.pdf", "mri_date", "D1", r"MRI", date_check(datetime(2026, 1, 20).date())),
]


# ------------------------------------- offline: expectations vs answer key

EXPECTATION_IDS = [f"{e[0]}:{e[1]}" for e in LIVE_EXPECTATIONS]


def test_expectation_fields_are_real_fields():
    """Every expectation names a real schema field and a file in the key.
    Fails if an expectation has a typo'd field or file name."""
    for file, field, *_ in LIVE_EXPECTATIONS:
        assert field in EXPECTED_FIELDS, field
        assert file in KEY["files"], file


@pytest.mark.parametrize("file,field,item,selector,check", LIVE_EXPECTATIONS, ids=EXPECTATION_IDS)
def test_expectation_maps_to_exactly_one_key_entry(file, field, item, selector, check):
    """The (file, item, selector) picks exactly one location in answer_key.json.
    Fails if the item is unknown, or the selector matches zero or several key locations."""
    assert item in KEY_ITEMS, f"{file}:{field}: item {item} not in answer_key.json"
    found = key_locations(item, file, selector)
    assert len(found) == 1, (
        f"{file}:{field} ({item}, selector {selector!r}) matches {len(found)} key locations: "
        f"{[(l['page'], l['value']) for l in found]}"
    )


@pytest.mark.parametrize("file,field,item,selector,check", LIVE_EXPECTATIONS, ids=EXPECTATION_IDS)
def test_expectation_check_accepts_the_key_value(file, field, item, selector, check):
    """The hardcoded check passes on the answer key's own value string for that location.
    Fails (naming the expectation and key value) if the check rejects the key text or cannot run on it."""
    found = key_locations(item, file, selector)
    if len(found) != 1:
        pytest.skip("selector problem reported by test_expectation_maps_to_exactly_one_key_entry")
    key_value = found[0]["value"]
    try:
        ok = check(key_value)
    except Exception as exc:  # check cannot run on the key's text (e.g. unparseable date)
        pytest.fail(f"{file}:{field} ({item}): check could not run on key value {key_value!r}: {exc!r}")
    assert ok, f"{file}:{field} ({item}): check rejects key value {key_value!r}"


def test_every_conflict_item_has_an_expectation():
    """Each of C1-C8 is used by at least one expectation.
    Fails if a conflict in the key has no live expectation."""
    used = {e[2] for e in LIVE_EXPECTATIONS}
    missing = [i for i in KEY_ITEMS if re.fullmatch(r"C[1-8]", i) and i not in used]
    assert not missing, f"no expectation for {missing}"


def test_every_primary_key_location_is_covered():
    """Each location with role 'primary' in C1-C8 is claimed by an expectation.
    Fails (listing the location) if a conflicting value in the key is never checked."""
    claimed = {(e[2], l["file"], l["page"], l["value"])
               for e in LIVE_EXPECTATIONS for l in key_locations(e[2], e[0], e[3])}
    unclaimed = [
        (iid, l["file"], l["page"], l["value"])
        for iid, item in KEY_ITEMS.items() if re.fullmatch(r"C[1-8]", iid)
        for l in item["locations"]
        if l["role"] == "primary" and (iid, l["file"], l["page"], l["value"]) not in claimed
    ]
    assert not unclaimed, f"primary key locations with no expectation: {unclaimed}"


@pytest.fixture(scope="module")
def live_results(case):
    from dotenv import load_dotenv
    from google import genai

    load_dotenv()  # GEMINI_API_KEY; never printed
    client = genai.Client()
    return extract_case(case, client, cache_dir=CACHE_DIR)


@pytest.mark.live
@pytest.mark.parametrize("file,field,item,selector,check", LIVE_EXPECTATIONS,
                         ids=[f"{e[0]}:{e[1]}" for e in LIVE_EXPECTATIONS])
def test_live_value_and_page_match_answer_key(live_results, file, field, item, selector, check):
    """Extracted value passes the key-derived check and the cited page is a page the key lists for it.
    Fails if the model returns null, a wrong value, or cites a page the key does not support."""
    f = getattr(live_results[file], field)
    assert f.value is not None, f"{file} {field}: got null"
    assert check(f.value), f"{file} {field}: unexpected value {f.value!r}"
    allowed = key_pages(item, file, selector)
    assert allowed, "answer key has no matching location (test bug)"
    assert f.page in allowed, f"{file} {field}: cited page {f.page}, key says {sorted(allowed)}"


@pytest.mark.live
@pytest.mark.parametrize("file", sorted(KEY["files"]))
def test_live_quotes_are_grounded_in_cited_page(live_results, case, file):
    """Every non-null fact's quote appears in the text of its cited page, for the real model output.
    Fails if the model paraphrases or invents quotes or cites the wrong page."""
    assert check_grounding(live_results[file], case[file]) == []
