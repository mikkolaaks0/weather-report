import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


@unittest.skipUnless(shutil.which("git"), "Git is required")
class GitUpdateIntegrationTests(unittest.TestCase):
    def init_repository(self, path: Path) -> None:
        subprocess.run(
            ["git", "init", "-b", "main", str(path)],
            capture_output=True, check=True, timeout=30, **main._hidden_subprocess_kwargs(),
        )

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

    def test_local_remote_update_restart_and_conflict_safety(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            remote = root / "origin.git"
            author = root / "author"
            checkout = root / "app"

            def git(directory, *args):
                return subprocess.run(
                    ["git", "-C", str(directory), "-c", "user.name=Test",
                     "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
                     "-c", f"core.hooksPath={root / 'no-hooks'}", *args],
                    capture_output=True, text=True, check=True, timeout=30,
                    **main._hidden_subprocess_kwargs(),
                ).stdout.strip()

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
                    self.assertEqual(main.check_github_update_status()["state"], "current")
                    (checkout / "main.py").write_text("LOCAL_CHANGE = True\n", encoding="utf-8")
                    self.assertEqual(main.check_github_update_status()["state"], "dirty")
                    with self.assertRaises(RuntimeError):
                        main.apply_github_update()
                    self.assertEqual((checkout / "main.py").read_text(encoding="utf-8"), "LOCAL_CHANGE = True\n")

                git(checkout, "commit", "-am", "Local change")
                (author / "main.py").write_text("VERSION = 3\n", encoding="utf-8")
                git(author, "commit", "-am", "Conflicting upstream change")
                git(author, "push", "origin", "main")
                with patch.object(main, "RUNTIME_FILE_SIGNATURE_AT_START", main._runtime_file_signature()):
                    self.assertEqual(main.check_github_update_status()["state"], "diverged")
                    before = git(checkout, "rev-parse", "HEAD")
                    with self.assertRaises(RuntimeError):
                        main.apply_github_update()
                    self.assertEqual(git(checkout, "rev-parse", "HEAD"), before)
                    git(checkout, "switch", "-c", "feature")
                    self.assertEqual(main.check_github_update_status()["state"], "unsupported")
