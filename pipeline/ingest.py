from pathlib import Path

import pdfplumber


def ingest_pdf(path):
    """Return one dict per page: file name, 1-based page number, extracted text."""
    pages = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            pages.append({
                "file": Path(path).name,
                "page": i,
                "text": page.extract_text() or "",
            })
    return pages


def ingest_case(case_dir):
    """Return {file name: [page dicts]} for every PDF in the case folder."""
    return {p.name: ingest_pdf(p) for p in sorted(Path(case_dir).glob("*.pdf"))}