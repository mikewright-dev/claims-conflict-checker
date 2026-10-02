# Phase Plan

Model: Gemini 3.8 Flash (free tier)
Case: Bevredeau (5 PDFs, 8 planted conflicts, 2 decoys)

## Phase 1: Ingest
Goal: PDF to text, page by page, with page numbers.
Test: all 5 files, every page, text present and numbered.

## Phase 2: Extract
Goal: key facts per document as JSON, each with a page citation.
Test: dates, level, grade, strength, smoking status, PT duration match the answer key.

## Phase 3: Normalize
Goal: standardize dates and level notation.
Test: D1 and D2 come out identical.

## Phase 4: Compare
Goal: flag cross-document disagreements.
Test: finds C1-C8, flags neither decoy.

## Phase 5: Adjudicate
Goal: severity and helps/hurts per conflict.
Test: matches the answer key.

## Phase 6: Report and review screen
Goal: conflicts listed, click to see source page.
Test: every conflict links to its source page.