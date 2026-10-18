#!/usr/bin/env python3
"""Deterministic storage and deployment operations for the embedded-notes Skill."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, NoReturn

from embedded_notes.render import safe_slug, yaml_quote
from embedded_notes.request import stable_note_id, validate_request_shape
from embedded_notes.sources import DEFAULT_MAX_BYTES, read_file_source, read_url_source

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover - only for unsupported Python
    raise SystemExit("embedded-notes requires Python 3.11 or newer") from exc


class NotesError(RuntimeError):
    pass


DEFAULT_CONFIG = '''[site]
content_dir = "content/embedded/embedded-study"
front_matter = "yaml"
filename_style = "date-slug"
default_draft = false
default_tags = ["嵌入式", "EmbeddedStudy"]
default_categories = ["嵌入式"]
default_series = ["EmbeddedStudy"]
default_featureimage = ""
default_summary = ""
include_lastmod = true

[git]
remote = "origin"
branch = "main"
require_remote = true
cloud_wins_on_divergence = true
repository_is_dedicated = false
auto_commit = true
auto_push = true

[hugo]
enabled = true
command = ["hugo", "--gc", "--minify"]

[publish]
enabled = false
command = []

[generator]
command = ["codex", "exec", "--ephemeral", "--color", "never", "--sandbox", "workspace-write", "--approve-for-me", "--cd", "{site_root}", "{prompt}"]
'''

WINDOWS_TIMEZONES = {
    "UTC": "UTC",
    "Etc/UTC": "UTC",
    "Asia/Shanghai": "China Standard Time",
    "America/New_York": "Eastern Standard Time",
    "America/Chicago": "Central Standard Time",
    "America/Denver": "Mountain Standard Time",
    "America/Los_Angeles": "Pacific Standard Time",
    "Europe/London": "GMT Standard Time",
    "Europe/Berlin": "W. Europe Standard Time",
}

SOURCE_METADATA_FIELDS = (
    "type",
    "description",
    "path",
    "url",
    "title",
    "retrieved_at",
    "sha256",
    "note_id",
)


def fail(message: str) -> NoReturn:
    raise NotesError(message)


def now_stamp() -> str:
    return dt.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def date_prefix(value: object) -> str:
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[T ])", value):
        fail("draft.date must start with a valid YYYY-MM-DD date")
    prefix = value[:10]
    try:
        dt.date.fromisoformat(prefix)
    except ValueError:
        fail("draft.date must start with a valid YYYY-MM-DD date")
    return prefix


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def run_command(
    command: list[str],
    cwd: Path,
    *,
    check: bool = True,
    capture: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            capture_output=capture,
            env=env,
            check=False,
        )
    except OSError as exc:
        fail(f"cannot execute {command[0]!r}: {exc}")
    if check and result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        fail(f"command failed ({result.returncode}): {' '.join(command)}\n{details}")
    return result


def git(site_root: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_command(["git", *args], site_root, check=check)


def git_text(site_root: Path, args: list[str], *, check: bool = True) -> str:
    return (git(site_root, args, check=check).stdout or "").strip()


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path: Path, value: Any) -> None:
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def load_config(site_root: Path) -> dict[str, Any]:
    path = site_root / ".embedded-notes" / "config.toml"
    if not path.is_file():
        fail(f"missing configuration: {path}; run notesctl init first")
    try:
        with path.open("rb") as stream:
            config = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        fail(f"invalid configuration {path}: {exc}")
    if not isinstance(config, dict):
        fail(f"invalid configuration: {path}")
    return config


def section(config: dict[str, Any], name: str) -> dict[str, Any]:
    value = config.get(name, {})
    if not isinstance(value, dict):
        fail(f"configuration section [{name}] must be a table")
    return value


def resolve_site_root(value: str | None) -> Path:
    candidate = value or os.environ.get("EMBEDDED_NOTES_SITE_ROOT")
    if candidate:
        return Path(candidate).expanduser().resolve()
    current = Path.cwd().resolve()
    for directory in (current, *current.parents):
        if (directory / ".embedded-notes" / "config.toml").is_file():
            return directory
    fail("Hugo site not found; pass --site-root or set EMBEDDED_NOTES_SITE_ROOT")


def site_paths(site_root: Path, config: dict[str, Any]) -> dict[str, Path]:
    site = section(config, "site")
    content_value = site.get("content_dir", "content/embedded")
    if not isinstance(content_value, str) or not content_value:
        fail("site.content_dir must be a non-empty relative path")
    root = site_root.resolve()
    content = (root / content_value).resolve()
    try:
        content.relative_to(root)
    except ValueError:
        fail("site.content_dir must stay below the Hugo site root")
    state = root / ".embedded-notes"
    return {
        "state": state,
        "config": state / "config.toml",
        "manifest": state / "manifest.json",
        "plans": state / "plans",
        "locks": state / "locks",
        "transactions": state / "transactions",
        "backups": state / "backups",
        "content": content,
    }


def init_site(args: argparse.Namespace) -> dict[str, Any]:
    site_root = Path(args.site_root).expanduser().resolve()
    site_root.mkdir(parents=True, exist_ok=True)
    state = site_root / ".embedded-notes"
    config_path = state / "config.toml"
    state.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        fail(f"configuration already exists: {config_path}")
    config = DEFAULT_CONFIG
    if args.content_dir:
        config = re.sub(r'(?m)^content_dir = ".*"$', f'content_dir = {json.dumps(args.content_dir)}', config, count=1)
    if args.remote:
        config = config.replace('remote = "origin"', f'remote = {json.dumps(args.remote)}')
    if args.branch:
        config = config.replace('branch = "main"', f'branch = {json.dumps(args.branch)}')
    atomic_write(config_path, config.encode("utf-8"))
    for directory in (state / "plans", state / "transactions", state / "backups", state / "locks"):
        directory.mkdir(parents=True, exist_ok=True)
    atomic_json(state / "manifest.json", {"version": 1, "notes": {}, "requests": {}})
    atomic_write(state / ".gitignore", b"/locks/\n/transactions/\n/backups/\n/scheduler/\n")
    config_data = load_config(site_root)
    paths = site_paths(site_root, config_data)
    paths["content"].mkdir(parents=True, exist_ok=True)
    return {"site_root": str(site_root), "config": str(config_path), "content": str(paths["content"])}


class RepoLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.acquired = False

    def __enter__(self) -> "RepoLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps({"pid": os.getpid(), "created_at": now_iso()}))
        except FileExistsError:
            fail(f"another notesctl operation holds the lock: {self.path}")
        self.acquired = True
        return self

    def __exit__(self, *_: Any) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def git_root(site_root: Path) -> None:
    result = git(site_root, ["rev-parse", "--show-toplevel"], check=False)
    if result.returncode != 0:
        fail(f"not a Git repository: {site_root}")


def relative_git_path(site_root: Path, path: Path) -> str:
    return os.path.relpath(path, site_root).replace(os.sep, "/")


def managed_paths(site_root: Path, paths: dict[str, Path]) -> tuple[str, str, str]:
    content = relative_git_path(site_root, paths["content"])
    state = relative_git_path(site_root, paths["state"])
    config = relative_git_path(site_root, paths["config"])
    return content.rstrip("/") + "/", state.rstrip("/") + "/", config


def status_paths(site_root: Path) -> list[str]:
    result = git(
        site_root,
        ["-c", "core.quotePath=false", "status", "--porcelain=v1", "--untracked-files=all"],
    )
    output = result.stdout or ""
    values: list[str] = []
    for line in output.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        values.append(path.replace("\\", "/"))
    return values


def is_managed(path: str, managed_content: str, managed_state: str, managed_config: str) -> bool:
    return path.startswith(managed_content) or path.startswith(managed_state) or path == managed_config


def backup_state(site_root: Path, paths: dict[str, Path], reason: str) -> Path:
    target = paths["backups"] / f"{now_stamp()}-{reason}"
    target.mkdir(parents=True, exist_ok=False)
    diff = git(site_root, ["diff"], check=False).stdout or ""
    cached = git(site_root, ["diff", "--cached"], check=False).stdout or ""
    atomic_write(target / "working-tree.patch", diff.encode("utf-8"))
    atomic_write(target / "index.patch", cached.encode("utf-8"))
    if paths["content"].is_dir():
        shutil.copytree(paths["content"], target / "content", dirs_exist_ok=True)
    state_target = target / "state"
    for child in paths["state"].iterdir():
        if child.name in {"backups", "locks"}:
            continue
        destination = state_target / child.name
        if child.is_dir():
            shutil.copytree(child, destination, dirs_exist_ok=True)
        elif child.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, destination)
    atomic_json(target / "backup.json", {"created_at": now_iso(), "reason": reason, "site_root": str(site_root)})
    return target


def git_ref(site_root: Path, ref: str) -> str | None:
    result = git(site_root, ["rev-parse", "--verify", ref], check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def ancestor(site_root: Path, older: str, newer: str) -> bool:
    return git(site_root, ["merge-base", "--is-ancestor", older, newer], check=False).returncode == 0


def discard_managed_worktree_changes(site_root: Path, paths: dict[str, Path]) -> None:
    managed_content, managed_state, managed_config = managed_paths(site_root, paths)
    tracked_output = git_text(site_root, ["ls-files", "-z"])
    tracked = [item for item in tracked_output.split("\x00") if item]
    restore = [
        item for item in tracked
        if is_managed(item, managed_content, managed_state, managed_config)
    ]
    if restore:
        git(site_root, ["restore", "--source=HEAD", "--staged", "--worktree", "--", *restore])
    for relative in status_paths(site_root):
        if not is_managed(relative, managed_content, managed_state, managed_config):
            continue
        absolute = (site_root / relative).resolve()
        if any(
            absolute == protected or protected in absolute.parents
            for protected in (paths["backups"].resolve(), paths["locks"].resolve(), paths["transactions"].resolve())
        ):
            continue
        if absolute.is_file() and git(site_root, ["ls-files", "--error-unmatch", relative], check=False).returncode != 0:
            absolute.unlink()


def sync_repo(site_root: Path, config: dict[str, Any], *, fetch: bool = True) -> dict[str, Any]:
    git_root(site_root)
    paths = site_paths(site_root, config)
    git_config = section(config, "git")
    remote_name = str(git_config.get("remote", "origin"))
    branch = str(git_config.get("branch", "main"))
    remote_url = git(site_root, ["remote", "get-url", remote_name], check=False)
    if remote_url.returncode != 0:
        if bool(git_config.get("require_remote", True)):
            fail(f"configured Git remote is unavailable: {remote_name}")
        return {"status": "no-remote", "local": git_ref(site_root, "HEAD"), "remote": None}
    remote_ref = f"refs/remotes/{remote_name}/{branch}"
    if fetch:
        git(site_root, ["fetch", "--prune", remote_name])
    local = git_ref(site_root, "HEAD")
    remote = git_ref(site_root, remote_ref)
    if not remote:
        return {"status": "no-remote-ref", "local": local, "remote": None}
    if not local:
        return {"status": "no-local-commit", "local": None, "remote": remote}
    if local == remote:
        return {"status": "equal", "local": local, "remote": remote}

    current_status = status_paths(site_root)
    managed_content, managed_state, managed_config = managed_paths(site_root, paths)
    outside = [p for p in current_status if not is_managed(p, managed_content, managed_state, managed_config)]
    remote_ahead = ancestor(site_root, local, remote)
    local_ahead = ancestor(site_root, remote, local)
    if remote_ahead and not local_ahead:
        backup = None
        managed_changes = [
            path for path in current_status
            if is_managed(path, managed_content, managed_state, managed_config)
        ]
        if managed_changes:
            backup = str(backup_state(site_root, paths, "remote-ahead"))
            discard_managed_worktree_changes(site_root, paths)
        # A fast-forward can preserve dirty files outside the managed note paths
        # when the incoming commits do not touch them. Git aborts before changing
        # HEAD if one of those local edits would be overwritten.
        git(site_root, ["merge", "--ff-only", remote])
        return {"status": "fast-forwarded", "local": local, "remote": remote, "backup": backup}
    if local_ahead and not remote_ahead:
        return {"status": "local-ahead", "local": local, "remote": remote}

    if not bool(git_config.get("cloud_wins_on_divergence", True)):
        fail("local and cloud histories diverged and cloud_wins_on_divergence is disabled")
    if outside:
        fail("local and cloud histories diverged; unrelated local changes exist: " + ", ".join(outside))
    backup = str(backup_state(site_root, paths, "diverged"))
    if not bool(git_config.get("repository_is_dedicated", False)):
        fail(
            "local and cloud histories diverged; backup created at "
            f"{backup}, but repository_is_dedicated is false so no reset was performed"
        )
    git(site_root, ["reset", "--hard", remote])
    return {"status": "cloud-reset", "local": local, "remote": remote, "backup": backup}


def load_manifest(paths: dict[str, Path]) -> dict[str, Any]:
    if not paths["manifest"].exists():
        return {"version": 1, "notes": {}, "requests": {}}
    try:
        value = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid manifest {paths['manifest']}: {exc}")
    if not isinstance(value, dict):
        fail("manifest must be a JSON object")
    value.setdefault("version", 1)
    value.setdefault("notes", {})
    value.setdefault("requests", {})
    return value


def transaction_path(paths: dict[str, Path], request_id: str) -> Path:
    key = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return paths["transactions"] / f"{key}.json"


def write_transaction(path: Path, transaction: dict[str, Any]) -> None:
    atomic_json(path, transaction)


def load_transaction(path: Path, request_id: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid request transaction {path}: {exc}")
    if not isinstance(value, dict) or value.get("request_id") != request_id:
        fail(f"request transaction does not match {request_id!r}: {path}")
    return value


def finish_transaction(
    site_root: Path,
    config: dict[str, Any],
    paths: dict[str, Path],
    path: Path,
    transaction: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    staged = transaction.get("paths")
    if not isinstance(staged, list) or not staged or any(not isinstance(item, str) for item in staged):
        fail(f"request transaction has invalid paths: {path}")
    manifest_relative = relative_git_path(site_root, paths["manifest"])
    for relative in staged:
        target = (site_root / relative).resolve()
        if target == paths["manifest"].resolve():
            continue
        try:
            target.relative_to(paths["content"].resolve())
        except ValueError:
            fail(f"request transaction path is outside managed content: {relative}")
    if manifest_relative not in staged:
        fail(f"request transaction does not include the manifest: {path}")

    if not bool(transaction.get("build_done", False)):
        if bool(transaction.get("build_requested", False)):
            result["build"] = build_site(site_root, config)
        transaction["build_done"] = True
        write_transaction(path, transaction)

    if not bool(transaction.get("commit_done", False)):
        if bool(transaction.get("commit_requested", False)):
            git(site_root, ["add", "--", *staged])
            if git(site_root, ["diff", "--cached", "--quiet"], check=False).returncode != 0:
                message = str(transaction.get("commit_message", "docs: update embedded notes"))
                git(site_root, ["commit", "-m", message])
            result["commit"] = git_ref(site_root, "HEAD")
        transaction["commit_done"] = True
        write_transaction(path, transaction)

    if not bool(transaction.get("push_done", False)):
        if bool(transaction.get("push_requested", False)):
            git_config = section(config, "git")
            remote = str(git_config.get("remote", "origin"))
            branch = str(git_config.get("branch", "main"))
            git(site_root, ["push", remote, f"HEAD:{branch}"])
            result["push"] = {"remote": remote, "branch": branch}
        transaction["push_done"] = True
        write_transaction(path, transaction)

    if not bool(transaction.get("publish_done", False)):
        if bool(transaction.get("publish_requested", False)):
            result["publish"] = publish_site(site_root, config)
        transaction["publish_done"] = True
        write_transaction(path, transaction)

    path.unlink(missing_ok=True)
    return result


def request_data(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid request {path}: {exc}")
    if not isinstance(value, dict):
        fail("request must be a JSON object")
    mode = value.get("mode", "single")
    count = value.get("count", 1)
    drafts = value.get("drafts")
    if not isinstance(drafts, list):
        fail("request.drafts must be a list")
    try:
        validate_request_shape(mode, count, len(drafts))
    except ValueError as exc:
        fail(str(exc))
    action = value.get("action", "create")
    if action not in {"create", "update"}:
        fail("request.action must be create or update")
    request_id = value.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        fail("request.request_id is required for idempotent retries")
    return value


def read_drafts(request_path: Path, request: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in request["drafts"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            fail("each request.drafts entry must contain a path")
        draft_path = (request_path.parent / item["path"]).resolve()
        if not draft_path.is_file():
            fail(f"missing draft: {draft_path}")
        try:
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"invalid draft {draft_path}: {exc}")
        if not isinstance(draft, dict):
            fail(f"draft must be a JSON object: {draft_path}")
        draft["_request_item"] = item
        output.append(draft)
    return output


def source_list(request: dict[str, Any], draft: dict[str, Any]) -> list[dict[str, Any]]:
    values = draft.get("sources", request.get("sources", []))
    if values is None:
        return []
    if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
        fail("sources must be a list of objects")
    return [
        {key: item[key] for key in SOURCE_METADATA_FIELDS if key in item}
        for item in values
    ]


def render_yaml_frontmatter(metadata: dict[str, Any]) -> str:
    lines = ["---", f"title: {yaml_quote(metadata['title'])}", f"date: {yaml_quote(metadata['date'])}"]
    if metadata.get("lastmod"):
        lines.append(f"lastmod: {yaml_quote(metadata['lastmod'])}")
    lines.append(f"draft: {'true' if metadata['draft'] else 'false'}")
    lines.append(f"featureimage: {yaml_quote(metadata.get('featureimage', ''))}")
    lines.append(f"summary: {yaml_quote(metadata.get('summary', ''))}")
    if metadata.get("categories"):
        lines.append("categories:")
        lines.extend(f"  - {yaml_quote(category)}" for category in metadata["categories"])
    if metadata.get("series"):
        lines.append("series: [" + ", ".join(yaml_quote(item) for item in metadata["series"]) + "]")
    if metadata.get("series_order") is not None:
        lines.append(f"series_order: {metadata['series_order']}")
    if metadata.get("tags"):
        lines.append("tags:")
        lines.extend(f"  - {yaml_quote(tag)}" for tag in metadata["tags"])
    lines.append(f"note_id: {yaml_quote(metadata['note_id'])}")
    if metadata.get("sources"):
        lines.append("sources:")
        for source in metadata["sources"]:
            lines.append("  -")
            for key, value in source.items():
                if isinstance(value, (str, int, float, bool)):
                    lines.append(f"    {key}: {yaml_quote(value)}")
    lines.append("---")
    return "\n".join(lines)


def render_json_frontmatter(metadata: dict[str, Any]) -> str:
    return ";;;\n" + json.dumps(metadata, ensure_ascii=False, indent=2) + "\n;;;"


def render_toml_frontmatter(metadata: dict[str, Any]) -> str:
    lines = ["+++", f"title = {yaml_quote(metadata['title'])}", f"date = {yaml_quote(metadata['date'])}"]
    if metadata.get("lastmod"):
        lines.append(f"lastmod = {yaml_quote(metadata['lastmod'])}")
    lines.append(f"draft = {'true' if metadata['draft'] else 'false'}")
    lines.append(f"featureimage = {yaml_quote(metadata.get('featureimage', ''))}")
    lines.append(f"summary = {yaml_quote(metadata.get('summary', ''))}")
    for field in ("categories", "series", "tags"):
        if metadata.get(field):
            lines.append(f"{field} = [" + ", ".join(yaml_quote(item) for item in metadata[field]) + "]")
    if metadata.get("series_order") is not None:
        lines.append(f"series_order = {metadata['series_order']}")
    lines.append(f"note_id = {yaml_quote(metadata['note_id'])}")
    for source in metadata.get("sources", []):
        lines.append("")
        lines.append("[[sources]]")
        for key, value in source.items():
            if isinstance(value, (str, int, float, bool)):
                lines.append(f"{key} = {yaml_quote(value)}")
    lines.append("+++")
    return "\n".join(lines)


def render_note(config: dict[str, Any], draft: dict[str, Any], note_id: str, request: dict[str, Any]) -> tuple[str, str]:
    title = draft.get("title")
    body = draft.get("body")
    if not isinstance(title, str) or not title.strip():
        fail("draft.title is required")
    if not isinstance(body, str) or not body.strip():
        fail(f"draft.body is required for {title!r}")
    if body.lstrip().startswith(("---", "+++", ";;;")):
        fail("draft.body must not contain a second front matter block")
    site = section(config, "site")
    tags = list(site.get("default_tags", []))
    draft_tags = draft.get("tags", [])
    if not isinstance(draft_tags, list) or any(not isinstance(tag, str) for tag in draft_tags):
        fail("draft.tags must be a list of strings")
    for tag in draft_tags:
        if tag not in tags:
            tags.append(tag)
    categories = list(site.get("default_categories", []))
    draft_categories = draft.get("categories", [])
    if not isinstance(draft_categories, list) or any(not isinstance(item, str) for item in draft_categories):
        fail("draft.categories must be a list of strings")
    for category in draft_categories:
        if category not in categories:
            categories.append(category)
    series = draft.get("series", site.get("default_series", []))
    if not isinstance(series, list) or any(not isinstance(item, str) for item in series):
        fail("draft.series must be a list of strings")
    series_order = draft.get("series_order")
    if series_order is not None and (not isinstance(series_order, int) or series_order < 1):
        fail("draft.series_order must be a positive integer")
    date_value = draft.get("date", now_iso())
    date_prefix(date_value)
    metadata: dict[str, Any] = {
        "title": title.strip(),
        "date": date_value,
        "lastmod": draft.get("lastmod", date_value) if bool(site.get("include_lastmod", True)) else None,
        "draft": bool(draft.get("draft", site.get("default_draft", False))),
        "featureimage": draft.get("featureimage", site.get("default_featureimage", "")),
        "summary": draft.get("summary", draft.get("description", site.get("default_summary", ""))),
        "categories": categories,
        "series": series,
        "series_order": series_order,
        "note_id": note_id,
        "tags": tags,
        "sources": source_list(request, draft),
    }
    if not isinstance(metadata["date"], str):
        fail("draft.date must be a string")
    front_matter = str(site.get("front_matter", "yaml")).lower()
    if front_matter == "yaml":
        header = render_yaml_frontmatter(metadata)
    elif front_matter == "json":
        header = render_json_frontmatter(metadata)
    elif front_matter == "toml":
        header = render_toml_frontmatter(metadata)
    else:
        fail("site.front_matter must be yaml, toml, or json")
    slug = safe_slug(str(draft.get("slug", title)))
    return slug, header + "\n\n" + body.rstrip() + "\n"


def validate_markdown(path: Path, front_matter: str) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")
    delimiter = {"yaml": "---", "toml": "+++", "json": ";;;"}.get(front_matter.lower())
    if not delimiter or not content.startswith(delimiter + "\n"):
        fail(f"{path} does not start with {front_matter} front matter")
    end = content.find("\n" + delimiter, len(delimiter) + 1)
    if end < 0:
        fail(f"{path} has no closing front matter delimiter")
    header = content[len(delimiter) + 1 : end]
    format_name = front_matter.lower()
    if format_name == "yaml" and not re.search(r"(?m)^title:\s*", header):
        fail(f"{path} front matter has no title")
    if format_name == "json":
        try:
            parsed = json.loads(header)
        except json.JSONDecodeError as exc:
            fail(f"{path} has invalid JSON front matter: {exc}")
        if not isinstance(parsed, dict) or not parsed.get("title"):
            fail(f"{path} JSON front matter has no title")
    if format_name == "toml":
        try:
            parsed = tomllib.loads(header)
        except tomllib.TOMLDecodeError as exc:
            fail(f"{path} has invalid TOML front matter: {exc}")
        if not parsed.get("title"):
            fail(f"{path} TOML front matter has no title")
    if not content[end + len(delimiter) + 1 :].strip():
        fail(f"{path} has an empty body")
    return {"path": str(path), "bytes": len(content.encode("utf-8")), "sha256": sha256_text(content)}


def manifest_path_for_note(manifest: dict[str, Any], note_id: str) -> Path | None:
    entry = manifest.get("notes", {}).get(note_id)
    if isinstance(entry, dict) and isinstance(entry.get("path"), str):
        return Path(entry["path"])
    return None


def resolve_update_target(site_root: Path, paths: dict[str, Path], manifest: dict[str, Any], item: dict[str, Any]) -> tuple[str, Path]:
    note_id = item.get("note_id")
    target = item.get("target")
    if isinstance(note_id, str):
        relative = manifest_path_for_note(manifest, note_id)
        if relative is None:
            fail(f"unknown note_id for update: {note_id}")
        target_path = (site_root / relative).resolve()
        if not target_path.is_file():
            fail(f"manifest target does not exist for update: {target_path}")
        return note_id, target_path
    if isinstance(target, str):
        target_path = (site_root / target).resolve()
        try:
            target_path.relative_to(paths["content"])
        except ValueError:
            fail("update target must be below site.content_dir")
        if not target_path.is_file():
            fail(f"update target does not exist: {target_path}")
        target_relative = relative_git_path(site_root, target_path)
        found = next((key for key, entry in manifest.get("notes", {}).items() if entry.get("path") == target_relative), None)
        return found or f"embedded-{uuid.uuid4().hex}", target_path
    fail("update draft requires note_id or target")


def create_notes(args: argparse.Namespace) -> dict[str, Any]:
    site_root = resolve_site_root(args.site_root)
    config = load_config(site_root)
    paths = site_paths(site_root, config)
    request_path = Path(args.request).expanduser().resolve()
    request = request_data(request_path)
    drafts = read_drafts(request_path, request)
    git_config = section(config, "git")
    auto_commit = bool(git_config.get("auto_commit", True))
    auto_push = bool(git_config.get("auto_push", True))
    if auto_push and not auto_commit:
        fail("git.auto_push requires git.auto_commit for note creation")
    with RepoLock(paths["locks"] / "notesctl.lock"):
        sync_result = sync_repo(site_root, config)
        manifest = load_manifest(paths)
        request_id = request["request_id"]
        old_request = manifest.get("requests", {}).get(request_id)
        if old_request:
            pending = transaction_path(paths, request_id)
            if pending.is_file():
                transaction = load_transaction(pending, request_id)
                completion = finish_transaction(site_root, config, paths, pending, transaction)
                return {
                    "status": "resumed",
                    "request_id": request_id,
                    "notes": old_request,
                    "sync": sync_result,
                    "completion": completion,
                }
            return {"status": "already-applied", "request_id": request_id, "notes": old_request, "sync": sync_result}
        if git(site_root, ["diff", "--cached", "--quiet"], check=False).returncode != 0:
            fail("the Git index already contains staged changes; commit or unstage them before creating notes")

        artifacts: list[dict[str, Any]] = []
        original_files: dict[Path, bytes | None] = {}
        original_manifest = paths["manifest"].read_bytes() if paths["manifest"].exists() else None
        for index, draft in enumerate(drafts):
            item = draft.pop("_request_item")
            if request["action"] == "update":
                note_id, target = resolve_update_target(site_root, paths, manifest, item)
                try:
                    target.relative_to(paths["content"])
                except ValueError:
                    fail("update target must be below site.content_dir")
                slug, rendered = render_note(config, draft, note_id, request)
            else:
                note_id = stable_note_id(request_id, index)
                slug, rendered = render_note(config, draft, note_id, request)
                filename_date = date_prefix(draft.get("date", now_iso()))
                style = str(section(config, "site").get("filename_style", "date-slug"))
                filename = f"{filename_date}-{slug}.md" if style == "date-slug" else f"{slug}.md"
                target = paths["content"] / filename
                if target.exists():
                    filename = f"{target.stem}--{note_id[-8:]}{target.suffix}"
                    target = paths["content"] / filename
            if target in original_files:
                fail(f"multiple drafts target the same file: {target}")
            original_files[target] = target.read_bytes() if target.exists() else None
            artifacts.append({
                "note_id": note_id,
                "path": relative_git_path(site_root, target),
                "title": draft["title"],
                "sha256": sha256_text(rendered),
                "rendered": rendered,
                "request_id": request_id,
                "slug": slug,
            })

        if any(original is not None for original in original_files.values()):
            backup_state(site_root, paths, "update")

        publish_requested = bool(request.get("publish", section(config, "publish").get("enabled", False)))
        build_requested = bool(request.get("build", section(config, "hugo").get("enabled", True)))
        commit_message = "docs: add embedded note" if len(artifacts) == 1 else f"docs: add {len(artifacts)} embedded notes"
        pending = transaction_path(paths, request_id)
        transaction = {
            "version": 1,
            "request_id": request_id,
            "paths": [artifact["path"] for artifact in artifacts]
            + [relative_git_path(site_root, paths["manifest"])],
            "build_requested": build_requested,
            "build_done": not build_requested,
            "commit_requested": auto_commit,
            "commit_done": not auto_commit,
            "commit_message": commit_message,
            "push_requested": auto_push,
            "push_done": not auto_push,
            "publish_requested": publish_requested,
            "publish_done": not publish_requested,
        }
        write_transaction(pending, transaction)
        build_result: dict[str, Any] | None = None
        try:
            for artifact in artifacts:
                atomic_write(site_root / artifact["path"], artifact["rendered"].encode("utf-8"))
                validate_markdown(
                    site_root / artifact["path"],
                    str(section(config, "site").get("front_matter", "yaml")),
                )
            for artifact in artifacts:
                manifest.setdefault("notes", {})[artifact["note_id"]] = {
                    key: artifact[key] for key in ("path", "title", "sha256", "request_id")
                }
            manifest.setdefault("requests", {})[request_id] = [artifact["note_id"] for artifact in artifacts]
            atomic_json(paths["manifest"], manifest)
            if build_requested:
                build_result = build_site(site_root, config)
            transaction["build_done"] = True
            write_transaction(pending, transaction)
        except Exception:
            for path, original in original_files.items():
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, original)
            if original_manifest is None:
                paths["manifest"].unlink(missing_ok=True)
            else:
                atomic_write(paths["manifest"], original_manifest)
            pending.unlink(missing_ok=True)
            raise
        completion = finish_transaction(site_root, config, paths, pending, transaction)
        if build_result is not None:
            completion = {"build": build_result, **completion}
    return {
        "status": "created",
        "request_id": request_id,
        "notes": [{k: v for k, v in item.items() if k != "rendered"} for item in artifacts],
        "sync": sync_result,
        "completion": completion,
    }


def build_site(site_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    hugo = section(config, "hugo")
    command = hugo.get("command", ["hugo", "--minify"])
    if not hugo.get("enabled", True):
        return {"status": "disabled"}
    if not isinstance(command, list) or not command or any(not isinstance(item, str) for item in command):
        fail("hugo.command must be a non-empty argument list")
    result = run_command(command, site_root)
    return {"status": "built", "stdout": (result.stdout or "").strip()}


def publish_site(site_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    publish = section(config, "publish")
    command = publish.get("command", [])
    if not publish.get("enabled", False):
        return {"status": "disabled"}
    if not isinstance(command, list) or not command or any(not isinstance(item, str) for item in command):
        fail("publish.command must be a non-empty argument list")
    public_dir = site_root / "public"
    commit = git_text(site_root, ["rev-parse", "HEAD"], check=False)
    formatted = [item.format(site_root=str(site_root), public_dir=str(public_dir), commit=commit) for item in command]
    result = run_command(formatted, site_root)
    return {"status": "published", "stdout": (result.stdout or "").strip(), "public_dir": str(public_dir)}


def status_site(args: argparse.Namespace) -> dict[str, Any]:
    site_root = resolve_site_root(args.site_root)
    config = load_config(site_root)
    paths = site_paths(site_root, config)
    git_root(site_root)
    git_config = section(config, "git")
    local = git_ref(site_root, "HEAD")
    remote_ref = f"refs/remotes/{git_config.get('remote', 'origin')}/{git_config.get('branch', 'main')}"
    return {"site_root": str(site_root), "local": local, "remote": git_ref(site_root, remote_ref), "worktree": status_paths(site_root), "content_dir": str(paths["content"])}


def validate_command(args: argparse.Namespace) -> dict[str, Any]:
    site_root = resolve_site_root(args.site_root)
    config = load_config(site_root)
    path = Path(args.path)
    if not path.is_absolute():
        path = site_root / path
    return validate_markdown(path.resolve(), str(section(config, "site").get("front_matter", "yaml")))


def build_command(args: argparse.Namespace) -> dict[str, Any]:
    site_root = resolve_site_root(args.site_root)
    config = load_config(site_root)
    with RepoLock(site_paths(site_root, config)["locks"] / "notesctl.lock"):
        sync = sync_repo(site_root, config)
        result = build_site(site_root, config)
    return {"sync": sync, "build": result}


def publish_command(args: argparse.Namespace) -> dict[str, Any]:
    site_root = resolve_site_root(args.site_root)
    config = load_config(site_root)
    with RepoLock(site_paths(site_root, config)["locks"] / "notesctl.lock"):
        sync = sync_repo(site_root, config)
        result = publish_site(site_root, config)
    return {"sync": sync, "publish": result}


def plan_file(plan_id: str, paths: dict[str, Path]) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", plan_id):
        fail("plan id contains unsupported characters")
    path = paths["plans"] / f"{plan_id}.toml"
    if not path.is_file():
        fail(f"missing plan: {path}")
    return path


def configured_generator(config: dict[str, Any]) -> list[str]:
    command = section(config, "generator").get("command", [])
    if not isinstance(command, list) or not command or any(not isinstance(item, str) for item in command):
        fail("generator.command must be configured for plan run")
    return command


def schedule_values(data: dict[str, Any]) -> tuple[list[str], str]:
    expression = data.get("schedule")
    if not isinstance(expression, str) or len(expression.split()) != 5:
        fail("plan.schedule must be a five-field cron expression")
    fields = expression.split()
    if not (fields[0].isdigit() and fields[1].isdigit() and fields[2] == "*" and fields[3] == "*"):
        fail("scheduler supports daily or weekly plans such as '0 20 * * 1'")
    hour, minute = int(fields[1]), int(fields[0])
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        fail("schedule hour or minute is out of range")
    timezone = data.get("timezone", "local")
    if not isinstance(timezone, str) or not re.fullmatch(r"[A-Za-z0-9_+./-]{1,64}", timezone):
        fail("plan.timezone must be 'local' or an IANA timezone such as Asia/Shanghai")
    return fields, timezone


def plan_run(args: argparse.Namespace) -> dict[str, Any]:
    site_root = resolve_site_root(args.site_root)
    config = load_config(site_root)
    paths = site_paths(site_root, config)
    path = plan_file(args.plan_id, paths)
    with path.open("rb") as stream:
        plan = tomllib.load(stream)
    topics = plan.get("topics", [])
    if not isinstance(topics, list) or not topics or any(not isinstance(topic, str) for topic in topics):
        fail("plan.topics must be a non-empty list of strings")
    with RepoLock(paths["locks"] / "plan.lock"):
        sync = sync_repo(site_root, config)
    command = configured_generator(config)
    run_id = args.run_id or f"{args.plan_id}-{now_stamp()}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", run_id):
        fail("run id contains unsupported characters")
    results: list[dict[str, Any]] = []
    for index, topic in enumerate(topics, start=1):
        request_id = f"plan-{run_id}-{index}"
        prompt = (
            f"Use $embedded-notes with plan file {path}. Generate exactly one note for topic {topic!r}. "
            f"Use mode single, count 1, and request_id {request_id!r}. Do not generate any other topic. "
            "Apply the plan's declared sources and publish setting, then call notesctl create."
        )
        substitutions = {
            "plan_file": str(path),
            "plan_id": args.plan_id,
            "run_id": run_id,
            "site_root": str(site_root),
            "topic": topic,
            "index": str(index),
            "count": str(len(topics)),
            "request_id": request_id,
            "prompt": prompt,
        }
        item_command = [item.format(**substitutions) for item in command]
        environment = os.environ.copy()
        environment.update({
            "EMBEDDED_NOTES_PLAN_ID": args.plan_id,
            "EMBEDDED_NOTES_PLAN_FILE": str(path),
            "EMBEDDED_NOTES_PLAN_RUN_ID": run_id,
            "EMBEDDED_NOTES_PLAN_INDEX": str(index),
            "EMBEDDED_NOTES_PLAN_COUNT": str(len(topics)),
            "EMBEDDED_NOTES_REQUEST_ID": request_id,
            "EMBEDDED_NOTES_SITE_ROOT": str(site_root),
            "EMBEDDED_NOTES_TOPIC": topic,
            "EMBEDDED_NOTES_PROMPT": prompt,
        })
        result = run_command(item_command, site_root, env=environment)
        results.append({"index": index, "topic": topic, "request_id": request_id, "stdout": (result.stdout or "").strip()})
    return {"status": "ran", "sync": sync, "plan_id": args.plan_id, "run_id": run_id, "items": results}


def schedule_paths(site_root: Path, plan_id: str) -> tuple[Path, Path]:
    directory = site_root / ".embedded-notes" / "scheduler"
    return directory / f"{plan_id}.cmd", directory / f"{plan_id}.sh"


def schedule_install(args: argparse.Namespace) -> dict[str, Any]:
    site_root = resolve_site_root(args.site_root)
    config = load_config(site_root)
    paths = site_paths(site_root, config)
    plan = plan_file(args.plan_id, paths)
    with plan.open("rb") as stream:
        data = tomllib.load(stream)
    fields, timezone = schedule_values(data)
    generator_command = configured_generator(config)
    generator_executable = shutil.which(generator_command[0])
    if generator_executable is None:
        fail(f"generator executable is not available on PATH: {generator_command[0]}")
    if sys.platform.startswith("win"):
        hour, minute = int(fields[1]), int(fields[0])
        if timezone != "local":
            expected = WINDOWS_TIMEZONES.get(timezone)
            if expected is None:
                fail(f"Windows timezone is not mapped: {timezone}; use local or a supported IANA timezone")
            active = (run_command(["tzutil", "/g"], site_root).stdout or "").strip()
            if active.casefold() != expected.casefold():
                fail(
                    f"Windows Task Scheduler uses the system timezone {active!r}, but the plan requires "
                    f"{timezone!r} ({expected!r})"
                )
        command_file, _ = schedule_paths(site_root, args.plan_id)
        command_file.parent.mkdir(parents=True, exist_ok=True)
        script = Path(__file__).resolve()
        command_file.write_text(
            "@echo off\n"
            + f'@set "PATH={os.environ.get("PATH", "")}"\n'
            + f'"{sys.executable}" "{script}" plan run --site-root "{site_root}" --plan-id "{args.plan_id}"\n',
            encoding="utf-8",
        )
        task_name = f"EmbeddedNotes-{args.plan_id}"
        if fields[4] == "*":
            schtasks = ["schtasks", "/Create", "/F", "/TN", task_name, "/TR", str(command_file), "/SC", "DAILY", "/ST", f"{hour:02d}:{minute:02d}"]
        else:
            dow = {"0": "SUN", "1": "MON", "2": "TUE", "3": "WED", "4": "THU", "5": "FRI", "6": "SAT", "7": "SUN"}.get(fields[4])
            if dow is None:
                fail("Windows weekly schedule requires a numeric day-of-week")
            schtasks = ["schtasks", "/Create", "/F", "/TN", task_name, "/TR", str(command_file), "/SC", "WEEKLY", "/D", dow, "/ST", f"{hour:02d}:{minute:02d}"]
        run_command(schtasks, site_root)
        return {
            "status": "installed",
            "platform": "windows",
            "task": task_name,
            "wrapper": str(command_file),
            "timezone": timezone,
            "generator": generator_executable,
        }
    if fields[0].isdigit() and fields[1].isdigit() and fields[2] == "*" and fields[3] == "*":
        hour, minute = int(fields[1]), int(fields[0])
        day = {"0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed", "4": "Thu", "5": "Fri", "6": "Sat", "7": "Sun", "*": "*"}.get(fields[4])
        if day is None:
            fail("Linux schedule requires a numeric day-of-week")
        _, shell_file = schedule_paths(site_root, args.plan_id)
        shell_file.parent.mkdir(parents=True, exist_ok=True)
        shell_command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "plan",
            "run",
            "--site-root",
            str(site_root),
            "--plan-id",
            args.plan_id,
        ]
        shell_file.write_text(
            "#!/bin/sh\nexport PATH="
            + shlex.quote(os.environ.get("PATH", ""))
            + "\nexec "
            + " ".join(shlex.quote(item) for item in shell_command)
            + "\n",
            encoding="utf-8",
        )
        shell_file.chmod(0o700)
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        service_name = f"embedded-notes-{args.plan_id}"
        (unit_dir / f"{service_name}.service").write_text(
            "[Unit]\nDescription=Embedded notes plan\n\n[Service]\nType=oneshot\nExecStart="
            + json.dumps(str(shell_file), ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        calendar = f"{day} *-*-* {hour:02d}:{minute:02d}:00" if day != "*" else f"*-*-* {hour:02d}:{minute:02d}:00"
        if timezone != "local":
            calendar += f" {timezone}"
        (unit_dir / f"{service_name}.timer").write_text("[Unit]\nDescription=Embedded notes schedule\n\n[Timer]\nOnCalendar=" + calendar + "\nPersistent=true\nUnit=" + service_name + ".service\n\n[Install]\nWantedBy=default.target\n", encoding="utf-8")
        run_command(["systemctl", "--user", "daemon-reload"], site_root)
        run_command(["systemctl", "--user", "enable", "--now", f"{service_name}.timer"], site_root)
        return {
            "status": "installed",
            "platform": "linux",
            "timer": service_name,
            "wrapper": str(shell_file),
            "timezone": timezone,
            "generator": generator_executable,
        }
    fail("unsupported schedule; use a daily or weekly '0 H * * [DOW]' expression")


def schedule_remove(args: argparse.Namespace) -> dict[str, Any]:
    site_root = resolve_site_root(args.site_root)
    load_config(site_root)
    if sys.platform.startswith("win"):
        task_name = f"EmbeddedNotes-{args.plan_id}"
        run_command(["schtasks", "/Delete", "/F", "/TN", task_name], site_root)
        command_file, _ = schedule_paths(site_root, args.plan_id)
        command_file.unlink(missing_ok=True)
        return {"status": "removed", "platform": "windows", "task": task_name}
    service_name = f"embedded-notes-{args.plan_id}"
    run_command(["systemctl", "--user", "disable", "--now", f"{service_name}.timer"], site_root)
    for suffix in (".service", ".timer"):
        (Path.home() / ".config" / "systemd" / "user" / f"{service_name}{suffix}").unlink(missing_ok=True)
    _, shell_file = schedule_paths(site_root, args.plan_id)
    shell_file.unlink(missing_ok=True)
    return {"status": "removed", "platform": "linux", "timer": service_name}


def sync_command(args: argparse.Namespace) -> dict[str, Any]:
    site_root = resolve_site_root(args.site_root)
    config = load_config(site_root)
    paths = site_paths(site_root, config)
    with RepoLock(paths["locks"] / "notesctl.lock"):
        return sync_repo(site_root, config)


def source_command(args: argparse.Namespace) -> dict[str, Any]:
    try:
        if args.source_command == "file":
            return read_file_source(Path(args.path), max_bytes=args.max_bytes)
        if args.source_command == "url":
            return read_url_source(args.url, max_bytes=args.max_bytes, timeout=args.timeout)
        if args.source_command == "note":
            site_root = resolve_site_root(args.site_root)
            config = load_config(site_root)
            paths = site_paths(site_root, config)
            with RepoLock(paths["locks"] / "notesctl.lock"):
                sync = sync_repo(site_root, config)
                manifest = load_manifest(paths)
                note_id = args.note_id
                if note_id:
                    relative = manifest_path_for_note(manifest, note_id)
                    if relative is None:
                        fail(f"unknown note_id: {note_id}")
                    target = (site_root / relative).resolve()
                else:
                    candidate = Path(args.path)
                    target = (candidate if candidate.is_absolute() else site_root / candidate).resolve()
                    relative = Path(relative_git_path(site_root, target))
                    note_id = next(
                        (
                            key
                            for key, entry in manifest.get("notes", {}).items()
                            if isinstance(entry, dict) and entry.get("path") == relative.as_posix()
                        ),
                        None,
                    )
                try:
                    target.relative_to(paths["content"].resolve())
                except ValueError:
                    fail("note source must be below site.content_dir")
                source = read_file_source(target, max_bytes=args.max_bytes)
                source.update({
                    "type": "note",
                    "path": relative_git_path(site_root, target),
                    "note_id": note_id,
                    "sync": sync,
                })
                return source
    except (OSError, ValueError) as exc:
        fail(str(exc))
    fail("unsupported source command")


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--site-root")
    root = argparse.ArgumentParser(prog="notesctl")
    sub = root.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--site-root", required=True)
    init.add_argument("--content-dir")
    init.add_argument("--remote")
    init.add_argument("--branch")

    sub.add_parser("status", parents=[common])
    sub.add_parser("sync", parents=[common])
    validate = sub.add_parser("validate", parents=[common])
    validate.add_argument("--path", required=True)
    sub.add_parser("build", parents=[common])
    sub.add_parser("publish", parents=[common])
    create = sub.add_parser("create", parents=[common])
    create.add_argument("--request", required=True)
    source = sub.add_parser("source")
    source_sub = source.add_subparsers(dest="source_command", required=True)
    source_file = source_sub.add_parser("file")
    source_file.add_argument("--path", required=True)
    source_file.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    source_url = source_sub.add_parser("url")
    source_url.add_argument("--url", required=True)
    source_url.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    source_url.add_argument("--timeout", type=float, default=30.0)
    source_note = source_sub.add_parser("note", parents=[common])
    source_note_target = source_note.add_mutually_exclusive_group(required=True)
    source_note_target.add_argument("--note-id")
    source_note_target.add_argument("--path")
    source_note.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    plan = sub.add_parser("plan")
    plan_sub = plan.add_subparsers(dest="plan_command", required=True)
    plan_run_parser = plan_sub.add_parser("run", parents=[common])
    plan_run_parser.add_argument("--plan-id", required=True)
    plan_run_parser.add_argument("--run-id")
    schedule = sub.add_parser("schedule")
    schedule_sub = schedule.add_subparsers(dest="schedule_command", required=True)
    schedule_install_parser = schedule_sub.add_parser("install", parents=[common])
    schedule_install_parser.add_argument("--plan-id", required=True)
    schedule_remove_parser = schedule_sub.add_parser("remove", parents=[common])
    schedule_remove_parser.add_argument("--plan-id", required=True)
    return root


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "init":
        return init_site(args)
    if args.command == "status":
        return status_site(args)
    if args.command == "sync":
        return sync_command(args)
    if args.command == "validate":
        return validate_command(args)
    if args.command == "build":
        return build_command(args)
    if args.command == "publish":
        return publish_command(args)
    if args.command == "create":
        return create_notes(args)
    if args.command == "source":
        return source_command(args)
    if args.command == "plan" and args.plan_command == "run":
        return plan_run(args)
    if args.command == "schedule" and args.schedule_command == "install":
        return schedule_install(args)
    if args.command == "schedule" and args.schedule_command == "remove":
        return schedule_remove(args)
    fail("unsupported command")


def main(argv: list[str] | None = None) -> int:
    try:
        result = dispatch(parser().parse_args(argv))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except NotesError as exc:
        print(f"notesctl: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
