from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install_skill.py"
SPEC = importlib.util.spec_from_file_location("install_skill", SCRIPT)
assert SPEC and SPEC.loader
install_skill = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(install_skill)


class InstallSkillTests(unittest.TestCase):
    def test_install_and_update_preserve_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / ".codex"

            first = install_skill.install(codex_home)
            destination = Path(first["destination"])
            self.assertTrue((destination / "SKILL.md").is_file())
            marker = destination / "local-marker.txt"
            marker.write_text("old installation", encoding="utf-8")

            second = install_skill.install(codex_home, update=True)
            backup = Path(second["backup"])
            self.assertTrue((backup / "local-marker.txt").is_file())
            self.assertFalse(marker.exists())
            self.assertTrue((destination / "scripts" / "notesctl.py").is_file())


if __name__ == "__main__":
    unittest.main()
