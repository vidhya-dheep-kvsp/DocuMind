"""
Standalone streaming diagnostic -- run this directly, completely outside
FastAPI/Uvicorn, to check whether Gemini itself delivers chunks with real
time gaps between them, or whether they arrive all at once regardless of
our server.

Usage:
    cd backend
    python test_stream.py

(Needs your .env file already set up with GEMINI_API_KEY, same as the
main app.)
"""

import os
import time

from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

print("Requesting a long response... watch the timestamps below.\n")

start = time.time()
stream = client.models.generate_content_stream(
    model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
    contents=[{"role": "user", "parts": [{"text": "Write a detailed, 1500-word essay about the history of the internet, covering multiple decades in depth."}]}],
    config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="low"),
    ),
)

chunk_count = 0
for chunk in stream:
    if chunk.text:
        chunk_count += 1
        elapsed = time.time() - start
        print(f"[{elapsed:6.2f}s] chunk #{chunk_count} ({len(chunk.text)} chars): {chunk.text[:60]!r}")

print(f"\nDone. Received {chunk_count} chunks over {time.time() - start:.2f} seconds.")
print("If the timestamps above are all clustered within a fraction of a")
print("second of each other, Gemini itself sent it as one burst. If they're")
print("spread out over several seconds, Gemini is streaming correctly and")
print("the issue is somewhere between our server and your browser.")
