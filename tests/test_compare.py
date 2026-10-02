"""Phase 4 tests: compare normalized facts across documents. Pure code, no model, no network.

Interface these tests define for pipeline/compare.py:
    compare(facts_by_doc)   -> Comparison
        facts_by_doc is {document name: {field: NormFact}} (what normalize_file returns per document)
    compare_run(run_dir)    -> Comparison, from a folder of extraction JSON files named <stem>.<anything>.json
                               (document name = stem + ".pdf"), via normalize_file
    Comparison(conflicts, agreements, uncomparable)
    Conflict(field, sides)               one per field with two or more distinct parsed values
    Side(value, sources)                 one distinct value and every document holding it
    Agreement(field, value, sources)     all parsed values equal, in two or more documents
    Uncomparable(field, reason, sources) reason "unparsed" or "mixed_units"; raw text kept
    Source(file, page, quote, raw)
Values in the output are JSON-native (a Duration becomes {"amount", "unit"}, Injections becomes
{"count", "dates"}) so a Comparison round-trips through JSON unchanged.
Ordering: conflicts, agreements and uncomparable sorted by field (then reason); sides sorted by
json.dumps(value, sort_keys=True); sources sorted by (file, page). The comparison never says
which side is right.
"""
import json
import random
import re
import socket
from pathlib import Path

import pytest

from pipeline import compare as compare_module
from pipeline.compare import (
    Agreement,
    Comparison,
    Conflict,
    Side,
    Source,
    Uncomparable,
    compare,
    compare_run,
)
from pipeline.normalize import Duration, Injections, NormFact, normalize_extraction, normalize_file

CASE_DIR = Path("cases/bevredeau")
RUN_DIR = Path("outputs/examples/extraction_run1")

KEY = json.loads((CASE_DIR / "answer_key.json").read_text(encoding="utf-8"))
KEY_ITEMS = {item["id"]: item for item in KEY["items"]}

# Which schema field each planted conflict / decoy is about (the key's "field" is free text).
ITEM_FIELD = {
    "C1": "surgery_date", "C2": "fusion_level", "C3": "pt_duration", "C4": "conservative_care_required",
    "C5": "injections", "C6": "spondylolisthesis_grade", "C7": "motor_strength", "C8": "smoking_status",
}
DECOY_FIELD = {"D1": "mri_date", "D2": "fusion_level"}


# ---------------------------------------------------------------- helpers

def nf(field, value, *, page=1, quote=None, raw=None, status="parsed"):
    """A NormFact. For status 'parsed' the value is the canonical value; raw defaults to str(value)."""
    raw = str(value) if raw is None else raw
    return NormFact(field=field, raw=raw, page=page, quote=quote if quote is not None else f"quote {raw}",
                    status=status, value=value if status == "parsed" else None)


def unparsed(field, raw, page=1):
    return nf(field, None, raw=raw, page=page, status="unparsed")


def docs(**by_doc):
    """docs(a=[nf, nf], b=[nf]) -> {'a.pdf': {field: NormFact}, 'b.pdf': {...}}"""
    return {f"{name}.pdf": {f.field: f for f in facts} for name, facts in by_doc.items()}


def conflict_for(c, field):
    return next((x for x in c.conflicts if x.field == field), None)


def agreement_for(c, field):
    return next((x for x in c.agreements if x.field == field), None)


def side_files(side):
    return {s.file for s in side.sources}


def side_index(conflict, file):
    for i, side in enumerate(conflict.sides):
        if file in side_files(side):
            return i
    return None


def separated(conflict, file_a, file_b):
    """True if both files are in the conflict, on different sides."""
    a, b = side_index(conflict, file_a), side_index(conflict, file_b)
    return a is not None and b is not None and a != b


def load_raw_run():
    return {p.name.split(".")[0] + ".pdf": json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(RUN_DIR.glob("*.json"))}


def normalized_run():
    return {doc: normalize_extraction(data) for doc, data in load_raw_run().items()}


@pytest.fixture(scope="module")
def run():
    return compare(normalized_run())


def key_locations(item_id):
    return KEY_ITEMS[item_id]["locations"]


def primary_files(item_id):
    return sorted({l["file"] for l in key_locations(item_id) if l["role"] == "primary"})


# ---------------------------------------------------- unit: agreements and conflicts

def test_equal_values_make_an_agreement():
    """Two documents with the same parsed value give one agreement listing both sources, and no conflict.
    Fails if equal values are reported as a conflict, dropped, or lose a source."""
    c = compare(docs(a=[nf("surgery_date", "2026-03-14", page=1)], b=[nf("surgery_date", "2026-03-14", page=4)]))
    assert c.conflicts == [] and c.uncomparable == []
    [ag] = c.agreements
    assert isinstance(ag, Agreement) and ag.field == "surgery_date" and ag.value == "2026-03-14"
    assert [(s.file, s.page) for s in ag.sources] == [("a.pdf", 1), ("b.pdf", 4)]


def test_differing_values_make_one_conflict_with_all_sides():
    """Two documents with different parsed values give one conflict with two sides, each carrying file, page, quote and raw.
    Fails if the conflict is missing, split in two, or a side loses its citation."""
    c = compare(docs(
        a=[nf("fusion_level", "L5-S1", page=1, quote="Service Reviewed: L5-S1", raw="L5-S1")],
        b=[nf("fusion_level", "L4-L5", page=4, quote="Planned procedure: L4-L5", raw="L4-5")],
    ))
    assert c.agreements == [] and c.uncomparable == []
    [cf] = c.conflicts
    assert isinstance(cf, Conflict) and cf.field == "fusion_level" and len(cf.sides) == 2
    by_value = {s.value: s for s in cf.sides}
    assert all(isinstance(s, Side) for s in cf.sides)
    assert by_value["L5-S1"].sources == [Source(file="a.pdf", page=1, quote="Service Reviewed: L5-S1", raw="L5-S1")]
    assert by_value["L4-L5"].sources == [Source(file="b.pdf", page=4, quote="Planned procedure: L4-L5", raw="L4-5")]


def test_three_documents_two_agreeing_make_one_conflict_with_two_sides():
    """Two documents agreeing and one differing give ONE conflict with two sides (2 sources and 1 source).
    Fails if the agreeing pair is reported as a separate agreement or conflict, or the field gets a conflict per pair."""
    c = compare(docs(
        a=[nf("pt_visit_count", 4)], b=[nf("pt_visit_count", 24)], c=[nf("pt_visit_count", 24)],
    ))
    assert len(c.conflicts) == 1 and c.agreements == []
    sides = {s.value: side_files(s) for s in c.conflicts[0].sides}
    assert sides == {4: {"a.pdf"}, 24: {"b.pdf", "c.pdf"}}


def test_three_distinct_values_make_one_conflict_with_three_sides():
    """Three different values for a field give a single conflict with three sides.
    Fails if the comparison only keeps two sides or emits several conflicts for one field."""
    c = compare(docs(a=[nf("motor_strength", 3)], b=[nf("motor_strength", 4)], c=[nf("motor_strength", 5)]))
    assert len(c.conflicts) == 1 and len(c.conflicts[0].sides) == 3


def test_structured_values_compare_by_content():
    """Duration and Injections values are equal when their contents are equal (14 equals 14.0), different otherwise.
    Fails if values are compared by object identity, or 14 weeks and 14.0 weeks are treated as different."""
    same = compare(docs(
        a=[nf("pt_duration", Duration(amount=14, unit="weeks"))],
        b=[nf("pt_duration", Duration(amount=14.0, unit="weeks"))],
    ))
    assert len(same.agreements) == 1 and same.conflicts == []
    assert same.agreements[0].value == {"amount": 14, "unit": "weeks"}

    differ = compare(docs(
        a=[nf("injections", Injections(count=2, dates=["2025-11-12", "2025-12-17"]))],
        b=[nf("injections", Injections(count=2, dates=["2025-11-12", "2025-12-18"]))],
        c=[nf("injections", Injections(count=0, dates=[]))],
    ))
    assert len(differ.conflicts) == 1 and len(differ.conflicts[0].sides) == 3
    assert {"count": 0, "dates": []} in [s.value for s in differ.conflicts[0].sides]


def test_page_none_is_carried_through():
    """A fact with no page still appears in its side with page None.
    Fails if missing pages raise or are dropped from the output."""
    c = compare(docs(a=[nf("mri_date", "2026-01-20", page=None)], b=[nf("mri_date", "2026-02-01", page=2)]))
    pages = sorted((s.file, s.page) for side in c.conflicts[0].sides for s in side.sources)
    assert pages == [("a.pdf", None), ("b.pdf", 2)]


def test_comparison_does_not_pick_a_winner():
    """Conflict, side and source carry only the agreed keys; nothing like winner, correct, severity or helps/hurts.
    Fails if the comparison adds trust, severity or appeal-effect information (that is Phase 5)."""
    c = compare(docs(a=[nf("smoking_status", "current")], b=[nf("smoking_status", "former")]))
    dumped = c.model_dump(mode="json")
    assert set(dumped) == {"conflicts", "agreements", "uncomparable"}
    conflict = dumped["conflicts"][0]
    assert set(conflict) == {"field", "sides"}
    assert all(set(side) == {"value", "sources"} for side in conflict["sides"])
    assert all(set(src) == {"file", "page", "quote", "raw"} for side in conflict["sides"] for src in side["sources"])


# ---------------------------------------------------- unit: uncomparable and single-source

def test_unparsed_values_are_uncomparable_never_conflicts():
    """Two different unparsed raw texts are not a conflict; both go to uncomparable with raw, page and quote kept.
    Fails if unparsed text is compared (conflict from differing raw text) or its raw text is lost."""
    c = compare(docs(a=[unparsed("surgery_date", "sometime in spring", page=2)],
                     b=[unparsed("surgery_date", "TBD", page=3)]))
    assert c.conflicts == [] and c.agreements == []
    [u] = c.uncomparable
    assert isinstance(u, Uncomparable) and u.field == "surgery_date" and u.reason == "unparsed"
    assert sorted((s.file, s.page, s.raw) for s in u.sources) == [("a.pdf", 2, "sometime in spring"), ("b.pdf", 3, "TBD")]


def test_unparsed_fact_is_set_aside_but_parsed_ones_still_compare():
    """With two equal parsed values and one unparsed, the pair is an agreement and the unparsed one is uncomparable.
    With two differing parsed values and one unparsed, the conflict has two sides and the unparsed one is not a side.
    Fails if one unparsed fact poisons the whole field or is counted as a side."""
    agree = compare(docs(a=[nf("mri_date", "2026-01-20")], b=[nf("mri_date", "2026-01-20")],
                         c=[unparsed("mri_date", "unclear")]))
    assert len(agree.agreements) == 1 and agree.conflicts == []
    assert [s.file for s in agree.uncomparable[0].sources] == ["c.pdf"]

    differ = compare(docs(a=[nf("mri_date", "2026-01-20")], b=[nf("mri_date", "2026-02-02")],
                          c=[unparsed("mri_date", "unclear")]))
    assert len(differ.conflicts) == 1 and len(differ.conflicts[0].sides) == 2
    assert all("c.pdf" not in side_files(s) for s in differ.conflicts[0].sides)
    assert [s.file for s in differ.uncomparable[0].sources] == ["c.pdf"]


def test_mixed_duration_units_are_uncomparable_without_conversion():
    """4 weeks vs 3 months is uncomparable (reason mixed_units, raw kept), not a conflict and not an agreement.
    Fails if units are converted (12 weeks ~ 3 months) or the difference is reported as a conflict."""
    c = compare(docs(
        a=[nf("pt_duration", Duration(amount=12, unit="weeks"), raw="12 weeks")],
        b=[nf("pt_duration", Duration(amount=3, unit="months"), raw="3 months")],
    ))
    assert c.conflicts == [] and c.agreements == []
    [u] = c.uncomparable
    assert u.field == "pt_duration" and u.reason == "mixed_units"
    assert sorted(s.raw for s in u.sources) == ["12 weeks", "3 months"]


def test_mixed_units_make_the_whole_field_uncomparable():
    """If any documents give weeks and another gives months, the whole field is uncomparable (no partial conflict).
    Fails if the weeks pair is still compared while the months value is set aside."""
    c = compare(docs(
        a=[nf("pt_duration", Duration(amount=4, unit="weeks"))],
        b=[nf("pt_duration", Duration(amount=14, unit="weeks"))],
        c=[nf("pt_duration", Duration(amount=3, unit="months"))],
    ))
    assert c.conflicts == [] and c.agreements == []
    assert len(c.uncomparable) == 1 and len(c.uncomparable[0].sources) == 3


def test_same_unit_durations_still_compare():
    """4 weeks vs 14 weeks is a conflict; 3 months vs 6 months is a conflict.
    Fails if same-unit durations are wrongly treated as uncomparable."""
    c = compare(docs(
        a=[nf("pt_duration", Duration(amount=4, unit="weeks")), nf("conservative_care_required", Duration(amount=6, unit="months"))],
        b=[nf("pt_duration", Duration(amount=14, unit="weeks")), nf("conservative_care_required", Duration(amount=3, unit="months"))],
    ))
    assert sorted(x.field for x in c.conflicts) == ["conservative_care_required", "pt_duration"]
    assert c.uncomparable == []


def test_single_source_field_is_neither_agreement_nor_conflict():
    """A field with a parsed value in only one document appears in no list.
    Fails if a lone value is called an agreement (trivially) or a conflict."""
    c = compare(docs(a=[nf("smoking_status", "current")], b=[nf("mri_date", "2026-01-20")]))
    assert (c.conflicts, c.agreements, c.uncomparable) == ([], [], [])


# ---------------------------------------------------- unit: ordering, JSON, robustness

def test_output_order_is_deterministic():
    """Shuffling document and field order gives an identical Comparison and identical JSON; fields, sides and sources follow the stated sort.
    Fails if output order depends on dict insertion order or set iteration."""
    facts = {
        "z.pdf": [nf("surgery_date", "2026-03-21"), nf("fusion_level", "L4-L5"), nf("motor_strength", 5)],
        "a.pdf": [nf("surgery_date", "2026-03-14"), nf("fusion_level", "L5-S1"), nf("motor_strength", 5)],
        "m.pdf": [nf("surgery_date", "2026-03-21"), nf("fusion_level", "L4-L5"), nf("motor_strength", 4)],
    }
    baseline = compare(docs(**facts))
    for seed in range(8):
        rng = random.Random(seed)
        order = list(facts)
        rng.shuffle(order)
        shuffled = {name: rng.sample(facts[name], len(facts[name])) for name in order}
        again = compare(docs(**shuffled))
        assert again == baseline
        assert again.model_dump_json() == baseline.model_dump_json()
    assert [x.field for x in baseline.conflicts] == sorted(x.field for x in baseline.conflicts)
    for cf in baseline.conflicts:
        keys = [json.dumps(s.value, sort_keys=True) for s in cf.sides]
        assert keys == sorted(keys)
        for side in cf.sides:
            assert [s.file for s in side.sources] == sorted(s.file for s in side.sources)


def test_json_round_trip_is_unchanged_with_structured_values():
    """A Comparison containing conflicts, agreements and uncomparable (with Duration and Injections values) survives JSON dump and load unchanged.
    Fails if values stay as Python objects that come back as plain dicts, or any list/field changes in the round trip."""
    c = compare(docs(
        a=[nf("pt_duration", Duration(amount=4, unit="weeks")), nf("injections", Injections(count=0, dates=[])),
           nf("mri_date", "2026-01-20"), unparsed("surgery_date", "TBD")],
        b=[nf("pt_duration", Duration(amount=14, unit="weeks")),
           nf("injections", Injections(count=2, dates=["2025-11-12", "2025-12-17"])),
           nf("mri_date", "2026-01-20"), nf("surgery_date", "2026-03-21")],
        c=[nf("conservative_care_required", Duration(amount=6, unit="months"))],
        d=[nf("conservative_care_required", Duration(amount=3, unit="months"))],
    ))
    assert c.conflicts and c.agreements
    text = c.model_dump_json()
    assert Comparison.model_validate_json(text) == c
    assert json.loads(json.dumps(c.model_dump(mode="json"))) == c.model_dump(mode="json")


@pytest.mark.parametrize("bad_input", [
    {}, None, {"a.pdf": {}}, {"a.pdf": {}, "b.pdf": {}},
], ids=["empty", "none", "one-empty-doc", "two-empty-docs"])
def test_empty_input_gives_empty_comparison(bad_input):
    """Empty or missing input returns an empty Comparison instead of raising.
    Fails if empty input raises (StopIteration, KeyError, TypeError) or returns None."""
    c = compare(bad_input)
    assert isinstance(c, Comparison)
    assert (c.conflicts, c.agreements, c.uncomparable) == ([], [], [])


def test_odd_values_do_not_raise():
    """Parsed facts whose value is unhashable, None, or of mixed types are handled without raising and never become a conflict by accident.
    Fails if the implementation puts values in sets/dict keys without handling dict/list values, or crashes on None."""
    odd = docs(
        a=[nf("injections", {"count": 1, "dates": ["2025-01-01"]}), nf("motor_strength", ["x"]), nf("smoking_status", None, raw="?")],
        b=[nf("injections", {"count": 1, "dates": ["2025-01-01"]}), nf("motor_strength", "4"), nf("smoking_status", "current")],
    )
    odd["a.pdf"]["smoking_status"] = NormFact(field="smoking_status", raw="?", page=1, quote="?", status="parsed", value=None)
    c = compare(odd)
    assert isinstance(c, Comparison)
    assert agreement_for(c, "injections") is not None


# ---------------------------------------------------- integration: the example run

def test_compare_run_matches_compare_of_normalized_files():
    """compare_run(folder) gives the same result as comparing the normalize_file output of each file.
    Fails if the folder reader maps files to documents differently or skips files."""
    facts = {p.name.split(".")[0] + ".pdf": normalize_file(p) for p in sorted(RUN_DIR.glob("*.json"))}
    assert compare_run(RUN_DIR) == compare(facts)


def test_key_conflict_items_are_the_ones_this_file_maps():
    """The key still has C1-C8 and D1-D2, each with two primary files, so the integration tests below are meaningful.
    Fails if the key changes shape and the item-to-field mapping in this file is stale."""
    assert sorted(i for i in KEY_ITEMS if re.fullmatch(r"C[1-8]", i)) == sorted(ITEM_FIELD)
    assert sorted(i for i in KEY_ITEMS if re.fullmatch(r"D\d", i)) == sorted(DECOY_FIELD)
    for item_id in list(ITEM_FIELD) + list(DECOY_FIELD):
        assert len(primary_files(item_id)) == 2, item_id


def test_conflicted_fields_equal_the_key_conflict_fields(run):
    """The fields with a conflict are exactly the fields of key items C1-C8.
    Fails if a planted conflict is missed (e.g. an unparsed or skipped field) or an extra conflict is found (e.g. a decoy)."""
    assert {c.field for c in run.conflicts} == {ITEM_FIELD[i] for i in ITEM_FIELD}
    assert len(run.conflicts) == len(ITEM_FIELD)


@pytest.mark.parametrize("item_id", sorted(ITEM_FIELD))
def test_each_planted_conflict_separates_the_key_files_and_cites_key_pages(run, item_id):
    """For each of C1-C8: the key's two primary files sit on different sides, every document in the conflict is one the key involves, and each cited page is a page the key lists for that file.
    Fails if the right documents are on the same side, a stray document appears, or a citation points to a page the key does not support."""
    conflict = conflict_for(run, ITEM_FIELD[item_id])
    assert conflict is not None, f"{item_id}: no conflict for {ITEM_FIELD[item_id]}"
    file_a, file_b = primary_files(item_id)
    assert separated(conflict, file_a, file_b), f"{item_id}: {file_a} and {file_b} are not on different sides"
    involved = set(KEY_ITEMS[item_id]["documents_involved"])
    for side in conflict.sides:
        for src in side.sources:
            assert src.file in involved, f"{item_id}: {src.file} not in key documents_involved"
            key_pages = {l["page"] for l in key_locations(item_id) if l["file"] == src.file}
            assert src.page in key_pages, f"{item_id}: {src.file} cites page {src.page}, key lists {sorted(key_pages)}"
            assert src.quote, f"{item_id}: {src.file} has no quote"


def test_decoy_documents_are_never_on_different_sides_of_their_own_field_conflict(run):
    """For D1 and D2, read at runtime from the key: the two documents involved are never separated in a conflict on the decoy's own field.
    (Other fields are excluded: the same two documents genuinely conflict on the grade, C6.)
    Fails if a format-only difference (date format, level notation) shows up as a disagreement."""
    for decoy, field in DECOY_FIELD.items():
        file_a, file_b = sorted(KEY_ITEMS[decoy]["documents_involved"])
        for conflict in run.conflicts:
            if conflict.field == field:
                assert not separated(conflict, file_a, file_b), f"{decoy}: {file_a}/{file_b} split in {field}"


def test_decoy_d1_mri_date_is_an_agreement_of_the_two_key_documents(run):
    """The MRI date is an agreement whose sources are exactly the two documents the key lists for D1, and no conflict exists for it.
    Fails if 'January 20, 2026' vs '01/20/2026' is reported as a conflict, or one document is missing from the agreement."""
    field = DECOY_FIELD["D1"]
    ag = agreement_for(run, field)
    assert ag is not None and conflict_for(run, field) is None
    assert {s.file for s in ag.sources} == set(KEY_ITEMS["D1"]["documents_involved"])


def test_decoy_d2_same_side_when_the_key_level_is_added_to_the_run(run):
    """The example run has no MRI level fact, so add one built from the key's own D2 MRI string (read at runtime), then compare.
    The MRI and surgeon note must land on the SAME side of the fusion level conflict, with the denial letter on the other.
    Fails if the notations 'L4-5' and 'L4-L5' normalize or compare differently."""
    field = DECOY_FIELD["D2"]
    mri_loc = next(l for l in key_locations("D2") if l["file"] == "mri_report.pdf")
    surgeon_file = next(l["file"] for l in key_locations("D2") if l["file"] != "mri_report.pdf")
    raw = load_raw_run()
    raw["mri_report.pdf"][field] = {"value": mri_loc["value"], "page": mri_loc["page"], "quote": mri_loc["value"]}
    c = compare({doc: normalize_extraction(data) for doc, data in raw.items()})
    conflict = conflict_for(c, field)
    assert conflict is not None
    assert side_index(conflict, "mri_report.pdf") == side_index(conflict, surgeon_file) is not None
    denial_file = next(f for f in primary_files("C2") if f != surgeon_file)
    assert separated(conflict, denial_file, surgeon_file)
    assert separated(conflict, denial_file, "mri_report.pdf")
    assert len(conflict.sides) == 2


def test_no_conflict_for_fields_the_key_does_not_list(run):
    """Every conflict is for a field mapped from C1-C8, and the visit count and MRI date are agreements.
    Fails if a field the key does not list gets a conflict, or a known agreement is missing."""
    allowed = set(ITEM_FIELD.values())
    assert all(c.field in allowed for c in run.conflicts)
    agreed = {a.field for a in run.agreements}
    assert {"pt_visit_count", "mri_date"} <= agreed
    assert agreed.isdisjoint({c.field for c in run.conflicts})


def test_example_run_has_nothing_uncomparable(run):
    """Every fact in the example run is parsed and no field mixes duration units, so uncomparable is empty.
    Fails if a parser regressed to unparsed on real output or units got mixed within a field."""
    assert run.uncomparable == []


def test_example_run_comparison_round_trips_through_json(run):
    """The real comparison (with Duration and Injections values) serializes to JSON and loads back unchanged.
    Fails if any real value type does not survive JSON."""
    assert Comparison.model_validate_json(run.model_dump_json()) == run


# ---------------------------------------------------------------- purity / hygiene

def test_compare_is_pure_no_network_no_model(monkeypatch):
    """Comparing the example run works with sockets disabled, and compare.py does not reference the Gemini SDK.
    Fails if the module opens a connection or imports/calls google.genai."""
    def blocked(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket, "socket", blocked)
    assert compare(normalized_run()).conflicts
    source = Path(compare_module.__file__).read_text(encoding="utf-8")
    assert "genai" not in source and "interactions" not in source and "google" not in source


def test_no_answer_key_values_in_compare_code():
    """None of the key's location strings, full dates, or the patient/member/authorization identifiers appear in pipeline/compare.py.
    Fails if key values are hardcoded (special-casing a conflict, decoy or field)."""
    source = Path(compare_module.__file__).read_text(encoding="utf-8").lower()
    banned = {KEY["case"]["patient"], KEY["case"]["member_id"], KEY["case"]["prior_authorization"]}
    for item in KEY["items"]:
        for loc in item["locations"]:
            banned.add(loc["value"])
            banned.update(re.findall(r"\d{1,2}/\d{1,2}/\d{4}|[A-Z][a-z]+ \d{1,2}, \d{4}", loc["value"]))
    hits = [b for b in banned if b.lower() in source]
    assert not hits, f"answer-key values found in pipeline code: {hits}"


def test_no_field_names_hardcoded_in_compare_code():
    """compare.py names none of the ten extraction fields, so no field is special-cased or skipped by name.
    Fails if a field name like 'surgery_date' appears in the comparison code (it must group by whatever fields the facts carry)."""
    source = Path(compare_module.__file__).read_text(encoding="utf-8")
    fields = ["surgery_date", "fusion_level", "pt_duration", "pt_visit_count", "conservative_care_required",
              "injections", "spondylolisthesis_grade", "motor_strength", "smoking_status", "mri_date"]
    assert [f for f in fields if f in source] == []
