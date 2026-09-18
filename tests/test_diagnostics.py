import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.Logger("weather-test")
        self.logger.propagate = False
        patcher = patch.object(main, "LOGGER", self.logger)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_file_logging_is_utf8_rotating_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(main, "SETTINGS_PATH", Path(directory) / "weather_settings.json"):
                try:
                    self.assertTrue(main.configure_error_logging())
                    self.assertTrue(main.configure_error_logging())
                    self.assertEqual(len(self.logger.handlers), 1)
                    handler = self.logger.handlers[0]
                    self.assertEqual(handler.maxBytes, 512 * 1024)
                    self.assertEqual(handler.backupCount, 1)
                    handler.maxBytes = 128
                    for _ in range(8):
                        self.logger.error("Unexpected error: \u00e4\u00f6" * 2)
                    handler.flush()
                    self.assertTrue((Path(directory) / "weather-report.log.1").is_file())
                    self.assertEqual(len(list(Path(directory).iterdir())), 2)
                    self.assertIn("\u00e4\u00f6", (Path(directory) / "weather-report.log").read_text(encoding="utf-8"))
                finally:
                    for handler in self.logger.handlers:
                        handler.close()

    def test_unwritable_log_does_not_prevent_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(main, "SETTINGS_PATH", Path(directory) / "weather_settings.json"),
                patch.object(main, "RotatingFileHandler", side_effect=PermissionError("read only")),
            ):
                self.assertFalse(main.configure_error_logging())
        self.assertFalse(self.logger.handlers)

    def test_windowless_ui_callback_keeps_its_traceback(self):
        widget = object.__new__(main.WeatherWidget)
        try:
            raise ValueError("diagnostic marker")
        except ValueError:
            error = sys.exc_info()
        with patch.object(main.sys, "stderr", None), self.assertLogs(self.logger, level="ERROR") as captured:
            widget.report_callback_exception(*error)
        self.assertIn("diagnostic marker", captured.output[0])
        self.assertIs(captured.records[0].exc_info[2], error[2])
