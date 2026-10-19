#!/usr/bin/env python3
"""Install this Skill into a Codex home directory on Windows or Linux."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


SKILL_NAME = "embedded-notes"
SOURCE = Path(__file__).resolve().parents[1]


def default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def install(codex_home: Path, update: bool = False) -> dict[str, str | bool]:
    codex_home = codex_home.expanduser().resolve()
    destination = codex_home / "skills" / SKILL_NAME
    backup: Path | None = None
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}.install-", dir=destination.parent))
    staged = staging_root / SKILL_NAME
    try:
        shutil.copytree(
            SOURCE,
            staged,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
        if destination.exists():
            if not update:
                raise RuntimeError(f"Skill already exists: {destination}; rerun with --update")
            stamp = dt.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
            backup = destination.with_name(f".{SKILL_NAME}.backup-{stamp}")
            if backup.exists():
                raise RuntimeError(f"backup destination already exists: {backup}")
            shutil.copytree(destination, backup)
            shutil.rmtree(destination)
        shutil.move(str(staged), str(destination))
    except Exception:
        if backup is not None and not destination.exists():
            shutil.copytree(backup, destination)
        raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    if not (destination / "SKILL.md").is_file():
        raise RuntimeError(f"installation did not create {destination / 'SKILL.md'}")
    return {
        "installed": True,
        "source": str(SOURCE),
        "destination": str(destination),
        "backup": str(backup) if backup else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="install-embedded-notes")
    parser.add_argument("--codex-home", default=str(default_codex_home()))
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    try:
        result = install(Path(args.codex_home), update=args.update)
    except (OSError, RuntimeError) as exc:
        print(f"install-embedded-notes: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
