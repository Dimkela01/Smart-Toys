"""Uniform error shape: {"detail": {"code": ..., "message": ...}}.

The child client never shows text from an error (NFR-09, UC-22); it plays a local fallback
line and only the code is used for logging.
"""

from __future__ import annotations

from fastapi import HTTPException


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})
