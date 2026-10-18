"""Pulse Decision OS package."""

from __future__ import annotations

__all__ = ["init_db", "session_scope"]


def __getattr__(name: str):
    if name in ("init_db", "session_scope"):
        from backend.decision.db import init_db, session_scope

        return init_db if name == "init_db" else session_scope
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
