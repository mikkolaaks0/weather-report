import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from ctypes import wintypes

import main


@unittest.skipUnless(os.name == "nt", "Windows source launchers")
class SourceLauncherTests(unittest.TestCase):
    def wait_for_test_process(self, pid: int) -> None:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only; never terminate a process.
        if not handle:
            self.assertEqual(ctypes.get_last_error(), 87, "Could not inspect test process")
            return  # The short test program has already exited.
        try:
            self.assertEqual(kernel.WaitForSingleObject(handle, 10000), 0, "Test program did not exit")
        finally:
            kernel.CloseHandle(handle)

    def launcher_directory(self, root: Path) -> dict:
        for name in ("start_weather_app.bat", "start_weather_app.vbs"):
            shutil.copyfile(main.PROJECT_DIR / name, root / name)
        # Keep all user-installed Python interpreters out of discovery.
        return {**os.environ, "PATH": str(Path(os.environ["SystemRoot"]) / "System32"),
                "LOCALAPPDATA": str(root / "empty-appdata")}

    def create_virtualenv(self, root: Path) -> None:
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(root / ".venv")],
            check=True, capture_output=True, timeout=30, **main._hidden_subprocess_kwargs(),
        )

    def test_project_virtualenv_is_used_without_system_python(self) -> None:
        with tempfile.TemporaryDirectory(prefix="WeatherReportLaunch-") as directory:
            root = Path(directory)
            env = self.launcher_directory(root)
            self.create_virtualenv(root)
            marker = root / "launched.json"
            (root / "main.py").write_text(
                "import json, os, sys\nfrom pathlib import Path\n"
                "Path('launched.tmp').write_text(json.dumps({'exe': sys.executable, 'pid': os.getpid()}), encoding='utf-8')\n"
                "Path('launched.tmp').replace('launched.json')\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [str(Path(os.environ["SystemRoot"]) / "System32" / "cscript.exe"),
                 "//Nologo", str(root / "start_weather_app.vbs")],
                cwd=root, env=env, capture_output=True, timeout=15,
                **main._hidden_subprocess_kwargs(),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            deadline = time.monotonic() + 10
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(marker.is_file(), "Source launcher did not run the project interpreter")
            launched = json.loads(marker.read_text(encoding="utf-8"))
            self.wait_for_test_process(launched["pid"])
            self.assertEqual(Path(launched["exe"]), root / ".venv" / "Scripts" / "pythonw.exe")

    def test_negative_probe_exit_code_does_not_launch_an_unusable_interpreter(self) -> None:
        with tempfile.TemporaryDirectory(prefix="WeatherReportLaunch-") as directory:
            root = Path(directory)
            env = self.launcher_directory(root)
            self.create_virtualenv(root)
            (root / "tkinter.py").write_text("raise SystemExit(-1)\n", encoding="utf-8")
            (root / "main.py").write_text(
                "from pathlib import Path\nPath('should-not-run').touch()\n", encoding="utf-8",
            )
            result = subprocess.run(
                [os.environ["COMSPEC"], "/d", "/c", str(root / "start_weather_app.bat")],
                cwd=root, env=env, capture_output=True, timeout=15,
                **main._hidden_subprocess_kwargs(),
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertFalse((root / "should-not-run").exists())

    def test_windowless_launcher_reports_failure_when_no_python_is_available(self) -> None:
        with tempfile.TemporaryDirectory(prefix="WeatherReportLaunch-") as directory:
            root = Path(directory)
            env = self.launcher_directory(root)
            cscript = Path(os.environ["SystemRoot"]) / "System32" / "cscript.exe"
            result = subprocess.run(
                [str(cscript), "//Nologo", str(root / "start_weather_app.vbs")],
                cwd=root, env=env, capture_output=True, timeout=15,
                **main._hidden_subprocess_kwargs(),
            )
            self.assertEqual(result.returncode, 1, "Windowless launcher silently reported success")
            self.assertIn(b"Weather Report could not start", result.stdout + result.stderr)
