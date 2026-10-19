from __future__ import annotations

import uuid


def validate_request_shape(mode: object, count: object, draft_count: int) -> None:
    """Enforce the single/batch invariant before any filesystem mutation."""
    if mode not in {"single", "batch"}:
        raise ValueError("request.mode must be single or batch")
    if not isinstance(count, int) or count < 1:
        raise ValueError("request.count must be a positive integer")
    if mode == "single" and (count != 1 or draft_count != 1):
        raise ValueError("single mode requires count=1 and exactly one draft")
    if mode == "batch" and (count < 2 or draft_count != count):
        raise ValueError("batch mode requires count>=2 and exactly count drafts")


def stable_note_id(request_id: str, index: int) -> str:
    """Return an idempotent ID for one item in a request."""
    return f"embedded-{uuid.uuid5(uuid.NAMESPACE_URL, request_id + ':' + str(index)).hex}"
