"""Phase 4: compare normalized facts across documents. Pure code: no model, no network.

Facts are grouped by field. Only parsed facts are compared. A field whose parsed values all agree is an
agreement; a field with two or more distinct values is one conflict whose sides are those values.
This module never says which side is right.
"""
import json
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from pipeline.normalize import normalize_file


class Source(BaseModel):
    file: str
    page: Optional[int] = None
    quote: Optional[str] = None
    raw: Any = None


class Side(BaseModel):
    value: Any
    sources: list[Source]


class Conflict(BaseModel):
    field: str
    sides: list[Side]


class Agreement(BaseModel):
    field: str
    value: Any
    sources: list[Source]


class Uncomparable(BaseModel):
    field: str
    reason: str  # "unparsed" or "mixed_units"
    sources: list[Source]


class Comparison(BaseModel):
    conflicts: list[Conflict] = []
    agreements: list[Agreement] = []
    uncomparable: list[Uncomparable] = []


def _native(value):
    """JSON-native copy of a value, with whole-number floats as ints so 14 and 14.0 are the same value."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_native(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _key(value):
    return json.dumps(value, sort_keys=True, default=str)


def _source(file, fact):
    return Source(file=file, page=fact.page, quote=fact.quote, raw=fact.raw)


def _source_order(source):
    return (source.file, source.page is None, source.page or 0)


def _units(values):
    return {v["unit"] for v in values if isinstance(v, dict) and "unit" in v}


def compare(facts_by_doc):
    """Compare {document: {field: NormFact}} across documents and return a Comparison."""
    by_field = {}
    for file, facts in (facts_by_doc or {}).items():
        if not isinstance(facts, dict):
            continue
        for field, fact in facts.items():
            by_field.setdefault(field, []).append((file, fact))

    conflicts, agreements, uncomparable = [], [], []
    for field in sorted(by_field):
        parsed, unparsed = [], []
        for file, fact in by_field[field]:
            if fact.status == "parsed" and fact.value is not None:
                parsed.append((file, fact, _native(fact.value)))
            else:
                unparsed.append((file, fact))

        if unparsed:
            uncomparable.append(Uncomparable(
                field=field, reason="unparsed",
                sources=sorted((_source(f, x) for f, x in unparsed), key=_source_order)))

        if len(_units(v for _, _, v in parsed)) > 1:
            uncomparable.append(Uncomparable(
                field=field, reason="mixed_units",
                sources=sorted((_source(f, x) for f, x, _ in parsed), key=_source_order)))
            continue

        if len(parsed) < 2:
            continue  # a field in only one document is neither an agreement nor a conflict

        groups = {}
        for file, fact, value in parsed:
            groups.setdefault(_key(value), (value, []))[1].append(_source(file, fact))
        sides = [Side(value=value, sources=sorted(sources, key=_source_order))
                 for _, (value, sources) in sorted(groups.items())]
        if len(sides) == 1:
            agreements.append(Agreement(field=field, value=sides[0].value, sources=sides[0].sources))
        else:
            conflicts.append(Conflict(field=field, sides=sides))

    uncomparable.sort(key=lambda u: (u.field, u.reason))
    return Comparison(conflicts=conflicts, agreements=agreements, uncomparable=uncomparable)


def compare_run(run_dir):
    """Compare a folder of extraction JSON files named <stem>.<anything>.json (document = stem + '.pdf')."""
    facts = {p.name.split(".")[0] + ".pdf": normalize_file(p) for p in sorted(Path(run_dir).glob("*.json"))}
    return compare(facts)
