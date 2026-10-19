# DocuMind -- single lightweight container serving both the FastAPI
# backend (API + PDF processing) and the static frontend.
#
# No embedding model or vector DB here (see the concept note's
# Architecture Note), so this image stays small and avoids the
# memory-pressure issues that heavier RAG stacks can hit on AWS
# App Runner's free tier.

FROM python:3.12-slim

WORKDIR /app

# Install backend dependencies first, so Docker can cache this layer
# and only re-run pip install when requirements.txt actually changes
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Now copy the rest of the application code
COPY backend ./backend
COPY frontend ./frontend

# AWS App Runner (and most PaaS platforms) expect the app to listen on
# the port given via the PORT environment variable -- default to 8080
ENV PORT=8080
EXPOSE 8080

# Run with a shell so ${PORT} is expanded correctly at container start
CMD uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT}
