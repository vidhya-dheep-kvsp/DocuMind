"""
In-memory session storage for DocuMind.

Deliberately simple for this project's scope: each uploaded document gets a
session_id, and its extracted text + conversation history live in a plain
dict in server memory. This is a known, documented limitation -- restarting
the server clears all sessions -- and is called out explicitly in the
project report rather than hidden. Swapping this for Redis or a database
would be a natural next step if this became a real multi-user product.
"""

import uuid
from dataclasses import dataclass, field


@dataclass
class Session:
    session_id: str
    filename: str
    document_text: str
    page_count: int
    estimated_tokens: int
    history: list[dict] = field(default_factory=list)


_sessions: dict[str, Session] = {}


def create_session(filename: str, document_text: str, page_count: int, estimated_tokens: int) -> Session:
    session_id = str(uuid.uuid4())
    session = Session(
        session_id=session_id,
        filename=filename,
        document_text=document_text,
        page_count=page_count,
        estimated_tokens=estimated_tokens,
    )
    _sessions[session_id] = session
    return session


def get_session(session_id: str) -> Session | None:
    return _sessions.get(session_id)


def append_turn(session_id: str, role: str, content: str) -> None:
    session = _sessions.get(session_id)
    if session:
        session.history.append({"role": role, "content": content})
