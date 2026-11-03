import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt", "Windows Authenticode signing pipeline")
class WindowsSigningTests(unittest.TestCase):
    def _run_signing_tests(self, powershell: str) -> None:
        # Keep real signing credentials and edition-specific modules out of fixtures.
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("WEATHERREPORT_SIGNING_")
            and key.upper() not in {"WEATHERREPORT_TIMESTAMP_URL", "PSMODULEPATH"}
        }
        with tempfile.TemporaryDirectory(prefix="WeatherReport-signing-") as directory:
            environment["TEMP"] = directory
            environment["TMP"] = directory
            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(Path(__file__).with_suffix(".ps1")),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=environment,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_signing_pipeline_on_windows_powershell(self) -> None:
        powershell = shutil.which("powershell")
        self.assertIsNotNone(powershell, "Windows PowerShell is required")
        self._run_signing_tests(powershell)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is not installed")
    def test_signing_pipeline_on_powershell_seven(self) -> None:
        self._run_signing_tests(shutil.which("pwsh"))
