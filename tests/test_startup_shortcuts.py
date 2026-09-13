import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class StartupOwnershipTests(unittest.TestCase):
    def test_frozen_app_only_owns_its_exact_executable_without_extra_arguments(self):
        with patch.object(main, "IS_FROZEN", True), patch.object(main, "APP_EXECUTABLE_PATH", Path(r"C:\Apps\WeatherReport\WeatherReport.exe")):
            for target, arguments, expected in (
                (r"c:\apps\weatherreport\WEATHERREPORT.EXE", "", True),
                (r"C:\Old\WeatherReport\WeatherReport.exe", "", False),
                (r"C:\Apps\WeatherReport\WeatherReport.exe", "--custom", False),
                ("", "", False),
            ):
                with self.subTest(target=target, arguments=arguments):
                    self.assertEqual(main._shortcut_belongs_to_current_installation({"Target": target, "Arguments": arguments}), expected)

    def test_source_repair_recognizes_its_legacy_and_stable_launchers(self):
        project = Path(r"C:\Weather Project")
        with patch.object(main, "IS_FROZEN", False), patch.object(main, "PROJECT_DIR", project):
            for launcher, script in (("pythonw.exe", "main.py"), ("wscript.exe", "start_weather_app.vbs")):
                for quoted in (False, True):
                    path = str(project / script)
                    arguments = f'"{path}"' if quoted else path
                    shortcut = {"Target": rf"C:\Old Python\{launcher}", "Arguments": arguments}
                    self.assertTrue(main._shortcut_belongs_to_current_installation(shortcut))
            self.assertTrue(main._shortcut_belongs_to_current_installation({"Target": str(project / "start_weather_app.vbs"), "Arguments": ""}))
            for target, arguments in (
                (r"C:\Python\pythonw.exe", r'"C:\Other Project\main.py"'),
                (r"C:\Windows\wscript.exe", r'"C:\Weather Project Extra\start_weather_app.vbs"'),
                (r"C:\Python\pythonw.exe", f'"{project / "main.py"}" --custom'),
                (r"C:\Other\unknown.exe", f'"{project / "main.py"}"'),
            ):
                with self.subTest(target=target, arguments=arguments):
                    self.assertFalse(main._shortcut_belongs_to_current_installation({"Target": target, "Arguments": arguments}))

    def test_automatic_repair_leaves_other_installations_and_mixed_links_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ("weather-report.lnk", "Weather Report.lnk")]
            for path in paths:
                path.touch()
            for ownership in ((False,), (True, False), (True, True)):
                with (
                    self.subTest(ownership=ownership),
                    patch.object(main, "get_startup_shortcut_paths", return_value=paths),
                    patch.object(main, "_read_windows_shortcut", return_value={}),
                    patch.object(main, "_shortcut_belongs_to_current_installation", side_effect=ownership),
                    patch.object(main, "set_startup_enabled") as enable,
                ):
                    main.repair_startup_shortcut()
                if all(ownership):
                    enable.assert_called_once_with(True)
                else:
                    enable.assert_not_called()

    def test_disabled_or_unreadable_links_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weather-report.lnk"
            with (
                patch.object(main, "get_startup_shortcut_paths", return_value=[path]),
                patch.object(main, "_read_windows_shortcut", side_effect=OSError("unreadable")) as read,
                patch.object(main, "set_startup_enabled") as enable,
            ):
                main.repair_startup_shortcut()
                read.assert_not_called()
                path.touch()
                with self.assertRaises(OSError):
                    main.repair_startup_shortcut()
                enable.assert_not_called()

    def test_shortcut_reader_rejects_malformed_output(self):
        for output in ("", "null", "[]", '{"Target": 5, "Arguments": ""}', '{"Target": "x"}'):
            with self.subTest(output=output), patch.object(main, "_run_shortcut_script", return_value=output):
                with self.assertRaises(OSError):
                    main._read_windows_shortcut(Path("test.lnk"))

    def test_shortcut_process_timeout_is_a_recoverable_error(self):
        with patch.object(main.shutil, "which", return_value="powershell"), patch.object(main.subprocess, "run", side_effect=subprocess.TimeoutExpired("powershell", 20)):
            with self.assertRaisesRegex(OSError, "aikakatkaistiin"):
                main._run_shortcut_script("")

    @unittest.skipUnless(os.name == "nt", "Windows shortcut integration")
    def test_real_shortcut_reader_preserves_unicode_and_apostrophes(self):
        with tempfile.TemporaryDirectory(prefix="Weather-\u00e4-test-") as directory:
            path = Path(directory) / "Weather Report's test.lnk"
            target = str(main.APP_EXECUTABLE_PATH)
            arguments = '"S\u00e4\u00e4 test\'s.py"'
            with patch.object(main, "_resolve_shortcut_target", return_value=(target, arguments, directory, target)):
                main.create_windows_shortcut(path)
            self.assertEqual(main._read_windows_shortcut(path), {"Target": target, "Arguments": arguments})
