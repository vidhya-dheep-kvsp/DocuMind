"""
DocuMind backend -- FastAPI application.

Two endpoints:
  POST /api/upload  -- accepts a PDF, extracts + validates it, returns a session_id
  POST /api/chat     -- accepts {session_id, question}, streams a grounded answer

Also serves the frontend as static files, so the whole app runs as a single
process/container (see README for the reasoning: simpler local testing,
simpler deployment, no CORS complications).
"""

import os
import tempfile

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from .llm_client import get_client, stream_answer
from .pdf_processor import DocumentTooLargeError, extract_pdf_text
from .session_store import append_turn, create_session, get_session

app = FastAPI(title="DocuMind API")

# Permissive CORS is fine here since the frontend is served by this same
# app in production; this mainly helps if you run the frontend separately
# during local development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB -- mirrors the frontend's file-size check


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail={"message": "Only PDF files are supported."})

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "message": (
                    f"File is too large ({len(contents) / (1024 * 1024):.1f}MB). "
                    f"Max size is {MAX_UPLOAD_BYTES // (1024 * 1024)}MB."
                )
            },
        )

    # pdfplumber needs a file path, so write to a temp file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        doc = extract_pdf_text(tmp_path, file.filename)
    except DocumentTooLargeError as e:
        raise HTTPException(status_code=413, detail=e.detail)
    finally:
        os.unlink(tmp_path)

    session = create_session(
        filename=doc.filename,
        document_text=doc.text,
        page_count=doc.page_count,
        estimated_tokens=doc.estimated_tokens,
    )

    return {
        "session_id": session.session_id,
        "filename": doc.filename,
        "page_count": doc.page_count,
        "estimated_tokens": doc.estimated_tokens,
    }


class ChatRequest(BaseModel):
    session_id: str
    question: str


@app.post("/api/chat")
async def chat(request: ChatRequest):
    session = get_session(request.session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={"message": "Session not found. Please upload the document again."},
        )

    # Fail fast, before the stream starts: once StreamingResponse begins,
    # the HTTP status is already committed, so a missing/invalid key
    # discovered mid-stream can't be turned into a clean JSON error
    # anymore -- it would just look like a stalled or dropped connection
    # to the frontend. Checking here means the user gets the same clear
    # error message the frontend already knows how to display.
    try:
        get_client()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail={"message": str(e)})

    async def event_generator():
        full_answer = ""
        try:
            async for chunk in stream_answer(
                document_text=session.document_text,
                filename=session.filename,
                conversation_history=session.history,
                user_question=request.question,
            ):
                full_answer += chunk
                yield chunk
        except Exception as e:
            # The HTTP status is already sent by this point, so we can't
            # return a proper error response -- the best we can do is
            # surface a readable message inside the stream itself (e.g.
            # for a rate limit or network error that happens partway
            # through generation).
            error_note = f"\n\n[Error: the response was interrupted -- {e}]"
            full_answer += error_note
            yield error_note
        finally:
            # Save the turn even if the stream is interrupted partway
            append_turn(session.session_id, "user", request.question)
            if full_answer:
                append_turn(session.session_id, "assistant", full_answer)

    return StreamingResponse(
        event_generator(),
        media_type="text/plain",
        headers={
            # These headers matter once deployed to AWS: without them, the
            # proxy/load balancer in front of App Runner can buffer the
            # whole response instead of flushing it chunk by chunk, which
            # silently breaks the "progressive streaming" requirement even
            # though it works fine on localhost.
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Serve the frontend (must be registered after the API routes above)
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
