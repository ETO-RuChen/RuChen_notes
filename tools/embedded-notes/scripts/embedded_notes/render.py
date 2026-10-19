from __future__ import annotations

import json
import re
import unicodedata
from typing import Any


def yaml_quote(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def safe_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(r"\s+", "-", normalized, flags=re.UNICODE)
    normalized = re.sub(r"[^\w\-\u4e00-\u9fff]+", "-", normalized, flags=re.UNICODE)
    normalized = re.sub(r"-+", "-", normalized).strip("-._")
    return normalized[:96] or "embedded-note"
