"""Phase 3: turn extracted fact text into canonical typed values.

Pure code: no model, no network. Every parser takes any input and returns a Parsed result.
When it cannot parse, it returns status "unparsed" with value None and the raw input kept.
Parsers never guess: ambiguous or contradictory text is unparsed.
"""
import json
import re
from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel

FLAGS = re.IGNORECASE


class Parsed(BaseModel):
    status: Literal["parsed", "unparsed"]
    value: Any = None
    raw: Any = None


class Duration(BaseModel):
    amount: float
    unit: Literal["weeks", "months"]


class Injections(BaseModel):
    count: int
    dates: list[str]


class NormFact(BaseModel):
    field: str
    raw: Any
    page: Optional[int] = None
    quote: Optional[str] = None
    status: Literal["parsed", "unparsed"]
    value: Any = None


def _parser(fn):
    """Wrap fn(text) -> value or None into a parser that accepts anything and never raises."""
    def wrapper(raw):
        value = None
        if isinstance(raw, str):
            try:
                value = fn(raw)
            except Exception:
                value = None
        if value is None:
            return Parsed(status="unparsed", value=None, raw=raw)
        return Parsed(status="parsed", value=value, raw=raw)
    wrapper.__name__ = fn.__name__.lstrip("_")
    wrapper.__doc__ = fn.__doc__
    return wrapper


# ---------------------------------------------------------------- dates

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
          r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b\.?")
_ORD = r"(?:st|nd|rd|th)?"
_ISO_DATE = re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d-])")
_NUMERIC_DATE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4})(?![\d/])")
_MONTH_FIRST = re.compile(rf"\b{_MONTH}\s*(\d{{1,2}}){_ORD}\b\s*,?\s*(\d{{4}})\b", FLAGS)
_DAY_FIRST = re.compile(rf"\b(\d{{1,2}}){_ORD}\s+{_MONTH}\s*,?\s*(\d{{4}})\b", FLAGS)


def _make_date(y, m, d):
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def _find_dates(text):
    """All dates in text as date objects, or None if any date-looking text is invalid.
    Numeric dates are read month/day/year."""
    found = []
    for m in _ISO_DATE.finditer(text):
        found.append(_make_date(m.group(1), m.group(2), m.group(3)))
    for m in _NUMERIC_DATE.finditer(text):
        found.append(_make_date(m.group(3), m.group(1), m.group(2)))
    for m in _MONTH_FIRST.finditer(text):
        found.append(_make_date(m.group(3), MONTHS[m.group(1)[:3].lower()], m.group(2)))
    for m in _DAY_FIRST.finditer(text):
        found.append(_make_date(m.group(3), MONTHS[m.group(2)[:3].lower()], m.group(1)))
    if any(d is None for d in found):
        return None
    return found


@_parser
def parse_date(text):
    """One date anywhere in the text -> 'YYYY-MM-DD'. Zero, several different, or invalid dates -> unparsed."""
    found = _find_dates(text)
    if not found or len(set(found)) != 1:
        return None
    return found[0].isoformat()


# ---------------------------------------------------------------- spine level

_LEVEL = re.compile(r"\b([CTLS])(\d{1,2})\s*[-/]\s*(?:([CTLS])(\d{1,2})|(\d{1,2}))\b", FLAGS)


@_parser
def parse_level(text):
    """Spine level -> canonical 'Xn-Xm' form (letter plus number on both sides). A short second part reads as the
    next level on the same region. Zero or several levels -> unparsed."""
    text = text.replace("–", "-").replace("—", "-")
    levels = set()
    for m in _LEVEL.finditer(text):
        first_letter, first_num = m.group(1).upper(), int(m.group(2))
        if m.group(3):
            second_letter, second_num = m.group(3).upper(), int(m.group(4))
        else:
            second_letter, second_num = first_letter, int(m.group(5))
            if second_num != first_num + 1:
                return None  # a short second part that skips levels is a span, not one level
        levels.add(f"{first_letter}{first_num}-{second_letter}{second_num}")
    return levels.pop() if len(levels) == 1 else None


# ---------------------------------------------------------------- grade

ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}
_GRADE_TOKEN = r"(iii|ii|iv|i|v|[1-5])"
_GRADE = re.compile(rf"\bgrade\s*[:\-]?\s*{_GRADE_TOKEN}\b", FLAGS)
_GRADE_RANGE_TAIL = re.compile(rf"\s*[-–/]\s*{_GRADE_TOKEN}\b", FLAGS)
_GRADE_BARE = re.compile(rf"\s*{_GRADE_TOKEN}\s*", FLAGS)


def _grade_number(token):
    token = token.lower()
    return ROMAN[token] if token in ROMAN else int(token)


@_parser
def parse_grade(text):
    """Spondylolisthesis grade (roman or arabic, 1-5) -> int. Ranges or several grades -> unparsed."""
    grades = set()
    for m in _GRADE.finditer(text):
        if _GRADE_RANGE_TAIL.match(text, m.end()):
            return None
        grades.add(_grade_number(m.group(1)))
    if not grades:
        bare = _GRADE_BARE.fullmatch(text)
        if bare:
            grades.add(_grade_number(bare.group(1)))
    return grades.pop() if len(grades) == 1 else None


# ---------------------------------------------------------------- duration

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_NUMBER = r"(\d+(?:\.\d+)?|" + "|".join(NUMBER_WORDS) + r")"
_DURATION = re.compile(rf"(?<![\d.]){_NUMBER}\s*-?\s*(weeks?|wks?|months?|mos?)\b", FLAGS)
_RANGE_BEFORE = re.compile(rf"{_NUMBER}\s*(?:-|–|to)\s*$", FLAGS)


def _to_number(token):
    token = token.lower()
    return NUMBER_WORDS[token] if token in NUMBER_WORDS else float(token)


@_parser
def parse_duration(text):
    """Number plus weeks or months -> Duration. Units are not converted. Ranges or several durations -> unparsed."""
    found = set()
    for m in _DURATION.finditer(text):
        if _RANGE_BEFORE.search(text[:m.start()]):
            return None
        unit = "weeks" if m.group(2).lower().startswith("w") else "months"
        found.add((_to_number(m.group(1)), unit))
    if len(found) != 1:
        return None
    amount, unit = found.pop()
    return Duration(amount=amount, unit=unit)


# ---------------------------------------------------------------- visit count

_VISITS_AFTER = re.compile(r"(?<![\d/.])(\d+)\s*(?:visits?|sessions?)\b", FLAGS)
_VISITS_LABEL = re.compile(r"\b(?:visits?|sessions?)\s*[:=]\s*(\d+)\b", FLAGS)
_OF_BEFORE = re.compile(r"\d+\s+of\s*$", FLAGS)


@_parser
def parse_visit_count(text):
    """Number of visits -> int. Accepts '24', '24 visits', 'visits: 24'. 'N of M' or several counts -> unparsed."""
    if re.fullmatch(r"\s*\d+\s*", text):
        return int(text)
    counts = set()
    for m in _VISITS_AFTER.finditer(text):
        if _OF_BEFORE.search(text[:m.start()]):
            return None
        counts.add(int(m.group(1)))
    for m in _VISITS_LABEL.finditer(text):
        counts.add(int(m.group(1)))
    return counts.pop() if len(counts) == 1 else None


# ---------------------------------------------------------------- smoking

_SMOKING_TOPIC = re.compile(r"smok|tobacco|nicotine|cigarette|vap(?:e|ing)", FLAGS)
_NEGATED_CURRENT = re.compile(r"\b(?:no|denies|denied|without)\s+(?:any\s+)?current(?:ly)?\b(?:\s+\w+){0,3}", FLAGS)
_SMOKING_UNKNOWN = re.compile(r"\b(?:unknown|not\s+documented|undocumented|not\s+recorded)\b", FLAGS)
_SMOKING_NEVER = re.compile(r"\bnon-?\s?smoker\b|\bnever\s+(?:a\s+)?smok|\bnever[- ]smoker\b", FLAGS)
_SMOKING_FORMER = re.compile(
    r"\bformer\b|\bex-?\s?smoker\b|\bquit\b|\bstopped\s+smoking\b|\bhistory\s+of\s+(?:smoking|tobacco)", FLAGS)
_SMOKING_CURRENT = re.compile(
    r"\bcurrent(?:ly)?\s+(?:a\s+)?(?:smok\w*|tobacco|nicotine|cigarette\w*|vap\w*)"
    r"|\bsmokes\b|\bis\s+(?:a\s+)?smoker\b|\bactive(?:ly)?\s+smok", FLAGS)


@_parser
def parse_smoking(text):
    """Smoking status -> 'current', 'former', 'never' or 'unknown'.
    Text that fits none of these, or fits more than one, is unparsed."""
    if not _SMOKING_TOPIC.search(text):
        return None
    cleaned = _NEGATED_CURRENT.sub(" ", text)  # 'no current use' says nothing about being a current smoker
    found = set()
    for status, pattern in (("unknown", _SMOKING_UNKNOWN), ("never", _SMOKING_NEVER),
                            ("former", _SMOKING_FORMER), ("current", _SMOKING_CURRENT)):
        if pattern.search(cleaned):
            found.add(status)
    return found.pop() if len(found) == 1 else None


# ---------------------------------------------------------------- strength

_STRENGTH = re.compile(r"(?<![\d/.])(\d)([+-]?)\s*/\s*5(?![\d/])")


@_parser
def parse_strength(text):
    """Muscle strength graded out of 5 -> the lowest grade stated (0-5). Plus/minus or out-of-range grades -> unparsed."""
    grades = []
    for m in _STRENGTH.finditer(text):
        grade = int(m.group(1))
        if m.group(2) or grade > 5:
            return None
        grades.append(grade)
    return min(grades) if grades else None


# ---------------------------------------------------------------- injections

_INJECTION_NEGATION = re.compile(
    r"^\W*(?:no|none|never|without)\b|\b(?:has|have|had|was|were)\s+(?:not|never)\b", FLAGS)
_INJECTION_COUNT = re.compile(rf"(?<![\d./])\b{_NUMBER}\s+(?:[a-z]+\s+){{0,3}}injections?\b", FLAGS)


@_parser
def parse_injections(text):
    """Injections -> Injections(count, ascending ISO dates). A negation gives count 0.
    Dates give count = number of distinct dates. Otherwise an explicit number gives the count. Anything else is unparsed."""
    found = _find_dates(text)
    if found is None:
        return None
    dates = sorted({d.isoformat() for d in found})
    negated = bool(_INJECTION_NEGATION.search(text))
    if negated:
        return Injections(count=0, dates=[]) if not dates else None
    if dates:
        return Injections(count=len(dates), dates=dates)
    counts = {int(_to_number(m.group(1))) for m in _INJECTION_COUNT.finditer(text)}
    return Injections(count=counts.pop(), dates=[]) if len(counts) == 1 else None


# ---------------------------------------------------------------- facts

PARSERS = {
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


def normalize_extraction(data):
    """{field: NormFact} for every non-null fact in one document's extraction dict."""
    out = {}
    for field, parser in PARSERS.items():
        fact = data.get(field)
        if not isinstance(fact, dict) or fact.get("value") is None:
            continue
        result = parser(fact["value"])
        out[field] = NormFact(
            field=field,
            raw=fact["value"],
            page=fact.get("page"),
            quote=fact.get("quote"),
            status=result.status,
            value=result.value,
        )
    return out


def normalize_file(path):
    """normalize_extraction on an extraction JSON file."""
    with open(path, encoding="utf-8") as f:
        return normalize_extraction(json.load(f))
