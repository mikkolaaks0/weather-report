import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import main


@unittest.skipUnless(shutil.which("git"), "Git is required")
class GitUpdateIntegrationTests(unittest.TestCase):
    @staticmethod
    def git(directory: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(directory), "-c", "user.name=Test",
             "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
             "-c", f"core.hooksPath={directory / 'no-hooks'}", *map(str, args)],
            capture_output=True, text=True, check=True, timeout=30,
            **main._hidden_subprocess_kwargs(),
        ).stdout.strip()

    def remote_checkout(self, root: Path) -> tuple[Path, Path, Path]:
        remote, author, checkout = (root / name for name in ("origin.git", "author", "app"))
        self.git(root, "init", "--bare", "--initial-branch=main", remote)
        self.git(root, "init", "-b", "main", author)
        (author / "main.py").write_text("VERSION = 1\n", encoding="utf-8")
        self.git(author, "add", "main.py")
        self.git(author, "commit", "-m", "Initial version")
        self.git(author, "remote", "add", "origin", remote)
        self.git(author, "push", "origin", "main")
        self.git(root, "clone", "-b", "main", remote, checkout)
        return remote, author, checkout

    def init_repository(self, path: Path) -> None:
        subprocess.run(
            ["git", "init", "-b", "main", str(path)],
            capture_output=True, check=True, timeout=30, **main._hidden_subprocess_kwargs(),
        )

    def test_source_version_identifies_the_checkout_even_with_local_edits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            self.init_repository(checkout)
            timestamp = "2026-11-18T10:30:00+00:00"
            with patch.dict(os.environ, {"GIT_COMMITTER_DATE": timestamp, "GIT_AUTHOR_DATE": timestamp}):
                self.git(checkout, "commit", "--allow-empty", "-m", "Source revision")
            revision = self.git(checkout, "rev-parse", "HEAD")
            (checkout / "local-notes.txt").write_text("local work", encoding="utf-8")
            date = datetime.fromisoformat(timestamp).astimezone().strftime("%d.%m.%Y")

            with patch.object(main, "PROJECT_DIR", checkout), patch.object(main, "IS_FROZEN", False):
                version = main._read_source_version()
                self.assertEqual(version.commit, revision)
                self.assertEqual(str(version), f"{date} · {revision[:7]}")

    def test_update_already_on_disk_can_restart_offline_with_local_edits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _remote, _author, checkout = self.remote_checkout(Path(directory))
            with patch.object(main, "PROJECT_DIR", checkout), patch.object(main, "IS_FROZEN", False):
                start_version = main._read_source_version()
                start_signature = main._runtime_file_signature()
                (checkout / "main.py").write_text("VERSION = 2\n", encoding="utf-8")
                self.git(checkout, "commit", "-am", "Update applied outside the app")
                notes = checkout / "notes.txt"
                notes.write_text("Keep me", encoding="utf-8")

                with (
                    patch.object(main, "RUNTIME_FILE_SIGNATURE_AT_START", start_signature),
                    patch.object(main, "_fetch_update_branch", side_effect=OSError("Offline")) as fetch,
                ):
                    status = main.check_github_update_status(start_version.commit)

                self.assertEqual(status["state"], "restart_available")
                fetch.assert_not_called()
                self.assertEqual(notes.read_text(encoding="utf-8"), "Keep me")
                with self.assertRaises(RuntimeError):
                    main.apply_github_update()

    def test_git_operations_ignore_an_inherited_foreign_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app, other = root / "app", root / "other"
            self.init_repository(app)
            self.init_repository(other)
            contexts = (
                {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)},
                {"GIT_COMMON_DIR": str(other / ".git"), "GIT_INDEX_FILE": str(other / ".git" / "index")},
                {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.worktree", "GIT_CONFIG_VALUE_0": str(other)},
            )
            for context in contexts:
                with (
                    self.subTest(variables=tuple(context)),
                    patch.object(main, "PROJECT_DIR", app),
                    patch.dict(os.environ, context),
                ):
                    actual = Path(main._git_output(["rev-parse", "--show-toplevel"]))
                    common = app / main._git_output(["rev-parse", "--git-common-dir"])
                    index = app / main._git_output(["rev-parse", "--git-path", "index"])
                    # Windows temp paths may use 8.3 aliases that Git expands.
                    self.assertEqual(actual.resolve(), app.resolve())
                    self.assertEqual(common.resolve(), (app / ".git").resolve())
                    self.assertEqual(index.resolve(), (app / ".git" / "index").resolve())

    def test_git_output_preserves_international_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repository(root)
            filename = "Espoo-\u00e4-\u6771\u4eac.txt"
            (root / filename).write_text("local notes", encoding="utf-8")
            with patch.object(main, "PROJECT_DIR", root):
                status = main._git_output(["-c", "core.quotepath=false", "status", "--porcelain"])
            self.assertIn(filename, status)

    def test_hidden_untracked_files_still_block_automatic_updates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repository(root)
            (root / "notes.txt").write_text("Keep my notes", encoding="utf-8")
            with patch.object(main, "PROJECT_DIR", root), patch.object(main, "IS_FROZEN", False):
                main._git_output(["config", "status.showUntrackedFiles", "no"])
                self.assertEqual(main.check_github_update_status()["state"], "dirty")
                with self.assertRaisesRegex(RuntimeError, "Paikallisia muutoksia"):
                    main.apply_github_update()
            self.assertEqual((root / "notes.txt").read_text(encoding="utf-8"), "Keep my notes")

    def test_supported_virtualenv_is_not_treated_as_a_source_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repository(root)
            shutil.copyfile(main.PROJECT_DIR / ".gitignore", root / ".gitignore")
            with patch.object(main, "PROJECT_DIR", root):
                result = main._run_git_command(["check-ignore", "--quiet", ".venv/Scripts/pythonw.exe"])
            self.assertEqual(result.returncode, 0, "The supported virtualenv would block automatic updates")

    def test_fallback_error_logs_do_not_block_source_updates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.init_repository(root)
            shutil.copyfile(main.PROJECT_DIR / ".gitignore", root / ".gitignore")
            with patch.object(main, "PROJECT_DIR", root):
                for name in ("weather-report.log", "weather-report.log.1"):
                    self.assertEqual(main._run_git_command(["check-ignore", "--quiet", name]).returncode, 0)
                self.assertEqual(main._run_git_command(["check-ignore", "--quiet", "notes.txt"]).returncode, 1)

    def test_update_check_refreshes_main_with_a_custom_fetch_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _remote, author, checkout = self.remote_checkout(root)
            self.git(checkout, "config", "remote.origin.fetch", "+refs/heads/feature:refs/remotes/origin/feature")
            original = self.git(checkout, "rev-parse", "HEAD")
            (author / "main.py").write_text("VERSION = 2\n", encoding="utf-8")
            self.git(author, "commit", "-am", "New version")
            self.git(author, "push", "origin", "main")
            expected = self.git(author, "rev-parse", "HEAD")
            with patch.object(main, "PROJECT_DIR", checkout), patch.object(main, "IS_FROZEN", False):
                with patch.object(main, "RUNTIME_FILE_SIGNATURE_AT_START", main._runtime_file_signature()):
                    status = main.check_github_update_status()
            self.assertEqual(status["state"], "available")
            self.assertEqual(status["remote"], expected)
            self.assertEqual(self.git(checkout, "rev-parse", "HEAD"), original)

    def test_update_check_detects_remote_rewrites_without_changing_local_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote, author, checkout = self.remote_checkout(root)
            self.git(checkout, "config", "remote.origin.fetch", "+refs/heads/feature:refs/remotes/origin/feature")
            original = self.git(checkout, "rev-parse", "HEAD")
            self.git(author, "switch", "--orphan", "rewritten")
            (author / "main.py").write_text("VERSION = 'rewritten'\n", encoding="utf-8")
            self.git(author, "add", "main.py")
            self.git(author, "commit", "-m", "Unrelated history")
            self.git(author, "push", "origin", "rewritten")
            rewritten = self.git(author, "rev-parse", "HEAD")
            self.git(remote, "update-ref", "refs/heads/main", rewritten)
            with patch.object(main, "PROJECT_DIR", checkout), patch.object(main, "IS_FROZEN", False):
                with patch.object(main, "RUNTIME_FILE_SIGNATURE_AT_START", main._runtime_file_signature()):
                    self.assertEqual(main.check_github_update_status()["state"], "diverged")
                    with self.assertRaises(RuntimeError):
                        main.apply_github_update()
            self.assertEqual(self.git(checkout, "rev-parse", "HEAD"), original)
            self.assertEqual((checkout / "main.py").read_text(encoding="utf-8"), "VERSION = 1\n")

    def test_update_preserves_an_ignored_file_that_the_new_version_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _remote, author, checkout = self.remote_checkout(Path(directory))
            original = self.git(checkout, "rev-parse", "HEAD")
            local_file = checkout / "local-settings.txt"
            (checkout / ".git" / "info" / "exclude").write_text("local-settings.txt\n", encoding="utf-8")
            local_file.write_text("personal settings\n", encoding="utf-8")
            (author / local_file.name).write_text("new defaults\n", encoding="utf-8")
            self.git(author, "add", local_file.name)
            self.git(author, "commit", "-m", "Track default settings")
            self.git(author, "push", "origin", "main")

            with patch.object(main, "PROJECT_DIR", checkout):
                self.assertEqual(self.git(checkout, "status", "--porcelain"), "")
                with self.assertRaises(RuntimeError):
                    main.apply_github_update()

            self.assertEqual(local_file.read_text(encoding="utf-8"), "personal settings\n")
            self.assertEqual(self.git(checkout, "rev-parse", "HEAD"), original)

    def test_update_stops_if_the_user_switches_branches_during_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _remote, author, checkout = self.remote_checkout(Path(directory))
            original = self.git(checkout, "rev-parse", "HEAD")
            (author / "main.py").write_text("VERSION = 2\n", encoding="utf-8")
            self.git(author, "commit", "-am", "New version")
            self.git(author, "push", "origin", "main")
            fetch = main._fetch_update_branch

            def fetch_and_switch_branch(timeout):
                fetch(timeout=timeout)
                self.git(checkout, "switch", "-c", "feature")

            with (
                patch.object(main, "PROJECT_DIR", checkout),
                patch.object(main, "_fetch_update_branch", side_effect=fetch_and_switch_branch),
                self.assertRaisesRegex(RuntimeError, "feature"),
            ):
                main.apply_github_update()

            self.assertEqual(self.git(checkout, "branch", "--show-current"), "feature")
            self.assertEqual(self.git(checkout, "rev-parse", "HEAD"), original)

    def test_update_check_uses_the_tracking_ref_when_a_local_branch_has_the_same_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _remote, author, checkout = self.remote_checkout(Path(directory))
            self.git(checkout, "branch", "origin/main")
            (author / "main.py").write_text("VERSION = 2\n", encoding="utf-8")
            self.git(author, "commit", "-am", "New version")
            self.git(author, "push", "origin", "main")
            expected = self.git(author, "rev-parse", "HEAD")

            with (
                patch.object(main, "PROJECT_DIR", checkout),
                patch.object(main, "IS_FROZEN", False),
                patch.object(main, "RUNTIME_FILE_SIGNATURE_AT_START", None),
                patch.object(main, "_runtime_file_signature", return_value=None),
            ):
                status = main.check_github_update_status()
            self.assertEqual(status["state"], "available")
            self.assertEqual(status["remote"], expected)

    def test_local_remote_update_restart_and_conflict_safety(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            remote = root / "origin.git"
            author = root / "author"
            checkout = root / "app"

            git = self.git

            git(root, "init", "--bare", str(remote))
            git(root, "init", "-b", "main", str(author))
            (author / "main.py").write_text("VERSION = 1\n", encoding="utf-8")
            git(author, "add", "main.py")
            git(author, "commit", "-m", "Initial version")
            git(author, "remote", "add", "origin", str(remote))
            git(author, "push", "origin", "main")
            git(root, "clone", "-b", "main", str(remote), str(checkout))

            with patch.object(main, "PROJECT_DIR", checkout), patch.object(main, "IS_FROZEN", False):
                with patch.object(main, "RUNTIME_FILE_SIGNATURE_AT_START", main._runtime_file_signature()):
                    self.assertEqual(main.check_github_update_status()["state"], "current")
                    (author / "main.py").write_text("VERSION = 2\n", encoding="utf-8")
                    git(author, "commit", "-am", "New version")
                    git(author, "push", "origin", "main")
                    self.assertEqual(main.check_github_update_status()["state"], "available")
                    main.apply_github_update()
                    self.assertEqual(git(checkout, "rev-parse", "HEAD"), git(author, "rev-parse", "HEAD"))
                    self.assertEqual(main.check_github_update_status()["state"], "restart_available")

                with patch.object(main, "RUNTIME_FILE_SIGNATURE_AT_START", main._runtime_file_signature()):
                    running_commit = self.git(checkout, "rev-parse", "HEAD")
                    self.assertEqual(main.check_github_update_status()["state"], "current")
                    (checkout / "main.py").write_text("LOCAL_CHANGE = True\n", encoding="utf-8")
                    self.assertEqual(main.check_github_update_status(running_commit)["state"], "current")
                    with self.assertRaises(RuntimeError):
                        main.apply_github_update()
                    self.assertEqual((checkout / "main.py").read_text(encoding="utf-8"), "LOCAL_CHANGE = True\n")

                (author / "main.py").write_text("VERSION = 3\n", encoding="utf-8")
                git(author, "commit", "-am", "Conflicting upstream change")
                git(author, "push", "origin", "main")
                self.assertEqual(main.check_github_update_status()["state"], "dirty")
                self.assertEqual((checkout / "main.py").read_text(encoding="utf-8"), "LOCAL_CHANGE = True\n")
                git(checkout, "commit", "-am", "Local change")
                with patch.object(main, "RUNTIME_FILE_SIGNATURE_AT_START", main._runtime_file_signature()):
                    self.assertEqual(main.check_github_update_status()["state"], "diverged")
                    before = git(checkout, "rev-parse", "HEAD")
                    with self.assertRaises(RuntimeError):
                        main.apply_github_update()
                    self.assertEqual(git(checkout, "rev-parse", "HEAD"), before)
                    git(checkout, "switch", "-c", "feature")
                    self.assertEqual(main.check_github_update_status()["state"], "unsupported")
