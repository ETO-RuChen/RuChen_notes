from __future__ import annotations

import datetime as dt
import hashlib
import html.parser
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_MAX_BYTES = 2 * 1024 * 1024


def _now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_file_source(path: Path, max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"source file does not exist: {resolved}")
    data = resolved.read_bytes()
    if len(data) > max_bytes:
        raise ValueError(f"source file exceeds {max_bytes} bytes: {resolved}")
    return {
        "type": "file",
        "path": str(resolved),
        "retrieved_at": _now_iso(),
        "sha256": _sha256(data),
        "content": data.decode("utf-8", errors="replace"),
    }


class HtmlTextExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if lowered == "title" and self._ignored_depth == 0:
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "title":
            self._in_title = False
        if lowered in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        value = " ".join(data.split())
        if not value:
            return
        self.text_parts.append(value)
        if self._in_title:
            self.title_parts.append(value)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()

    @property
    def text(self) -> str:
        return "\n".join(self.text_parts).strip()


def extract_html_text(value: str) -> tuple[str, str]:
    parser = HtmlTextExtractor()
    parser.feed(value)
    parser.close()
    return parser.title, parser.text


def read_url_source(url: str, max_bytes: int = DEFAULT_MAX_BYTES, timeout: float = 30.0) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source URL must use http or https")
    request = urllib.request.Request(url, headers={"User-Agent": "embedded-notes/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get_content_type()
        if not (content_type.startswith("text/") or content_type in {"application/xhtml+xml", "application/xml"}):
            raise ValueError(f"source URL returned unsupported content type: {content_type}")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError(f"source URL exceeds {max_bytes} bytes")
        charset = response.headers.get_content_charset() or "utf-8"
        text = data.decode(charset, errors="replace")
        final_url = response.geturl()
    title = ""
    content = text
    if content_type in {"text/html", "application/xhtml+xml"}:
        title, content = extract_html_text(text)
    return {
        "type": "url",
        "url": final_url,
        "title": title,
        "retrieved_at": _now_iso(),
        "sha256": _sha256(data),
        "content": content,
    }
