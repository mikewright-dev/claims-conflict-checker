import hashlib
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, model_validator

MODEL = "gemini-3.8-flash"

FIELD_HELP = {
    "surgery_date": "date the surgery is planned, scheduled, or reviewed for",
    "fusion_level": "spinal level(s) of the fusion or procedure",
    "pt_duration": "how long physical therapy lasted or is documented",
    "pt_visit_count": "number of physical therapy visits",
    "conservative_care_required": "length of conservative care that a policy or criteria requires",
    "injections": "injections or interventional pain management: whether they were done, and when",
    "spondylolisthesis_grade": "grade of spondylolisthesis or listhesis",
    "motor_strength": "lower-extremity motor strength findings",
    "smoking_status": "smoking or nicotine use status",
    "mri_date": "date of the MRI exam",
}


class Fact(BaseModel):
    value: Optional[str] = None
    page: Optional[int] = None
    quote: Optional[str] = None

    @model_validator(mode="after")
    def value_needs_page(self):
        if self.value is not None and self.page is None:
            raise ValueError("a non-null value must cite a page")
        return self


class DocExtraction(BaseModel):
    surgery_date: Fact = Field(default_factory=Fact)
    fusion_level: Fact = Field(default_factory=Fact)
    pt_duration: Fact = Field(default_factory=Fact)
    pt_visit_count: Fact = Field(default_factory=Fact)
    conservative_care_required: Fact = Field(default_factory=Fact)
    injections: Fact = Field(default_factory=Fact)
    spondylolisthesis_grade: Fact = Field(default_factory=Fact)
    motor_strength: Fact = Field(default_factory=Fact)
    smoking_status: Fact = Field(default_factory=Fact)
    mri_date: Fact = Field(default_factory=Fact)


FIELDS = tuple(DocExtraction.model_fields)


def _inline_refs(node, defs):
    """Inline $ref/$defs and drop 'default' so the schema is plain, self-contained JSON Schema."""
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline_refs(defs[node["$ref"].split("/")[-1]], defs)
        return {k: _inline_refs(v, defs) for k, v in node.items() if k not in ("$defs", "default")}
    if isinstance(node, list):
        return [_inline_refs(v, defs) for v in node]
    return node


def response_schema():
    schema = DocExtraction.model_json_schema()
    return _inline_refs(schema, schema.get("$defs", {}))


def build_prompt(pages):
    field_lines = "\n".join(f"- {name}: {FIELD_HELP[name]}" for name in FIELDS)
    page_blocks = "\n\n".join(f"[Page {p['page']}]\n{p['text']}" for p in pages)
    return (
        "Extract the facts listed below from the document pages that follow.\n\n"
        "Return one JSON object with exactly these fields, each an object with "
        "\"value\", \"page\" and \"quote\":\n"
        f"{field_lines}\n\n"
        "Rules:\n"
        "- value: the fact as the document states it, copied in the document's own wording and format.\n"
        "- page: the page number (the number in the [Page N] label) where the fact is stated.\n"
        "- quote: a short verbatim excerpt from that page that contains the fact, copied exactly.\n"
        "- If the document does not state a fact, set value, page and quote to null. "
        "Never guess, infer, or fill in a fact from outside the document.\n"
        "- Use only the text below.\n\n"
        f"Document:\n\n{page_blocks}\n"
    )


def _norm(text):
    return re.sub(r"\s+", " ", text).strip().casefold()


def check_grounding(extraction, pages):
    """Return a list of problems; empty means every non-null fact's quote is on its cited page."""
    by_page = {p["page"]: p["text"] for p in pages}
    problems = []
    for name in FIELDS:
        f = getattr(extraction, name)
        if f.value is None:
            continue
        if f.page not in by_page:
            problems.append(f"{name}: cited page {f.page} does not exist")
        elif not f.quote:
            problems.append(f"{name}: no quote given")
        elif _norm(f.quote) not in _norm(by_page[f.page]):
            problems.append(f"{name}: quote {f.quote!r} not found on page {f.page}")
    return problems


def _cache_path(cache_dir, pages, prompt):
    stem = Path(pages[0]["file"]).stem
    digest = hashlib.sha256((MODEL + prompt).encode("utf-8")).hexdigest()[:8]
    return Path(cache_dir) / f"{stem}.{digest}.json"


def extract_document(pages, client, cache_dir=None):
    """Extract one DocExtraction from a document's page dicts (one model call, or the cached response)."""
    prompt = build_prompt(pages)
    cache = _cache_path(cache_dir, pages, prompt) if cache_dir else None
    if cache is not None and cache.exists():
        return DocExtraction.model_validate_json(cache.read_text(encoding="utf-8"))

    interaction = client.interactions.create(
        model=MODEL,
        input=prompt,
        response_format={"type": "text", "mime_type": "application/json", "schema": response_schema()},
    )
    raw = interaction.output_text
    doc = DocExtraction.model_validate_json(raw)  # raises before anything is cached
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(raw, encoding="utf-8")
    return doc


def extract_case(case, client, cache_dir=None):
    """Return {file name: DocExtraction} for a case from ingest_case()."""
    return {name: extract_document(pages, client, cache_dir) for name, pages in case.items()}
