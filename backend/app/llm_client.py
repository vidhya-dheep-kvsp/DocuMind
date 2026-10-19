"""
Thin wrapper around the Gemini API for DocuMind.

Uses the google-genai SDK. The API key is read from the GEMINI_API_KEY
environment variable (never hardcoded, never sent to the frontend) --
see .env.example.
"""

import os
from collections.abc import AsyncIterator

from google import genai
from google.genai import types

from .prompts import SYSTEM_PROMPT

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")


def get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return genai.Client(api_key=api_key)


def _history_to_gemini_contents(conversation_history: list[dict]) -> list[dict]:
    """Convert our {"role": "user"|"assistant", "content": str} history into
    the Gemini SDK's expected contents format (role "model" instead of "assistant")."""
    contents = []
    for turn in conversation_history:
        role = "model" if turn["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": turn["content"]}]})
    return contents


async def stream_answer(
    document_text: str,
    filename: str,
    conversation_history: list[dict],
    user_question: str,
) -> AsyncIterator[str]:
    """
    Stream a grounded answer from Gemini, yielding text chunks as they arrive.

    Uses the async client (client.aio) with an async generator, rather than
    a sync generator run in FastAPI's threadpool. This is the pattern Google
    and FastAPI both document for streaming responses -- it avoids any
    ambiguity around thread-pool scheduling delaying when chunks actually
    reach the HTTP response.

    The full document text is re-sent as the system instruction on every
    call (see prompts.py for the reasoning behind this long-context
    approach). conversation_history carries prior turns so follow-up
    questions stay coherent within the session.
    """
    client = get_client()

    system_instruction = SYSTEM_PROMPT.format(filename=filename, document_text=document_text)

    contents = _history_to_gemini_contents(conversation_history)
    contents.append({"role": "user", "parts": [{"text": user_question}]})

    stream = await client.aio.models.generate_content_stream(
        model=MODEL_NAME,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            # Gemini 3.x models do an internal "thinking" pass before writing
            # the visible answer, which is invisible to this app (we only
            # capture chunk.text) -- at higher thinking levels this can
            # cause a long pause before anything streams, followed by the
            # answer arriving in one fast burst rather than trickling in.
            # A grounded Q&A task like this doesn't need heavy reasoning, so
            # we lower it to reduce that invisible pause. (temperature/top_p/
            # top_k are intentionally omitted -- Google no longer recommends
            # setting them for Gemini 3.x models.)
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        ),
    )

    async for chunk in stream:
        if chunk.text:
            yield chunk.text
