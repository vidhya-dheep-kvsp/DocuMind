"""
PDF extraction and limit-checking for DocuMind.

Design notes (also covered in the project report):
- We use pdfplumber rather than PyPDF2 because it handles multi-column
  academic layouts far more reliably.
- We enforce limits in two layers: page count (cheap, instant) and an
  estimated token count (more accurate, checked after extraction) before
  any text is sent to the LLM. This protects against exceeding the
  model's context window and keeps API calls predictable.
- Token counting here uses a lightweight character-based estimate
  (~4 characters per token), which avoids adding a heavy tokenizer
  dependency. It is deliberately conservative (see TOKEN_CHARS_PER
  below) so the estimate errs on the side of rejecting borderline
  documents rather than letting an oversized one through.
"""

from dataclasses import dataclass

import pdfplumber

# ---- Configurable limits -----------------------------------------------
MAX_PAGES = 25
MAX_ESTIMATED_TOKENS = 40_000  # leaves headroom for the prompt template,
                                # the user's question, and the model's answer
                                # within a long-context model's window

# Conservative estimate: real English text averages ~4 chars/token, but we
# use 3.5 to stay safely under real limits rather than risk going over.
TOKEN_CHARS_PER = 3.5


class DocumentTooLargeError(Exception):
    """Raised when an uploaded PDF exceeds the configured page or token limit."""

    def __init__(self, message: str, detail: dict):
        super().__init__(message)
        self.detail = detail


@dataclass
class ExtractedDocument:
    filename: str
    page_count: int
    text: str
    estimated_tokens: int


def estimate_tokens(text: str) -> int:
    """Cheap, dependency-free token estimate based on character count."""
    return int(len(text) / TOKEN_CHARS_PER)


def extract_pdf_text(file_path: str, filename: str) -> ExtractedDocument:
    """
    Extract text from a PDF, enforcing page and token limits.

    Raises DocumentTooLargeError if either limit is exceeded, with enough
    detail in `.detail` for the API layer to return a clear, specific
    message to the frontend (see main.py).
    """
    with pdfplumber.open(file_path) as pdf:
        page_count = len(pdf.pages)

        # --- Layer 1: page count check (cheap, before we do any real work) ---
        if page_count > MAX_PAGES:
            raise DocumentTooLargeError(
                "Page limit exceeded",
                {
                    "reason": "page_limit",
                    "page_count": page_count,
                    "max_pages": MAX_PAGES,
                    "message": (
                        f"This PDF has {page_count} pages. The limit is "
                        f"{MAX_PAGES} pages. Try uploading a shorter document "
                        f"or a specific section."
                    ),
                },
            )

        # --- Extract text page by page ---
        chunks = []
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            chunks.append(page_text)
        full_text = "\n".join(chunks).strip()

    if not full_text:
        raise DocumentTooLargeError(
            "No extractable text",
            {
                "reason": "empty_text",
                "message": (
                    "No readable text could be extracted from this PDF. "
                    "It may be a scanned image without a text layer."
                ),
            },
        )

    # --- Layer 2: token count check (accurate, after extraction) ---
    estimated_tokens = estimate_tokens(full_text)
    if estimated_tokens > MAX_ESTIMATED_TOKENS:
        raise DocumentTooLargeError(
            "Token limit exceeded",
            {
                "reason": "token_limit",
                "estimated_tokens": estimated_tokens,
                "max_tokens": MAX_ESTIMATED_TOKENS,
                "message": (
                    f"This document is too long to process (~{estimated_tokens:,} "
                    f"estimated tokens, limit is {MAX_ESTIMATED_TOKENS:,}). "
                    f"Try a shorter document or a specific section."
                ),
            },
        )

    return ExtractedDocument(
        filename=filename,
        page_count=page_count,
        text=full_text,
        estimated_tokens=estimated_tokens,
    )
