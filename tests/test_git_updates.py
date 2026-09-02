import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


@unittest.skipUnless(shutil.which("git"), "Git is required")
class GitUpdateIntegrationTests(unittest.TestCase):
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
