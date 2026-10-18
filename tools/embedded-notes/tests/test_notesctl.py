from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "notesctl.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("notesctl", SCRIPT)
assert SPEC and SPEC.loader
notesctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(notesctl)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def configure_site(site: Path) -> None:
    config_path = site / ".embedded-notes" / "config.toml"
    config = config_path.read_text(encoding="utf-8")
    config = config.replace("[hugo]\nenabled = true", "[hugo]\nenabled = false")
    config = config.replace("auto_push = true", "auto_push = false")
    config = config.replace("require_remote = true", "require_remote = false")
    config_path.write_text(config, encoding="utf-8")


def commit_initial(site: Path) -> None:
    git(site, "init", "-b", "main")
    git(site, "config", "user.email", "test@example.com")
    git(site, "config", "user.name", "Embedded Notes Test")
    git(site, "add", ".")
    git(site, "commit", "-m", "initial")


def make_request(root: Path, mode: str = "single", count: int = 1) -> Path:
    drafts = root / "drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    draft_items = []
    for index in range(count):
        path = drafts / f"draft-{index}.json"
        path.write_text(
            json.dumps(
                {
                    "title": f"DMA note {index}",
                    "slug": f"dma-{index}",
                    "tags": ["dma"],
                    "body": f"## Note {index}\n\nBody.",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        draft_items.append({"path": str(path.relative_to(root))})
    request = root / f"request-{mode}-{count}.json"
    request.write_text(
        json.dumps(
            {
                "request_id": f"test-{mode}-{count}",
                "mode": mode,
                "count": count,
                "action": "create",
                "drafts": draft_items,
            }
        ),
        encoding="utf-8",
    )
    return request


class NotesctlTests(unittest.TestCase):
    def test_status_paths_preserves_first_character_of_tracked_modification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory) / "site"
            site.mkdir()
            tracked = site / "content" / "embedded" / "tracked.md"
            tracked.parent.mkdir(parents=True)
            tracked.write_text("initial\n", encoding="utf-8")
            commit_initial(site)
            tracked.write_text("modified\n", encoding="utf-8")

            self.assertEqual(notesctl.status_paths(site), ["content/embedded/tracked.md"])

    def test_site_root_resolves_from_environment_or_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory) / "site"
            nested = site / "content" / "embedded"
            notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded", "remote": None, "branch": None})())
            nested.mkdir(parents=True, exist_ok=True)
            with mock.patch.dict(os.environ, {"EMBEDDED_NOTES_SITE_ROOT": str(site)}):
                self.assertEqual(notesctl.resolve_site_root(None), site.resolve())
            original = Path.cwd()
            try:
                os.chdir(nested)
                with mock.patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(notesctl.resolve_site_root(None), site.resolve())
            finally:
                os.chdir(original)

    def test_single_request_rejects_multiple_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / "request.json"
            request.write_text(
                json.dumps({"request_id": "bad", "mode": "single", "count": 2, "drafts": [{"path": "a"}, {"path": "b"}]}),
                encoding="utf-8",
            )
            with self.assertRaises(notesctl.NotesError):
                notesctl.request_data(request)

    def test_single_create_is_one_note_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(site)
            commit_initial(site)
            request = make_request(root)

            first = notesctl.main(["create", "--site-root", str(site), "--request", str(request)])
            second = notesctl.main(["create", "--site-root", str(site), "--request", str(request)])

            self.assertEqual(first, 0)
            self.assertEqual(second, 0)
            notes = list((site / "content" / "embedded").glob("*.md"))
            self.assertEqual(len(notes), 1)
            content = notes[0].read_text(encoding="utf-8")
            self.assertIn('title: "DMA note 0"', content)
            manifest = json.loads((site / ".embedded-notes" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["notes"]), 1)
            self.assertEqual(len(manifest["requests"]), 1)

    def test_batch_count_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(site)
            commit_initial(site)
            request = make_request(root, mode="batch", count=3)

            self.assertEqual(notesctl.main(["create", "--site-root", str(site), "--request", str(request)]), 0)
            self.assertEqual(len(list((site / "content" / "embedded").glob("*.md"))), 3)

    def test_create_rejects_date_that_could_escape_content_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(site)
            commit_initial(site)
            request = make_request(root)
            draft_path = root / "drafts" / "draft-0.json"
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["date"] = "../../escape"
            draft_path.write_text(json.dumps(draft), encoding="utf-8")

            self.assertEqual(notesctl.main(["create", "--site-root", str(site), "--request", str(request)]), 2)
            self.assertEqual(list((site / "content" / "embedded").glob("*.md")), [])
            manifest = json.loads((site / ".embedded-notes" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["requests"], {})

    def test_plan_runs_one_generator_process_per_topic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            log = root / "topics.log"
            notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(site)
            code = (
                "import os; from pathlib import Path; "
                "p=Path(os.environ['PLAN_LOG']); "
                "p.open('a', encoding='utf-8').write(os.environ['EMBEDDED_NOTES_TOPIC'] + '\\n')"
            )
            command = json.dumps([sys.executable, "-c", code])
            config_path = site / ".embedded-notes" / "config.toml"
            config = re.sub(
                r'(?m)^command = \["codex", "exec".*$',
                lambda _: f"command = {command}",
                config_path.read_text(encoding="utf-8"),
                count=1,
            )
            config_path.write_text(config, encoding="utf-8")
            plan = site / ".embedded-notes" / "plans" / "weekly.toml"
            plan.write_text('id = "weekly"\ntopics = ["SPI DMA", "UART DMA", "DMA 环形缓冲区"]\n', encoding="utf-8")
            commit_initial(site)

            with mock.patch.dict(os.environ, {"PLAN_LOG": str(log)}):
                result = notesctl.main(["plan", "run", "--site-root", str(site), "--plan-id", "weekly", "--run-id", "fixed-run"])

            self.assertEqual(result, 0)
            self.assertEqual(log.read_text(encoding="utf-8").splitlines(), ["SPI DMA", "UART DMA", "DMA 环形缓冲区"])

    def test_note_source_syncs_and_resolves_manifest_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(site)
            commit_initial(site)
            request = make_request(root)
            created = notesctl.dispatch(notesctl.parser().parse_args(["create", "--site-root", str(site), "--request", str(request)]))
            note_id = created["notes"][0]["note_id"]

            source = notesctl.dispatch(
                notesctl.parser().parse_args(
                    ["source", "note", "--site-root", str(site), "--note-id", note_id]
                )
            )

            self.assertEqual(source["type"], "note")
            self.assertEqual(source["note_id"], note_id)
            self.assertEqual(source["sync"]["status"], "no-remote")
            self.assertIn("## Note 0", source["content"])
            self.assertTrue(source["path"].startswith("content/embedded/"))

    def test_linux_schedule_preserves_iana_timezone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site with space"
            home = root / "linux home"
            notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(site)
            plan = site / ".embedded-notes" / "plans" / "weekly.toml"
            plan.write_text(
                'id = "weekly"\nschedule = "0 20 * * 1"\ntimezone = "Asia/Shanghai"\ntopics = ["DMA"]\n',
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess([], 0, "", "")
            args = type("Args", (), {"site_root": str(site), "plan_id": "weekly"})()

            with mock.patch.object(notesctl.sys, "platform", "linux"), mock.patch.object(
                notesctl.Path, "home", return_value=home
            ), mock.patch.object(notesctl.shutil, "which", return_value="/usr/bin/codex"), mock.patch.object(
                notesctl, "run_command", return_value=completed
            ):
                result = notesctl.schedule_install(args)

            timer = home / ".config" / "systemd" / "user" / "embedded-notes-weekly.timer"
            service = home / ".config" / "systemd" / "user" / "embedded-notes-weekly.service"
            self.assertIn("OnCalendar=Mon *-*-* 20:00:00 Asia/Shanghai", timer.read_text(encoding="utf-8"))
            self.assertIn('ExecStart="', service.read_text(encoding="utf-8"))
            self.assertIn("export PATH=", (site / ".embedded-notes" / "scheduler" / "weekly.sh").read_text(encoding="utf-8"))
            self.assertEqual(result["timezone"], "Asia/Shanghai")

    def test_windows_schedule_rejects_timezone_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(site)
            plan = site / ".embedded-notes" / "plans" / "weekly.toml"
            plan.write_text(
                'id = "weekly"\nschedule = "0 20 * * 1"\ntimezone = "Asia/Shanghai"\ntopics = ["DMA"]\n',
                encoding="utf-8",
            )
            completed = subprocess.CompletedProcess([], 0, "Pacific Standard Time\n", "")
            args = type("Args", (), {"site_root": str(site), "plan_id": "weekly"})()

            with mock.patch.object(notesctl.sys, "platform", "win32"), mock.patch.object(
                notesctl.shutil, "which", return_value="C:\\tools\\codex.exe"
            ), mock.patch.object(
                notesctl, "run_command", return_value=completed
            ), self.assertRaises(notesctl.NotesError):
                notesctl.schedule_install(args)

    def test_build_failure_rolls_back_uncommitted_note(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(site)
            config_path = site / ".embedded-notes" / "config.toml"
            config = config_path.read_text(encoding="utf-8")
            config = re.sub(
                r'(?ms)\[hugo\]\nenabled = false\ncommand = \[[^\n]+\]',
                '[hugo]\nenabled = true\ncommand = ["python", "-c", "raise SystemExit(1)"]',
                config,
                count=1,
            )
            config_path.write_text(config, encoding="utf-8")
            commit_initial(site)
            request = make_request(root)

            self.assertEqual(notesctl.main(["create", "--site-root", str(site), "--request", str(request)]), 2)
            self.assertEqual(list((site / "content" / "embedded").glob("*.md")), [])
            manifest = json.loads((site / ".embedded-notes" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["requests"], {})

    def test_successful_build_is_reported_by_create(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(site)
            config_path = site / ".embedded-notes" / "config.toml"
            config = config_path.read_text(encoding="utf-8")
            config = re.sub(
                r'(?ms)\[hugo\]\nenabled = false\ncommand = \[[^\n]+\]',
                '[hugo]\nenabled = true\ncommand = ["python", "-c", "print(\'build-ok\')"]',
                config,
                count=1,
            )
            config_path.write_text(config, encoding="utf-8")
            commit_initial(site)
            request = make_request(root)

            result = notesctl.dispatch(
                notesctl.parser().parse_args(["create", "--site-root", str(site), "--request", str(request)])
            )

            self.assertEqual(result["completion"]["build"]["status"], "built")
            self.assertEqual(result["completion"]["build"]["stdout"], "build-ok")

    def test_publish_failure_keeps_committed_note(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(site)
            config_path = site / ".embedded-notes" / "config.toml"
            config = config_path.read_text(encoding="utf-8")
            config = config.replace(
                "[publish]\nenabled = false\ncommand = []",
                "[publish]\nenabled = true\ncommand = [\"python\", \"-c\", \"raise SystemExit(1)\"]",
            )
            config_path.write_text(config, encoding="utf-8")
            commit_initial(site)
            request = make_request(root)
            request_data = json.loads(request.read_text(encoding="utf-8"))
            request_data["publish"] = True
            request.write_text(json.dumps(request_data), encoding="utf-8")

            self.assertEqual(notesctl.main(["create", "--site-root", str(site), "--request", str(request)]), 2)
            self.assertEqual(len(list((site / "content" / "embedded").glob("*.md"))), 1)
            self.assertEqual(git(site, "status", "--porcelain"), "")
            self.assertIn("docs: add embedded note", git(site, "log", "-1", "--pretty=%s"))

    def test_same_request_resumes_failed_publish_without_duplicate_note(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            attempt = root / "publish-attempted"
            published = root / "published"
            notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(site)
            config_path = site / ".embedded-notes" / "config.toml"
            config = config_path.read_text(encoding="utf-8")
            code = (
                "from pathlib import Path; "
                f"attempt=Path({str(attempt)!r}); published=Path({str(published)!r}); "
                "already=attempt.exists(); attempt.write_text('attempted'); "
                "published.write_text('ok') if already else (_ for _ in ()).throw(SystemExit(1))"
            )
            command = json.dumps([sys.executable, "-c", code])
            config = config.replace(
                "[publish]\nenabled = false\ncommand = []",
                f"[publish]\nenabled = true\ncommand = {command}",
            )
            config_path.write_text(config, encoding="utf-8")
            commit_initial(site)
            request = make_request(root)
            request_data = json.loads(request.read_text(encoding="utf-8"))
            request_data["publish"] = True
            request.write_text(json.dumps(request_data), encoding="utf-8")

            self.assertEqual(notesctl.main(["create", "--site-root", str(site), "--request", str(request)]), 2)
            self.assertEqual(len(list((site / ".embedded-notes" / "transactions").glob("*.json"))), 1)
            self.assertEqual(notesctl.main(["create", "--site-root", str(site), "--request", str(request)]), 0)
            self.assertEqual(published.read_text(encoding="utf-8"), "ok")
            self.assertEqual(list((site / ".embedded-notes" / "transactions").glob("*.json")), [])
            self.assertEqual(len(list((site / "content" / "embedded").glob("*.md"))), 1)

    def test_remote_ahead_fast_forwards_local_site(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bare = root / "remote.git"
            local = root / "local"
            cloud = root / "cloud"
            local.mkdir()
            notesctl.init_site(type("Args", (), {"site_root": str(local), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(local)
            commit_initial(local)
            git(root, "init", "--bare", str(bare))
            git(local, "remote", "add", "origin", str(bare))
            git(local, "push", "-u", "origin", "HEAD:main")
            git(root, "clone", "-b", "main", str(bare), str(cloud))
            git(cloud, "config", "user.email", "test@example.com")
            git(cloud, "config", "user.name", "Embedded Notes Test")
            remote_note = cloud / "content" / "embedded" / "remote.md"
            remote_note.parent.mkdir(parents=True, exist_ok=True)
            remote_note.write_text("---\ntitle: Remote\n---\n\nCloud.\n", encoding="utf-8")
            git(cloud, "add", ".")
            git(cloud, "commit", "-m", "cloud note")
            git(cloud, "push", "origin", "HEAD:main")

            result = notesctl.main(["sync", "--site-root", str(local)])

            self.assertEqual(result, 0)
            self.assertTrue((local / "content" / "embedded" / "remote.md").is_file())
            self.assertEqual(git(local, "rev-parse", "HEAD"), git(local, "rev-parse", "refs/remotes/origin/main"))

    def test_remote_ahead_preserves_nonconflicting_changes_outside_managed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bare = root / "remote.git"
            local = root / "local"
            cloud = root / "cloud"
            local.mkdir()
            notesctl.init_site(type("Args", (), {"site_root": str(local), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(local)
            outside = local / "README.md"
            outside.write_text("initial\n", encoding="utf-8")
            commit_initial(local)
            git(root, "init", "--bare", str(bare))
            git(local, "remote", "add", "origin", str(bare))
            git(local, "push", "-u", "origin", "HEAD:main")
            git(root, "clone", "-b", "main", str(bare), str(cloud))
            git(cloud, "config", "user.email", "test@example.com")
            git(cloud, "config", "user.name", "Embedded Notes Test")

            outside.write_text("local work\n", encoding="utf-8")
            remote_note = cloud / "content" / "embedded" / "remote.md"
            remote_note.parent.mkdir(parents=True, exist_ok=True)
            remote_note.write_text("remote work\n", encoding="utf-8")
            git(cloud, "add", ".")
            git(cloud, "commit", "-m", "cloud note")
            git(cloud, "push", "origin", "HEAD:main")

            result = notesctl.dispatch(notesctl.parser().parse_args(["sync", "--site-root", str(local)]))

            self.assertEqual(result["status"], "fast-forwarded")
            self.assertIsNone(result["backup"])
            self.assertEqual(outside.read_text(encoding="utf-8"), "local work\n")
            self.assertTrue((local / "content" / "embedded" / "remote.md").is_file())
            self.assertIn("README.md", git(local, "status", "--porcelain"))

    def test_remote_ahead_rejects_overlapping_change_outside_managed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bare = root / "remote.git"
            local = root / "local"
            cloud = root / "cloud"
            local.mkdir()
            notesctl.init_site(type("Args", (), {"site_root": str(local), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(local)
            outside = local / "README.md"
            outside.write_text("initial\n", encoding="utf-8")
            commit_initial(local)
            git(root, "init", "--bare", str(bare))
            git(local, "remote", "add", "origin", str(bare))
            git(local, "push", "-u", "origin", "HEAD:main")
            git(root, "clone", "-b", "main", str(bare), str(cloud))
            git(cloud, "config", "user.email", "test@example.com")
            git(cloud, "config", "user.name", "Embedded Notes Test")

            outside.write_text("local work\n", encoding="utf-8")
            (cloud / "README.md").write_text("cloud work\n", encoding="utf-8")
            git(cloud, "add", ".")
            git(cloud, "commit", "-m", "cloud readme")
            git(cloud, "push", "origin", "HEAD:main")
            original_head = git(local, "rev-parse", "HEAD")

            self.assertEqual(notesctl.main(["sync", "--site-root", str(local)]), 2)
            self.assertEqual(git(local, "rev-parse", "HEAD"), original_head)
            self.assertEqual(outside.read_text(encoding="utf-8"), "local work\n")

    def test_remote_ahead_backs_up_uncommitted_managed_note(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bare = root / "remote.git"
            local = root / "local"
            cloud = root / "cloud"
            local.mkdir()
            notesctl.init_site(type("Args", (), {"site_root": str(local), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(local)
            commit_initial(local)
            git(root, "init", "--bare", str(bare))
            git(local, "remote", "add", "origin", str(bare))
            git(local, "push", "-u", "origin", "HEAD:main")
            git(root, "clone", "-b", "main", str(bare), str(cloud))
            git(cloud, "config", "user.email", "test@example.com")
            git(cloud, "config", "user.name", "Embedded Notes Test")

            local_note = local / "content" / "embedded" / "本地未提交.md"
            local_note.parent.mkdir(parents=True, exist_ok=True)
            local_note.write_text("local work\n", encoding="utf-8")
            local_plan = local / ".embedded-notes" / "plans" / "local-only.toml"
            local_plan.write_text('id = "local-only"\n', encoding="utf-8")
            remote_note = cloud / "content" / "embedded" / "remote.md"
            remote_note.parent.mkdir(parents=True, exist_ok=True)
            remote_note.write_text("remote work\n", encoding="utf-8")
            git(cloud, "add", ".")
            git(cloud, "commit", "-m", "cloud note")
            git(cloud, "push", "origin", "HEAD:main")

            self.assertEqual(notesctl.main(["sync", "--site-root", str(local)]), 0)
            self.assertFalse(local_note.exists())
            self.assertTrue(remote_note.name and (local / "content" / "embedded" / remote_note.name).is_file())
            backups = list((local / ".embedded-notes" / "backups").iterdir())
            self.assertEqual(len(backups), 1)
            self.assertTrue((backups[0] / "content" / local_note.name).is_file())
            self.assertTrue((backups[0] / "state" / "plans" / local_plan.name).is_file())

    def test_create_pushes_to_configured_remote(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bare = root / "remote.git"
            local = root / "local"
            cloud = root / "cloud"
            local.mkdir()
            notesctl.init_site(type("Args", (), {"site_root": str(local), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(local)
            config_path = local / ".embedded-notes" / "config.toml"
            config = config_path.read_text(encoding="utf-8").replace("require_remote = false", "require_remote = true").replace("auto_push = false", "auto_push = true")
            config_path.write_text(config, encoding="utf-8")
            commit_initial(local)
            git(root, "init", "--bare", str(bare))
            git(local, "remote", "add", "origin", str(bare))
            git(local, "push", "-u", "origin", "HEAD:main")
            request = make_request(root)

            self.assertEqual(notesctl.main(["create", "--site-root", str(local), "--request", str(request)]), 0)
            git(root, "clone", "-b", "main", str(bare), str(cloud))
            self.assertEqual(len(list((cloud / "content" / "embedded").glob("*.md"))), 1)

    def test_same_request_resumes_failed_push_without_duplicate_note(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bare = root / "remote.git"
            local = root / "local"
            cloud = root / "cloud"
            local.mkdir()
            notesctl.init_site(type("Args", (), {"site_root": str(local), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(local)
            config_path = local / ".embedded-notes" / "config.toml"
            config = config_path.read_text(encoding="utf-8").replace("require_remote = false", "require_remote = true").replace("auto_push = false", "auto_push = true")
            config_path.write_text(config, encoding="utf-8")
            commit_initial(local)
            git(root, "init", "--bare", str(bare))
            git(local, "remote", "add", "origin", str(bare))
            git(local, "push", "-u", "origin", "HEAD:main")
            request = make_request(root)
            original_git = notesctl.git
            failed = False

            def fail_first_push(site_root: Path, args: list[str], *, check: bool = True):
                nonlocal failed
                if args and args[0] == "push" and not failed:
                    failed = True
                    raise notesctl.NotesError("simulated push failure")
                return original_git(site_root, args, check=check)

            with mock.patch.object(notesctl, "git", side_effect=fail_first_push):
                self.assertEqual(notesctl.main(["create", "--site-root", str(local), "--request", str(request)]), 2)

            self.assertEqual(len(list((local / ".embedded-notes" / "transactions").glob("*.json"))), 1)
            self.assertEqual(notesctl.main(["create", "--site-root", str(local), "--request", str(request)]), 0)
            git(root, "clone", "-b", "main", str(bare), str(cloud))
            self.assertEqual(len(list((cloud / "content" / "embedded").glob("*.md"))), 1)
            self.assertEqual(list((local / ".embedded-notes" / "transactions").glob("*.json")), [])

    def test_successful_publish_uses_argument_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded", "remote": None, "branch": None})())
            configure_site(site)
            config_path = site / ".embedded-notes" / "config.toml"
            config = config_path.read_text(encoding="utf-8")
            marker = site / "published.marker"
            config = config.replace(
                "[publish]\nenabled = false\ncommand = []",
                "[publish]\nenabled = true\ncommand = [\"python\", \"-c\", \"from pathlib import Path; Path(r'{site_root}/published.marker').write_text('ok')\"]",
            )
            config_path.write_text(config, encoding="utf-8")
            commit_initial(site)
            request = make_request(root)
            request_data = json.loads(request.read_text(encoding="utf-8"))
            request_data["publish"] = True
            request.write_text(json.dumps(request_data), encoding="utf-8")

            self.assertEqual(notesctl.main(["create", "--site-root", str(site), "--request", str(request)]), 0)
            self.assertEqual(marker.read_text(encoding="utf-8"), "ok")

    def test_supported_hugo_front_matter_formats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for format_name, delimiter in (("yaml", "---"), ("toml", "+++"), ("json", ";;;")):
                with self.subTest(format=format_name):
                    site = root / f"site-{format_name}"
                    notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded", "remote": None, "branch": None})())
                    configure_site(site)
                    config_path = site / ".embedded-notes" / "config.toml"
                    config = config_path.read_text(encoding="utf-8").replace('front_matter = "yaml"', f'front_matter = "{format_name}"')
                    config_path.write_text(config, encoding="utf-8")
                    commit_initial(site)
                    request = make_request(root / format_name)
                    self.assertEqual(notesctl.main(["create", "--site-root", str(site), "--request", str(request)]), 0)
                    note = next((site / "content" / "embedded").glob("*.md"))
                    self.assertTrue(note.read_text(encoding="utf-8").startswith(delimiter + "\n"))
                    self.assertEqual(notesctl.main(["validate", "--site-root", str(site), "--path", str(note)]), 0)

    def test_source_content_is_not_copied_into_front_matter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for format_name in ("yaml", "toml", "json"):
                with self.subTest(format=format_name):
                    site = root / f"site-{format_name}"
                    notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded", "remote": None, "branch": None})())
                    configure_site(site)
                    config_path = site / ".embedded-notes" / "config.toml"
                    config = config_path.read_text(encoding="utf-8").replace('front_matter = "yaml"', f'front_matter = "{format_name}"')
                    config_path.write_text(config, encoding="utf-8")
                    commit_initial(site)
                    request = make_request(root / format_name)
                    request_data = json.loads(request.read_text(encoding="utf-8"))
                    request_data["sources"] = [{
                        "type": "url",
                        "url": "https://example.com/dma",
                        "sha256": "abc123",
                        "content": "SOURCE-FULL-TEXT-MUST-NOT-LEAK",
                    }]
                    request.write_text(json.dumps(request_data), encoding="utf-8")

                    result = notesctl.dispatch(
                        notesctl.parser().parse_args(["create", "--site-root", str(site), "--request", str(request)])
                    )
                    note = site / result["notes"][0]["path"]
                    rendered = note.read_text(encoding="utf-8")
                    self.assertNotIn("SOURCE-FULL-TEXT-MUST-NOT-LEAK", rendered)
                    self.assertIn("abc123", rendered)

    def test_existing_hugo_article_fields_are_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            notesctl.init_site(type("Args", (), {"site_root": str(site), "content_dir": "content/embedded/embedded-study", "remote": None, "branch": None})())
            configure_site(site)
            config_path = site / ".embedded-notes" / "config.toml"
            config = config_path.read_text(encoding="utf-8")
            config = config.replace('default_tags = ["embedded"]', 'default_tags = ["嵌入式", "EmbeddedStudy"]')
            config = config.replace("default_categories = []", 'default_categories = ["嵌入式"]')
            config = config.replace("default_series = []", 'default_series = ["EmbeddedStudy"]')
            config_path.write_text(config, encoding="utf-8")
            commit_initial(site)
            request = make_request(root)
            draft_path = root / "drafts" / "draft-0.json"
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft.update({"summary": "DMA 学习笔记", "series_order": 1, "featureimage": ""})
            draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")

            self.assertEqual(notesctl.main(["create", "--site-root", str(site), "--request", str(request)]), 0)
            note = next((site / "content" / "embedded" / "embedded-study").glob("*.md"))
            content = note.read_text(encoding="utf-8")
            self.assertIn("lastmod:", content)
            self.assertIn('featureimage: ""', content)
            self.assertIn('summary: "DMA 学习笔记"', content)
            self.assertIn('  - "嵌入式"', content)
            self.assertIn('series: ["EmbeddedStudy"]', content)
            self.assertIn("series_order: 1", content)


if __name__ == "__main__":
    unittest.main()
