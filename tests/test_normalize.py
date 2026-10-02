"""Phase 3 tests: normalize extracted facts into canonical typed values. Pure code, no model, no network.

Interface these tests define for pipeline/normalize.py:
    Parsed(status, value, raw)        status is "parsed" or "unparsed"; value is None when unparsed
    parse_date(raw)                   -> Parsed, value "YYYY-MM-DD"            (month/day/year order for numeric dates)
    parse_level(raw)                  -> Parsed, value "L4-L5"
    parse_grade(raw)                  -> Parsed, value int 1..5
    parse_duration(raw)               -> Parsed, value Duration(amount, unit)  unit "weeks" | "months"
    parse_visit_count(raw)            -> Parsed, value int
    parse_smoking(raw)                -> Parsed, value "current" | "former" | "never" | "unknown"
    parse_strength(raw)               -> Parsed, value int 0..5 (lowest grade stated in the text)
    parse_injections(raw)             -> Parsed, value Injections(count, dates) with dates ascending ISO
    NormFact(field, raw, page, quote, status, value)
    normalize_extraction(data)        -> {field: NormFact} for every NON-null fact only
    normalize_file(path)              -> same, reading an extraction JSON file
Every parser accepts any input (including None or garbage), never raises, and returns
status "unparsed" with value None and the raw input kept when it cannot parse. Parsers never guess.
"""
import json
import re
import socket
from pathlib import Path

import pytest

from pipeline import normalize as normalize_module
from pipeline.extract import FIELDS
from pipeline.normalize import (
    Duration,
    Injections,
    NormFact,
    normalize_extraction,
    normalize_file,
    parse_date,
    parse_duration,
    parse_grade,
    parse_injections,
    parse_level,
    parse_smoking,
    parse_strength,
    parse_visit_count,
)

CASE_DIR = Path("cases/bevredeau")
RUN_DIR = Path("outputs/examples/extraction_run1")

KEY = json.loads((CASE_DIR / "answer_key.json").read_text(encoding="utf-8"))
KEY_ITEMS = {item["id"]: item for item in KEY["items"]}

ALL_PARSERS = [parse_date, parse_level, parse_grade, parse_duration,
               parse_visit_count, parse_smoking, parse_strength, parse_injections]

# Which schema field each planted conflict / decoy is about (the key's "field" is free text).
ITEM_FIELD = {
    "C1": "surgery_date",
    "C2": "fusion_level",
    "C3": "pt_duration",
    "C4": "conservative_care_required",
    "C5": "injections",
    "C6": "spondylolisthesis_grade",
    "C7": "motor_strength",
    "C8": "smoking_status",
}
FIELD_PARSER = {
    "surgery_date": parse_date,
    "mri_date": parse_date,
    "fusion_level": parse_level,
    "spondylolisthesis_grade": parse_grade,
    "pt_duration": parse_duration,
    "conservative_care_required": parse_duration,
    "pt_visit_count": parse_visit_count,
    "smoking_status": parse_smoking,
    "motor_strength": parse_strength,
    "injections": parse_injections,
}


def load_run():
    """{pdf name: raw extraction dict} from the tracked example run."""
    return {p.name.split(".")[0] + ".pdf": json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(RUN_DIR.glob("*.json"))}


def normalized_run():
    return {doc: normalize_extraction(data) for doc, data in load_run().items()}


def primary_files(item_id):
    """The two files holding the conflicting (primary) values for a key item, read from the key."""
    return sorted({l["file"] for l in KEY_ITEMS[item_id]["locations"] if l["role"] == "primary"})


def primary_values(item_id):
    return {l["file"]: l["value"] for l in KEY_ITEMS[item_id]["locations"] if l["role"] == "primary"}


# ------------------------------------------------------------ parser unit tests

def check_table(parser, table):
    for raw, expected in table:
        result = parser(raw)
        assert result.status == "parsed", f"{parser.__name__}({raw!r}) came back unparsed"
        assert result.value == expected, f"{parser.__name__}({raw!r}) -> {result.value!r}, wanted {expected!r}"
        assert result.raw == raw


def check_unparsed(parser, inputs):
    for raw in inputs:
        result = parser(raw)
        assert result.status == "unparsed", f"{parser.__name__}({raw!r}) should be unparsed, got {result.value!r}"
        assert result.value is None
        assert result.raw == raw


DATE_CASES = [
    ("01/20/2026", "2026-01-20"),
    ("1/5/2026", "2026-01-05"),
    ("03/04/2026", "2026-03-04"),  # numeric dates are month/day/year
    ("2026-01-20", "2026-01-20"),
    ("January 20, 2026", "2026-01-20"),
    ("Jan 20, 2026", "2026-01-20"),
    ("Jan. 20 2026", "2026-01-20"),
    ("20 January 2026", "2026-01-20"),
    ("March 3rd, 2026", "2026-03-03"),
    ("  03/14/2026.  ", "2026-03-14"),
    ("EXAM DATE: January 20, 2026", "2026-01-20"),
    ("Planned Date of Service: 03/14/2026", "2026-03-14"),
    ("MRI of the lumbar spine dated 01/20/2026 (Lakeview Imaging Center) was personally reviewed", "2026-01-20"),
    ("Scheduled for 03/21/2026, pending authorization", "2026-03-21"),
]
DATE_UNPARSEABLE = [
    "TBD",
    "sometime next spring",
    "02/30/2026",   # impossible day
    "13/01/2026",   # month 13: do not guess day/month order
    "01/20/26",     # two-digit year: do not guess the century
    "03/14/2026 or 03/21/2026",       # two different dates: ambiguous
    "10/01/2025 to 01/08/2026",       # a range, not one date
    "",
]


def test_parse_date_formats():
    """Many date formats, including a date inside a longer phrase, come out as ISO YYYY-MM-DD.
    Fails if a format is not handled, month/day are swapped, or the phrase text confuses the parser."""
    check_table(parse_date, DATE_CASES)


def test_parse_date_unparseable_stays_unparsed():
    """Impossible, ambiguous, two-digit-year, multi-date and non-date inputs are unparsed with raw kept.
    Fails if the parser guesses (day/month swap, century, picks one of two dates) or raises."""
    check_unparsed(parse_date, DATE_UNPARSEABLE)


LEVEL_CASES = [
    ("L4-L5", "L4-L5"),
    ("L4-5", "L4-L5"),
    ("L4/L5", "L4-L5"),
    ("L4/5", "L4-L5"),
    ("L4 - L5", "L4-L5"),
    ("l4-l5", "L4-L5"),
    ("L4–L5", "L4-L5"),  # en dash
    ("L5-S1", "L5-S1"),
    ("L5/S1", "L5-S1"),
    ("L5 - S1", "L5-S1"),
    ("Lumbar L4-5 fusion", "L4-L5"),
    ("L4-L5 posterior lumbar interbody fusion (PLIF), single level; CPT 22630", "L4-L5"),
    ("Service Reviewed: L5-S1 lumbar spinal fusion", "L5-S1"),
]
LEVEL_UNPARSEABLE = ["lumbar spine", "S1", "L4-L5 and L5-S1", "no level stated", ""]


def test_parse_level_notations():
    """Spine levels in different notations (L4-5, L4/L5, dashes, case, embedded) all become 'L4-L5' style.
    Fails if short notation is not expanded, separators are mishandled, or surrounding words interfere."""
    check_table(parse_level, LEVEL_CASES)


def test_parse_level_unparseable_stays_unparsed():
    """No level, a single vertebra, or two different levels is unparsed.
    Fails if the parser invents a level or silently keeps only the first of several."""
    check_unparsed(parse_level, LEVEL_UNPARSEABLE)


GRADE_CASES = [
    ("Grade I", 1),
    ("Grade II", 2),
    ("Grade III", 3),
    ("Grade IV", 4),
    ("Grade V", 5),
    ("grade ii", 2),
    ("Grade 2", 2),
    ("Grade 1 spondylolisthesis", 1),
    ("I", 1),
    ("II", 2),
    ("2", 2),
    ("Meyerding grade I", 1),
    ("Grade I anterolisthesis of L4 on L5, approximately 6 mm", 1),
    ("demonstrates Grade II spondylolisthesis at L4-L5 with bilateral facet arthropathy", 2),
]
GRADE_UNPARSEABLE = ["mild anterolisthesis", "Grade VII", "Grade I-II", "no grade given", ""]


def test_parse_grade_roman_and_arabic():
    """Roman numerals and digits, bare or inside a sentence, become integers (I -> 1, II -> 2, never II -> 1).
    Fails if II is read as I, nearby levels like L4/L5 are read as a grade, or lowercase is missed."""
    check_table(parse_grade, GRADE_CASES)


def test_parse_grade_unparseable_stays_unparsed():
    """Words without a grade, out-of-range grades, and grade ranges are unparsed.
    Fails if the parser picks one grade out of 'I-II' or accepts grade VII."""
    check_unparsed(parse_grade, GRADE_UNPARSEABLE)


DURATION_CASES = [
    ("4 weeks", Duration(amount=4, unit="weeks")),
    ("14 weeks", Duration(amount=14, unit="weeks")),
    ("only 4 weeks of physical therapy documented", Duration(amount=4, unit="weeks")),
    ("at least 6 months", Duration(amount=6, unit="months")),
    ("At least 3 months", Duration(amount=3, unit="months")),
    ("6-month course", Duration(amount=6, unit="months")),
    ("12 wks", Duration(amount=12, unit="weeks")),
    ("14-week program", Duration(amount=14, unit="weeks")),
    ("6 mo", Duration(amount=6, unit="months")),
    ("six months", Duration(amount=6, unit="months")),
    ("1.5 months", Duration(amount=1.5, unit="months")),
    ("The patient attended 24 visits over 14 weeks (10/01/2025 to 01/08/2026)", Duration(amount=14, unit="weeks")),
]
DURATION_UNPARSEABLE = [
    "an extended period",
    "4-6 weeks",                 # range
    "3 days",                    # unit other than weeks/months
    "10/01/2025 to 01/08/2026",  # dates only: do not compute a duration
    "6 weeks or 3 months",       # two different durations
    "",
]


def test_parse_duration_number_and_unit():
    """Durations come out as an amount plus weeks/months, ignoring 'at least', abbreviations, number words, hyphens, and other numbers like visit counts.
    Fails if the unit is converted or lost, '24 visits' is mistaken for the duration, or a form is missed."""
    check_table(parse_duration, DURATION_CASES)


def test_parse_duration_keeps_units_unconverted():
    """3 months and 12 weeks stay different values (no unit conversion).
    Fails if the parser converts between weeks and months."""
    assert parse_duration("3 months").value != parse_duration("12 weeks").value


def test_parse_duration_unparseable_stays_unparsed():
    """Vague text, ranges, other units, date-only text and two durations are unparsed.
    Fails if the parser guesses, computes a duration from dates, or picks one of two."""
    check_unparsed(parse_duration, DURATION_UNPARSEABLE)


VISIT_CASES = [
    ("24", 24),
    ("24 visits", 24),
    ("24 sessions", 24),
    ("visits: 24", 24),
    ("The patient attended 24 visits over 14 weeks (10/01/2025 to 01/08/2026)", 24),
    ("  7 visits  ", 7),
]
VISIT_UNPARSEABLE = ["many visits", "attended 24 of 36 visits", "10/01/2025", "", "two to three visits"]


def test_parse_visit_count_integer():
    """'24' and '24 visits' (and the same inside a sentence) both give the integer 24.
    Fails if the unit text breaks parsing or another number in the sentence (14 weeks, a date) is picked."""
    check_table(parse_visit_count, VISIT_CASES)


def test_parse_visit_count_unparseable_stays_unparsed():
    """Vague, ambiguous ('24 of 36'), date-only and empty inputs are unparsed.
    Fails if the parser guesses which number is the count."""
    check_unparsed(parse_visit_count, VISIT_UNPARSEABLE)


SMOKING_CASES = [
    ("current smoker, 1/2 pack per day", "current"),
    ("Current smoker", "current"),
    ("smokes daily", "current"),
    ("former smoker, quit 2019", "former"),
    ("ex-smoker", "former"),
    ("quit smoking in 2019", "former"),
    ("former smoker; no current tobacco use", "former"),
    ("never smoker", "never"),
    ("non-smoker", "never"),
    ("lifelong non-smoker", "never"),
    ("has never smoked", "never"),
    ("smoking status unknown", "unknown"),
    ("smoking status not documented", "unknown"),
]
SMOKING_UNPARSEABLE = [
    "Patient denies current nicotine use",   # cannot tell former from never: do not guess
    "former smoker, currently smoking half a pack per day",  # contradicts itself
    "Occasional alcohol use",
    "",
]


def test_parse_smoking_enum():
    """Smoking phrases map to current / former / never / unknown ('non-smoker' is never, not current).
    Fails if 'smoker' inside 'non-smoker' or 'ex-smoker' reads as current, or 'no current use' flips a former smoker to current."""
    check_table(parse_smoking, SMOKING_CASES)


def test_parse_smoking_unparseable_stays_unparsed():
    """Statements that do not determine status, or contradict themselves, are unparsed.
    Fails if 'denies current use' is guessed as never/former, or a contradiction is resolved silently."""
    check_unparsed(parse_smoking, SMOKING_UNPARSEABLE)


STRENGTH_CASES = [
    ("5/5", 5),
    ("4/5", 4),
    ("0/5", 0),
    ("4 / 5", 4),
    ("MRC grade 3/5", 3),
    ("strength 5/5 in both lower extremities", 5),
    ("5/5 throughout", 5),
    ("Ankle dorsiflexion 5/5 4/5", 4),   # table cells: right, left
    ("4/5 left, 5/5 right", 4),
    ("Progressive left foot dorsiflexion weakness, 4/5. All other lower extremity muscle groups 5/5", 4),
]
STRENGTH_UNPARSEABLE = ["weakness noted", "4+/5", "7/5", "strength intact", ""]


def test_parse_strength_numeric_grade():
    """Strength text gives the numeric grade out of 5; when several grades appear, the lowest (the weak muscle group) is used.
    Fails if '/5' formats are missed, the denominator is returned, or a normal 5/5 hides the 4/5 deficit."""
    check_table(parse_strength, STRENGTH_CASES)


def test_parse_strength_unparseable_stays_unparsed():
    """Text with no grade, plus-grades like 4+/5, and out-of-range grades are unparsed.
    Fails if '4+/5' is rounded to 4 or '7/5' is accepted."""
    check_unparsed(parse_strength, STRENGTH_UNPARSEABLE)


INJECTION_CASES = [
    ("Epidural steroid injections on 11/12/2025 and 12/17/2025",
     Injections(count=2, dates=["2025-11-12", "2025-12-17"])),
    ("ESI performed 12/17/2025", Injections(count=1, dates=["2025-12-17"])),
    ("Injections on December 17, 2025 and 11/12/2025",
     Injections(count=2, dates=["2025-11-12", "2025-12-17"])),   # mixed formats, sorted ascending
    ("Epidural steroid injections on 11/12/2025 and 12/17/2025 provided temporary relief only, with no durable improvement",
     Injections(count=2, dates=["2025-11-12", "2025-12-17"])),   # 'no' later in the sentence is not a negation
    ("3 epidural steroid injections", Injections(count=3, dates=[])),
    ("None", Injections(count=0, dates=[])),
    ("No injections", Injections(count=0, dates=[])),
    ("Patient has not had any epidural injections", Injections(count=0, dates=[])),
    ("no interventional pain management attempted in the submitted records "
     "(for example, epidural steroid injection or other image-guided spinal injection)",
     Injections(count=0, dates=[])),
]
INJECTION_UNPARSEABLE = ["injections discussed", "interventional options reviewed", ""]


def test_parse_injections_count_and_dates():
    """Injection text gives a count and ascending ISO dates, or count 0 with no dates for a negation.
    Fails if dates are not parsed or sorted, the count is not the number of dates, or the negation example text ('epidural steroid injection') is counted as an injection."""
    check_table(parse_injections, INJECTION_CASES)


def test_parse_injections_unparseable_stays_unparsed():
    """Text that neither negates nor gives a count or dates is unparsed.
    Fails if the parser assumes none or one."""
    check_unparsed(parse_injections, INJECTION_UNPARSEABLE)


@pytest.mark.parametrize("parser", ALL_PARSERS, ids=lambda p: p.__name__)
def test_parsers_never_raise_on_garbage(parser):
    """Every parser returns an unparsed result (raw kept) for None, numbers, control characters, huge and symbol-only input.
    Fails if any parser raises (TypeError on None/int, regex blowup, index error) instead of returning unparsed."""
    for raw in [None, 42, 3.5, "", "   ", "\x00\x01", "?!@#$%^&*()", "x" * 100_000, "é中文", ["a"], {"b": 1}]:
        result = parser(raw)
        assert result.status in ("parsed", "unparsed")
        if result.status == "unparsed":
            assert result.value is None
        assert result.raw == raw


# ---------------------------------------------------------- normalize_extraction

def test_every_schema_field_has_a_parser():
    """Each of the ten extraction fields is normalized by the right parser and produces a NormFact.
    Fails if a field is not wired to a parser, or is wired to the wrong one."""
    samples = {
        "surgery_date": "03/14/2026", "mri_date": "January 20, 2026", "fusion_level": "L4-5",
        "spondylolisthesis_grade": "Grade II", "pt_duration": "14 weeks",
        "conservative_care_required": "at least 3 months", "pt_visit_count": "24 visits",
        "smoking_status": "former smoker", "motor_strength": "4/5", "injections": "none",
    }
    assert set(samples) == set(FIELDS)
    data = {f: {"value": v, "page": 1, "quote": v} for f, v in samples.items()}
    out = normalize_extraction(data)
    assert set(out) == set(FIELDS)
    for field, nf in out.items():
        assert isinstance(nf, NormFact)
        assert nf.status == "parsed", field
        assert nf.value == FIELD_PARSER[field](samples[field]).value, field


def test_null_facts_are_omitted_and_missing_fields_tolerated():
    """Only non-null facts appear in the output; null facts and absent fields produce nothing.
    Fails if null facts become entries (e.g. an 'unparsed' NormFact with no raw) or absent fields raise KeyError."""
    data = {
        "surgery_date": {"value": "03/14/2026", "page": 1, "quote": "Planned Date of Service: 03/14/2026"},
        "fusion_level": {"value": None, "page": None, "quote": None},
    }
    assert set(normalize_extraction(data)) == {"surgery_date"}
    assert normalize_extraction({}) == {}


def test_unparsed_fact_keeps_raw_page_quote():
    """A fact whose value cannot be parsed is returned as unparsed with value None and raw/page/quote intact.
    Fails if the fact is dropped, raises, or its raw text is lost or altered."""
    data = {"mri_date": {"value": "sometime in spring", "page": 2, "quote": "exam sometime in spring"}}
    nf = normalize_extraction(data)["mri_date"]
    assert (nf.field, nf.status, nf.value) == ("mri_date", "unparsed", None)
    assert (nf.raw, nf.page, nf.quote) == ("sometime in spring", 2, "exam sometime in spring")


def test_normalize_file_reads_extraction_json(tmp_path):
    """normalize_file reads an extraction JSON file from disk and matches normalize_extraction on the same data.
    Fails if the file path input is unsupported or gives different results."""
    data = {"surgery_date": {"value": "03/14/2026", "page": 1, "quote": "Planned Date of Service: 03/14/2026"}}
    path = tmp_path / "doc.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert normalize_file(path) == normalize_extraction(data)


# ------------------------------------------------- example run (tracked in git)

def test_example_run_has_one_file_per_document():
    """outputs/examples/extraction_run1 holds exactly one extraction JSON per case document.
    Fails on a fresh clone if the example files are missing, extra, or misnamed."""
    assert set(load_run()) == set(KEY["files"])


def test_raw_page_and_quote_pass_through_unchanged():
    """For every non-null fact in the example run, raw, page and quote equal the extraction file exactly, and null facts are absent.
    Fails if normalization strips, reformats, or overwrites raw text/quotes, changes a page, or keeps null facts."""
    for doc, data in load_run().items():
        out = normalize_extraction(data)
        non_null = {f for f, fact in data.items() if fact["value"] is not None}
        assert set(out) == non_null, doc
        for field in non_null:
            assert out[field].raw == data[field]["value"], (doc, field)
            assert out[field].page == data[field]["page"], (doc, field)
            assert out[field].quote == data[field]["quote"], (doc, field)
            assert out[field].field == field


def test_normalize_file_on_every_example_file():
    """normalize_file works on each real example file and agrees with normalize_extraction.
    Fails if the file reader mishandles real files (encoding, extra keys)."""
    for path in sorted(RUN_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert normalize_file(path) == normalize_extraction(data)


def test_every_fact_in_the_example_run_parses():
    """Every non-null fact in the real model output normalizes to a parsed value.
    Fails (naming file, field, raw text) if a parser cannot handle something the model actually produced."""
    unparsed = [(doc, f, nf.raw) for doc, out in normalized_run().items()
                for f, nf in out.items() if nf.status != "parsed"]
    assert not unparsed, f"unparsed facts: {unparsed}"


def test_canonical_value_types_in_the_example_run():
    """Canonical values have the promised types: ISO date strings, 'Lx-Ly' levels, ints, Duration, enum strings, Injections.
    Fails if a parser returns the wrong type or format (e.g. a grade as 'II', a date as a US string)."""
    iso, level = re.compile(r"\d{4}-\d{2}-\d{2}"), re.compile(r"[CTLS]\d{1,2}-[CTLS]\d{1,2}")
    for doc, out in normalized_run().items():
        for field, nf in out.items():
            v = nf.value
            if field in ("surgery_date", "mri_date"):
                assert iso.fullmatch(v), (doc, field, v)
            elif field == "fusion_level":
                assert level.fullmatch(v), (doc, field, v)
            elif field in ("spondylolisthesis_grade", "pt_visit_count", "motor_strength"):
                assert isinstance(v, int) and not isinstance(v, bool), (doc, field, v)
            elif field in ("pt_duration", "conservative_care_required"):
                assert isinstance(v, Duration) and v.unit in ("weeks", "months"), (doc, field, v)
            elif field == "smoking_status":
                assert v in ("current", "former", "never", "unknown"), (doc, field, v)
            elif field == "injections":
                assert isinstance(v, Injections) and v.count >= 0, (doc, field, v)
                assert all(iso.fullmatch(d) for d in v.dates) and v.dates == sorted(v.dates)


# ------------------------------------------------------------------ decoys (D1, D2)

def test_decoy_d1_mri_date_matches_across_documents():
    """The MRI exam date in the MRI report and in the surgeon note normalize to the same value.
    Fails if 'January 20, 2026' and '01/20/2026' (inside a sentence) do not meet at one ISO date."""
    run = normalized_run()
    a, b = run["mri_report.pdf"]["mri_date"], run["surgeon_consult_note.pdf"]["mri_date"]
    assert a.status == b.status == "parsed"
    assert a.value == b.value


def test_decoy_d1_and_d2_key_strings_match():
    """Decoy values read from answer_key.json at runtime (D1 dates, D2 levels) normalize equal in each pair.
    Fails if either decoy pair still differs after parsing, or if the key's decoys change into something unparseable."""
    for item_id, parser in (("D1", parse_date), ("D2", parse_level)):
        values = [l["value"] for l in KEY_ITEMS[item_id]["locations"]]
        assert len(values) == 2
        results = [parser(v) for v in values]
        assert all(r.status == "parsed" for r in results), (item_id, values)
        assert results[0].value == results[1].value, (item_id, values, [r.value for r in results])


def test_decoy_d2_level_notation_matches():
    """'L4-5' and 'L4-L5' normalize to the same level.
    Fails if short notation is not expanded to match the long form."""
    a, b = parse_level("L4-5"), parse_level("L4-L5")
    assert a.status == b.status == "parsed"
    assert a.value == b.value


# ------------------------------------------------------ planted conflicts (C1-C8)

C_ITEMS = [i for i in KEY_ITEMS if re.fullmatch(r"C[1-8]", i)]


def test_key_has_the_expected_conflict_items():
    """The key still has C1-C8 and each has exactly two primary files (so the preservation tests below are meaningful).
    Fails if the key's conflicts change shape and the mapping in this file is stale."""
    assert sorted(C_ITEMS) == sorted(ITEM_FIELD)
    for item_id in C_ITEMS:
        assert len(primary_files(item_id)) == 2, item_id


@pytest.mark.parametrize("item_id", sorted(ITEM_FIELD))
def test_conflict_survives_normalization_in_extracted_data(item_id):
    """For each planted conflict, the two primary documents' normalized values (from the example run) are both parsed and still differ.
    Fails if normalization collapses a real conflict into equal values, or either side is unparsed."""
    field = ITEM_FIELD[item_id]
    run = normalized_run()
    file_a, file_b = primary_files(item_id)
    fa, fb = run[file_a].get(field), run[file_b].get(field)
    assert fa is not None and fb is not None, f"{item_id}: {field} missing in {file_a} or {file_b}"
    assert fa.status == fb.status == "parsed", f"{item_id}: {fa.raw!r} / {fb.raw!r}"
    assert fa.value != fb.value, f"{item_id}: both normalize to {fa.value!r} ({fa.raw!r} vs {fb.raw!r})"


@pytest.mark.parametrize("item_id", sorted(ITEM_FIELD))
def test_conflict_survives_normalization_in_key_strings(item_id):
    """Same check on the answer key's own primary value strings, read at runtime and parsed with the field's parser.
    Fails if the parsers collapse the key's conflicting strings or cannot parse the key's wording."""
    parser = FIELD_PARSER[ITEM_FIELD[item_id]]
    values = list(primary_values(item_id).values())
    results = [parser(v) for v in values]
    assert all(r.status == "parsed" for r in results), f"{item_id}: {values} -> {[r.status for r in results]}"
    assert results[0].value != results[1].value, f"{item_id}: both normalize to {results[0].value!r} ({values})"


# ------------------------------------------------------------- purity / hygiene

def test_normalize_is_pure_no_network_no_model(monkeypatch):
    """Normalizing the example run works with sockets disabled, and the module does not reference the Gemini SDK.
    Fails if the code opens a network connection or imports/calls google.genai."""
    def blocked(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket, "socket", blocked)
    assert normalized_run()
    source = Path(normalize_module.__file__).read_text(encoding="utf-8")
    assert "genai" not in source and "interactions" not in source


def test_no_answer_key_values_in_pipeline_code():
    """None of the key's location strings, full dates, or the patient/insurer names appear in pipeline/normalize.py.
    Fails if answer-key values are hardcoded (special-casing a conflict or decoy)."""
    source = Path(normalize_module.__file__).read_text(encoding="utf-8").lower()
    banned = {KEY["case"]["patient"], KEY["case"]["member_id"], KEY["case"]["prior_authorization"]}
    for item in KEY["items"]:
        for loc in item["locations"]:
            banned.add(loc["value"])
            banned.update(re.findall(r"\d{1,2}/\d{1,2}/\d{4}|[A-Z][a-z]+ \d{1,2}, \d{4}", loc["value"]))
    hits = [b for b in banned if b.lower() in source]
    assert not hits, f"answer-key values found in pipeline code: {hits}"
