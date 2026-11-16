"""Shared pure text and timestamp helpers for CloudMove backend modules."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Optional


def utc_now_iso(timespec: Optional[str] = None) -> str:
    """Return current UTC timestamp formatted as an ISO-8601 string."""
    now = datetime.now(timezone.utc)
    return now.isoformat(timespec=timespec) if timespec else now.isoformat()


def slugify(
    value: Any,
    *,
    fallback: str = "app",
    sep: str = "-",
    allow_underscore: bool = False,
) -> str:
    """Normalize arbitrary strings into safe lowercase ASCII slugs."""
    raw = str(value or fallback).strip().lower()
    if allow_underscore:
        cleaned = re.sub(r"[^a-z0-9_\-]+", sep, raw)
        cleaned = re.sub(f"{re.escape(sep)}+", sep, cleaned).strip(sep)
    else:
        cleaned = re.sub(r"[^a-z0-9]+", sep, raw).strip(sep)
    return cleaned or fallback
