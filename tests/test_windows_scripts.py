import os
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "Windows shortcut and installer tests")
class WindowsScriptTests(unittest.TestCase):
    def test_installer_and_release_safety(self) -> None:
        powershell = shutil.which("powershell")
        self.assertIsNotNone(powershell, "Windows PowerShell is required")
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(Path(__file__).with_name("test_scripts.ps1"))],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
