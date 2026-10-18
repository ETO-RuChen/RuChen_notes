from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from embedded_notes.sources import extract_html_text, read_file_source, read_url_source


class SourceTests(unittest.TestCase):
    def test_file_source_records_content_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dma.txt"
            payload = "DMA transfer complete.\n"
            path.write_text(payload, encoding="utf-8")
            stored = path.read_bytes()

            result = read_file_source(path)

            self.assertEqual(result["type"], "file")
            self.assertEqual(result["content"], stored.decode("utf-8"))
            self.assertEqual(result["sha256"], hashlib.sha256(stored).hexdigest())
            self.assertIn("retrieved_at", result)

    def test_html_source_ignores_script_and_style_text(self) -> None:
        title, content = extract_html_text(
            "<html><head><title>SPI DMA</title><style>secret-style</style></head>"
            "<body><h1>Transfer</h1><script>ignore-command()</script><p>Complete.</p></body></html>"
        )

        self.assertEqual(title, "SPI DMA")
        self.assertIn("Transfer", content)
        self.assertIn("Complete.", content)
        self.assertNotIn("ignore-command", content)
        self.assertNotIn("secret-style", content)

    def test_url_source_rejects_non_http_schemes(self) -> None:
        with self.assertRaises(ValueError):
            read_url_source("file:///etc/passwd")


if __name__ == "__main__":
    unittest.main()
