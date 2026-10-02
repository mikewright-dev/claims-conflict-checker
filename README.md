# Claim Conflict Checker

Finds contradictions across insurance claim documents using an LLM pipeline, tested against a synthetic case with planted conflicts.

## Status

| Phase | Name | State |
|---|---|---|
| 1 | Ingest | Done |
| 2 | Extract | Done |
| 3 | Normalize | Done |
| 4 | Compare | Done |
| 5 | Adjudicate | Not started |
| 6 | Report and review screen | Not started |

Model in use: Gemini 3.8 Flash (`gemini-3.8-flash`), free tier, called through the Gemini Interactions API. Only Phase 2 calls the model today.

No repeated-run consistency check has been done yet, so this repo makes no accuracy claims.

## Problem

A denied or disputed claim usually comes with several documents: the insurer's letter, the medical policy it cites, imaging and therapy reports, and the treating clinician's notes. Someone has to read all of them and check that the dates, spinal levels, durations, grades and findings agree. The check is slow, and a mismatch is easy to miss when the two statements sit on different pages of different files. Some mismatches matter to the outcome and some are only formatting differences. This project automates the cross-checking and keeps a page citation for every value.

## How it works

1. **Ingest** (plain code): reads each PDF page by page with pdfplumber and keeps the page number.
2. **Extract** (model): for each document, asks the model for ten facts as JSON, each with a value, a page and a verbatim quote. A fact the document does not state is null. The output is validated with Pydantic, and a grounding check confirms each quote appears on its cited page.
3. **Normalize** (plain code): converts each fact to a canonical typed value. Dates become ISO dates, spinal levels become the "L4-L5" form, grades become integers, durations become a number and a unit, and smoking status becomes an enum. A value that cannot be parsed is marked unparsed and its raw text is kept.
4. **Compare** (plain code): groups facts by field across documents. Equal values are agreements. Differing values are one conflict per field, with each distinct value as a side that lists its documents, pages and quotes. Unparsed values and durations in mixed units are listed as uncomparable. It does not say which side is right.
5. **Adjudicate** (model, planned): decide which source to trust, how severe each conflict is, and whether it helps or hurts the appeal.
6. **Report and review screen** (planned): list the conflicts and let the user open the source page for each.

Phases 3 and 4 do no model calls and no network access. Tests check this.

## Test data

All documents are synthetic and fictional, and each page carries a "SYNTHETIC DOCUMENT" footer. The case is in `cases/bevredeau/`:

- Five PDFs: a denial letter, a medical policy, an MRI report, a physical therapy discharge summary and a surgeon consult note.
- Eight planted conflicts (C1 to C8): surgery date, spinal level, PT duration, required conservative care, injections, spondylolisthesis grade, motor strength and smoking status.
- Two decoys (D1, D2) that differ only in format: the MRI date written two ways, and the spinal level written as "L4-5" and "L4-L5". A correct pipeline must not report them.
- `answer_key.json` and `answer_key.md`, which list every planted item with the file, page and text of each location.

The tests read `answer_key.json` at runtime. Pipeline code does not contain answer key values, and a test scans the Phase 3 and Phase 4 code for them.

`outputs/examples/` holds the cached extraction output of one live run (`extraction_run1/`) and the comparison built from it (`comparison_run1.json`), so the offline tests also run on a fresh clone.

## Method

- Test-first: tests for each phase are written and reviewed before the implementation. There is one test file per phase (`tests/test_ingest.py`, `test_extract.py`, `test_normalize.py`, `test_compare.py`).
- Tests that touch the model are mocked offline, and the ingest, normalize and compare tests need no model at all. Live tests are marked `live` and skipped unless `--live` is given.
- Some tests check the tests. The Phase 2 live expectations are written by hand, and offline tests confirm each one maps to exactly one answer key entry and that the check passes on the key's own text.
- Deliberate-break checks were done by hand to show the tests can fail. Each break was made on real code or tests, confirmed to fail with a clear message, then reverted and the suite rerun. They covered a bad selector, a bad check and a deleted expectation (Phase 2 tests), a parser that merged two different values and a level notation that no longer matched (Phase 3), and equal durations, same-side documents counted as a conflict and a skipped field (Phase 4). This is manual, not automated mutation testing.

## Setup and run

Built and tested with Python 3.11.

```
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS or Linux
pip install -r requirements.txt
```

Create a `.env` file in the repo root with your Gemini API key. It is listed in `.gitignore` and must not be committed.

```
GEMINI_API_KEY=your-key-here
```

Run the offline tests (no API calls, no key needed):

```
python -m pytest
```

Run the live tests (real API calls, one per document):

```
python -m pytest tests/test_extract.py --live -k live
```

Live responses are cached in `outputs/extract_cache/`, which is git-ignored, so reruns do not use quota. The cache key includes the model and the prompt, so changing either makes new calls. The free tier can return 503 errors when the model is busy, and the extractor does not retry.

## Known limitations

The full list is in [docs/known_limitations.md](docs/known_limitations.md). In summary:

- **Extraction:** each field holds one fact per document, so the policy's 6-to-3-month revision line and the surgeon note's "denies current nicotine use" are not captured. Null extraction fields are not covered by any test, because the answer key does not say which fields a document leaves unstated. The MRI report's fusion level was not extracted. The live tests accept one cited page per expectation. Quote grounding ignores whitespace and case only. There is no retry logic. The example run is a single run.
- **Normalization:** strength normalizes to the lowest grade stated, which is a heuristic. Numeric dates are read month/day/year. Ambiguous input, such as two different dates or "4+/5", is left unparsed rather than guessed.
- **Comparison:** durations in different units are uncomparable and are not converted. If any document in a field uses a different unit, the whole field is uncomparable. A field found in only one document is reported nowhere.
- **Decoy D2 (L4-5 vs L4-L5):** it was not verified end to end on live model output, because the extractor left the MRI report's fusion level null. It was verified two ways. The level parser maps the key's two D2 strings (read from the answer key at runtime) to the same value. And a comparison test adds a fusion level fact to the MRI report's extraction, built from the key's D2 MRI string, then checks that the MRI report and the surgeon note land on the same side of the fusion level conflict. Decoy D1 (the MRI date) does pass through the live extraction and is reported as an agreement.

## What is next

- Phase 5: adjudication with the model, giving severity and helps or hurts for each conflict, tested against the answer key.
- Phase 6: report and review screen, with each conflict linking to its source page.
- A 5-run consistency check, to measure how stable the model-dependent phases are across repeated runs.

Version 2 ideas:

- PDFs that contain several documents.
- Page-boundary detection.
- Scanned documents with OCR.
- Automated mutation testing.
