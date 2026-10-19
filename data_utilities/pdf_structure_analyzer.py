"""
Standalone utility: analyzes the structural composition of a PDF's
extracted text before it reaches the LLM pipeline.

Useful for judging extraction quality on a new document type
(page count, token estimate, LaTeX density, section structure)
without starting the full application.
"""

import re
import sys

import pdfplumber


def analyze_pdf_structure(path: str) -> dict:
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

    word_count = len(full_text.split())
    char_count = len(full_text)

    latex_segments = len(re.findall(r"\$[^\$\n]+?\$", full_text))
    section_headers = len(re.findall(r"^\d+\.\s+[A-Z]", full_text, re.MULTILINE))
    estimated_tokens = int(char_count / 3.5)  # same estimator as pdf_processor.py

    return {
        "page_count": page_count,
        "word_count": word_count,
        "char_count": char_count,
        "estimated_tokens": estimated_tokens,
        "detected_latex_segments": latex_segments,
        "detected_section_headers": section_headers,
        "within_documind_limits": page_count <= 25 and estimated_tokens <= 40_000,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python pdf_structure_analyzer.py <path_to_pdf>")
        sys.exit(1)

    for key, value in analyze_pdf_structure(sys.argv[1]).items():
        print(f"{key}: {value}")