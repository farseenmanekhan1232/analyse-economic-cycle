"""Pulse Decision OS API entry — same as backend.api.server.

Run from repo root:
  uvicorn backend.api.server:app --reload --host 127.0.0.1 --port 8000
"""

from backend.api.server import app

__all__ = ["app"]
