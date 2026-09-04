import ctypes
import io
import json
import queue
import re
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from http.client import IncompleteRead, RemoteDisconnected
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import main


KNOWN_WMO_CODES = (
    0,
    1,
    2,
    3,
    45,
    48,
    51,
    53,
    55,
    56,
    57,
    61,
    63,
    65,
    66,
    67,
    71,
    73,
    75,
    77,
    80,
    81,
    82,
    85,
    86,
    95,
    96,
    99,
)


class WeatherStyleTests(unittest.TestCase):
    def test_tuned_popup_icon_dimensions_remain_stable(self) -> None:
        self.assertEqual((main.HERO_ICON_WIDTH, main.HERO_ICON_HEIGHT), (87, 84))
        self.assertEqual((main.FORECAST_ICON_WIDTH, main.FORECAST_ICON_HEIGHT), (43, 39))

    def test_every_known_wmo_code_has_an_existing_asset(self) -> None:
        for code in KNOWN_WMO_CODES:
            for is_day in (True, False):
                with self.subTest(code=code, is_day=is_day):
                    style = main.resolve_weather_style(code, is_day)
                    self.assertNotEqual(style.icon_key, "unknown")
                    self.assertTrue(main._weather_icon_path(style.icon_key).is_file())

    def test_every_known_wmo_code_renders_from_the_tray_asset_library(self) -> None:
        if main.Image is None:
            self.skipTest("Pillow is not available")

        for code in KNOWN_WMO_CODES:
            for is_day in (True, False):
                with self.subTest(code=code, is_day=is_day):
                    style = main.resolve_weather_style(code, is_day)
                    tray_icon = main.build_tray_symbol_icon(style.icon_key)
                    self.assertIsNotNone(tray_icon)
                    self.assertEqual(tray_icon.size, (64, 64))

    def test_unknown_and_string_codes_are_handled(self) -> None:
        self.assertEqual(main.resolve_weather_style("95", False).icon_key, "thunder-night")
        self.assertEqual(main.resolve_weather_style("invalid").icon_key, "unknown")
        self.assertEqual(main.resolve_weather_style(float("nan")).icon_key, "unknown")
        self.assertEqual(main._normalize_weather_icon_key(" SUN "), "sun")
        self.assertEqual(main._weather_icon_path("not-an-icon").name, "unknown.png")

    def test_weather_and_metric_pngs_have_svg_sources_and_transparency(self) -> None:
        if main.Image is None:
            self.skipTest("Pillow is not available")

        for directory in (main.WEATHER_ICONS_DIR, main.METRIC_ICONS_DIR):
            png_paths = sorted(directory.glob("*.png"))
            svg_stems = {path.stem for path in directory.glob("*.svg")}
            self.assertTrue(png_paths)
            self.assertEqual({path.stem for path in png_paths}, svg_stems)
            for path in png_paths:
                with self.subTest(path=path.name), main.Image.open(path) as image:
                    self.assertIn("A", image.getbands())
                    alpha = image.getchannel("A")
                    alpha_minimum, alpha_maximum = alpha.getextrema()
                    self.assertLess(alpha_minimum, 255)
                    self.assertGreater(alpha_maximum, 0)
                    self.assertIsNotNone(alpha.getbbox())

    def test_corrupt_weather_icon_uses_cloud_fallback(self) -> None:
        if main.Image is None:
            self.skipTest("Pillow is not available")

        with tempfile.TemporaryDirectory() as temporary_dir:
            icon_dir = Path(temporary_dir)
            (icon_dir / "rain.png").write_bytes(b"not a png")
            fallback = main.Image.new("RGBA", (3, 2), (10, 20, 30, 255))
            fallback.save(icon_dir / "cloud.png")

            with patch.object(main, "WEATHER_ICONS_DIR", icon_dir):
                loaded = main._load_weather_icon_image("rain")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.size, (3, 2))
            self.assertEqual(loaded.getpixel((0, 0)), (10, 20, 30, 255))


class DataFormattingTests(unittest.TestCase):
    def test_numeric_formatters_reject_non_finite_and_invalid_values(self) -> None:
        degree = "\N{DEGREE SIGN}"
        self.assertEqual(main.format_temperature("18.6", "C"), f"19{degree}C")
        self.assertEqual(main.format_temperature(float("nan"), "C"), f"-{degree}C")
        self.assertEqual(main.format_metric("4.25", " mm", decimals=1), "4.2 mm")
        self.assertEqual(main.format_metric(True, "%"), "-")
        self.assertEqual(main.format_wind_direction("360"), "pohjoinen")
        self.assertEqual(main.format_wind_direction(float("inf")), "-")
        self.assertEqual(main.format_metric(10 ** 400, "%"), "-")
        self.assertEqual(main.resolve_weather_style(10 ** 400).icon_key, "unknown")

    def test_open_meteo_time_parser_accepts_seconds_and_timezone(self) -> None:
        self.assertEqual(
            main.format_time_short("2026-06-02T10:29:15+03:00"),
            "10:29",
        )
        self.assertEqual(main.format_time_short("not-a-time"), "-")
        self.assertIsNone(main._parse_open_meteo_time(None))

    def test_precipitation_window_filters_invalid_and_out_of_range_values(self) -> None:
        weather = {
            "current": {"time": "2026-06-02T10:15"},
            "hourly": {
                "time": [
                    "2026-06-02T10:00",
                    "2026-06-02T11:00",
                    "2026-06-02T12:00",
                    "2026-06-02T15:00",
                    "2026-06-02T17:00",
                ],
                "precipitation_probability": [99, "28", 101, 72.6, 100],
            },
        }
        self.assertEqual(main.max_precipitation_probability_next_hours(weather), 73)
        self.assertIsNone(main.max_precipitation_probability_next_hours(weather, hours=0))
        self.assertIsNone(main.max_precipitation_probability_next_hours({"current": None}))

    def test_city_formatting_omits_empty_placeholders(self) -> None:
        self.assertEqual(main.format_city({"name": "Espoo", "admin1": "Uusimaa"}), "Espoo, Uusimaa")
        self.assertEqual(main.format_city({"name": "Espoo", "admin1": " "}), "Espoo")
        self.assertEqual(main.format_city(None), "-")


class ServicePayloadTests(unittest.TestCase):
    def test_forecast_dates_reject_invalid_disordered_or_mismatched_days(self) -> None:
        for dates in (
            [None], ["bad-date"], ["2026-02-30"], ["2026-09-04T00:00"],
            ["2026-09-04", "2026-09-04"], ["2026-09-05", "2026-09-04"],
            ["2026-09-04", "2026-09-06"], ["2026-09-03"],
        ):
            weather = {"current": {"weather_code": 3, "temperature_2m": 18, "time": "2026-09-04T00:15"},
                       "daily": {"time": dates}}
            with self.subTest(dates=dates), self.assertRaises(main.WeatherServiceError):
                main.validate_weather_payload(weather)

    def test_forecast_uses_location_date_and_allows_missing_optional_metrics(self) -> None:
        weather = {"current": {"weather_code": 3, "temperature_2m": 18, "time": "2026-09-04T23:30-10:00"},
                   "daily": {"time": ["2026-09-03", "2026-09-04", "2026-09-05"]}}
        main.validate_weather_payload(weather)
        self.assertEqual(main._today_forecast_index(weather), 1)
        for value in (None, "invalid"):
            weather["current"]["time"] = value
            with self.assertRaises(main.WeatherServiceError):
                main.validate_weather_payload(weather)

    def test_json_client_closes_http_errors_without_a_retry_wrapper(self) -> None:
        body = io.BytesIO(b"unavailable")
        error = HTTPError("https://example.invalid", 503, "unavailable", None, body)
        with patch.object(main, "urlopen", side_effect=error):
            with self.assertRaises(HTTPError):
                main._get_json("https://example.invalid", {})
        self.assertTrue(body.closed)

    def test_interrupted_connections_are_retried_with_a_fixed_limit(self) -> None:
        for error in (ConnectionResetError("reset"), RemoteDisconnected("closed"), IncompleteRead(b"partial")):
            with self.subTest(error=type(error).__name__), patch.object(main.time, "sleep") as sleep:
                operation = Mock(side_effect=[error, {"ok": True}])
                self.assertEqual(main._request_with_retry(operation), {"ok": True})
                self.assertEqual(operation.call_count, 2)
                sleep.assert_called_once_with(1.0)

                operation = Mock(side_effect=error)
                with self.assertRaises(type(error)):
                    main._request_with_retry(operation)
                self.assertEqual(operation.call_count, 2)

    def test_http_error_responses_are_closed_before_retry_or_propagation(self) -> None:
        for code in (404, 429, 503):
            with self.subTest(code=code):
                body = io.BytesIO(b"server error")
                error = HTTPError("https://example.invalid", code, "error", None, body)
                operation = Mock(side_effect=[error, {"ok": True}])
                with patch.object(main.time, "sleep", side_effect=lambda _delay: self.assertTrue(body.closed)) as sleep:
                    if code == 404:
                        with self.assertRaises(HTTPError):
                            main._request_with_retry(operation)
                        self.assertEqual(operation.call_count, 1)
                        sleep.assert_not_called()
                    else:
                        self.assertEqual(main._request_with_retry(operation), {"ok": True})
                        sleep.assert_called_once_with(1.0)
                self.assertTrue(body.closed)

    def test_network_retry_retries_only_transient_transport_errors(self) -> None:
        calls = iter((URLError("temporary"), {"ok": True}))

        def operation():
            result = next(calls)
            if isinstance(result, Exception):
                raise result
            return result

        with patch.object(main.time, "sleep") as sleep:
            self.assertEqual(main._request_with_retry(operation), {"ok": True})
        sleep.assert_called_once_with(1.0)

        def invalid_operation():
            raise main.WeatherServiceError("bad payload")

        with patch.object(main.time, "sleep") as sleep:
            with self.assertRaises(main.WeatherServiceError):
                main._request_with_retry(invalid_operation)
        sleep.assert_not_called()

        def not_found_operation():
            raise HTTPError("https://example.invalid", 404, "not found", None, None)

        with patch.object(main.time, "sleep") as sleep:
            with self.assertRaises(HTTPError):
                main._request_with_retry(not_found_operation)
        sleep.assert_not_called()

    def test_json_client_rejects_non_object_payloads_and_sets_headers(self) -> None:
        class Headers:
            @staticmethod
            def get_content_charset():
                return "utf-8"

        class Response:
            headers = Headers()

            def __init__(self, payload: bytes) -> None:
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def read(self, size: int = -1) -> bytes:
                return self.payload if size < 0 else self.payload[:size]

        with patch.object(main, "urlopen", return_value=Response(b'{"ok": true}')) as mocked_open:
            self.assertEqual(main._get_json("https://example.invalid", {"q": "Espoo"}), {"ok": True})
        request = mocked_open.call_args.args[0]
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(request.get_header("User-agent"), f"{main.APP_SLUG}-desktop")

        invalid_payloads = (
            b"[]",
            b'{"broken":',
            b"\xff",
            b'{"nested":' * 10000 + b"null" + b"}" * 10000,
        )
        for payload in invalid_payloads:
            with self.subTest(payload_length=len(payload)):
                with patch.object(main, "urlopen", return_value=Response(payload)):
                    with self.assertRaises(main.WeatherServiceError):
                        main._get_json("https://example.invalid", {})

        with (
            patch.object(main, "MAX_JSON_RESPONSE_BYTES", 8),
            patch.object(main, "urlopen", return_value=Response(b"123456789")),
        ):
            with self.assertRaisesRegex(main.WeatherServiceError, "liian suuri"):
                main._get_json("https://example.invalid", {})

    def test_weather_request_normalizes_unknown_temperature_unit(self) -> None:
        with patch.object(main, "_get_json", return_value={}) as get_json:
            main.get_weather(60.2, 24.7, " KELVIN ")

        self.assertEqual(get_json.call_args.args[1]["temperature_unit"], "celsius")

    def test_geocoding_validates_and_normalizes_coordinates(self) -> None:
        payload = {
            "results": [
                {
                    "name": "Espoo",
                    "latitude": "60.2055",
                    "longitude": "24.6559",
                }
            ]
        }
        with patch.object(main, "_get_json", return_value=payload) as get_json:
            place = main.geocode_city("  Espoo\n Keskus ")
        self.assertEqual(place["latitude"], 60.2055)
        self.assertEqual(place["longitude"], 24.6559)
        self.assertEqual(get_json.call_args.args[1]["name"], "Espoo Keskus")

    def test_geocoding_distinguishes_not_found_from_invalid_payload(self) -> None:
        with patch.object(main, "_get_json", return_value={"results": []}):
            with self.assertRaises(main.CityNotFoundError):
                main.geocode_city("Missing")

        with patch.object(main, "_get_json") as get_json:
            with self.assertRaises(main.CityNotFoundError):
                main.geocode_city("   ")
            with self.assertRaisesRegex(main.WeatherServiceError, "enintään"):
                main.geocode_city("x" * (main.MAX_CITY_QUERY_LENGTH + 1))
        get_json.assert_not_called()

        with patch.object(main, "_get_json", return_value={"results": {}}):
            with self.assertRaises(main.WeatherServiceError):
                main.geocode_city("Broken")

        with patch.object(main, "_get_json", return_value={"results": [{"name": "Broken"}]}):
            with self.assertRaises(main.WeatherServiceError):
                main.geocode_city("Broken")

        invalid_coordinates = {
            "results": [{"name": "Broken", "latitude": 120, "longitude": 24}]
        }
        with patch.object(main, "_get_json", return_value=invalid_coordinates):
            with self.assertRaises(main.WeatherServiceError):
                main.geocode_city("Broken")

    def test_weather_payload_requires_current_conditions_and_daily_forecast(self) -> None:
        valid = {
            "current": {"weather_code": 2, "temperature_2m": 18},
            "daily": {"time": ["2026-06-02"]},
        }
        main.validate_weather_payload(valid)

        invalid_payloads = (
            {},
            {"current": {}},
            {"current": {"weather_code": 2, "temperature_2m": 18}},
            {
                "current": {"weather_code": 2.5, "temperature_2m": 18},
                "daily": {"time": ["2026-06-02"]},
            },
        )
        for invalid in invalid_payloads:
            with self.subTest(payload=invalid), self.assertRaises(main.WeatherServiceError):
                main.validate_weather_payload(invalid)


class SettingsAndShortcutTests(unittest.TestCase):
    def test_settings_directory_uses_local_appdata_as_fallback(self) -> None:
        local_appdata = Path(r"C:\Users\Example\AppData\Local")
        with patch.dict(
            main.os.environ,
            {"APPDATA": "", "LOCALAPPDATA": str(local_appdata)},
        ):
            settings_dir = main._resolve_settings_dir()

        self.assertEqual(settings_dir, local_appdata / main.APP_SLUG)

    def test_settings_are_whitelisted_and_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "weather_settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "city": "  Espoo\n  Keskus  ",
                        "temperature_unit": "KELVIN",
                        "popup_theme": "NOT-A-THEME",
                        "legacy": "ignored",
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(main, "SETTINGS_PATH", settings_path):
                settings = main.load_settings()

            self.assertEqual(
                settings,
                {
                    "city": "Espoo Keskus",
                    "temperature_unit": "celsius",
                    "popup_theme": main.DEFAULT_POPUP_THEME,
                },
            )

    def test_atomic_settings_save_keeps_previous_file_on_serialization_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "weather_settings.json"
            original = {"city": "Espoo", "temperature_unit": "celsius"}
            with patch.object(main, "SETTINGS_PATH", settings_path):
                self.assertIs(main.save_settings(original), True)
                self.assertIs(main.save_settings({"city": object()}), False)

            self.assertEqual(json.loads(settings_path.read_text(encoding="utf-8")), original)
            self.assertEqual(list(settings_path.parent.glob(".*.tmp")), [])

    def test_failed_settings_replacement_preserves_original_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "settings.json"
            with patch.object(main, "SETTINGS_PATH", path):
                self.assertTrue(main.save_settings({"city": "Espoo"}))
                original = path.read_bytes()
                with patch.object(main.os, "replace", side_effect=PermissionError("file locked")):
                    self.assertFalse(main.save_settings({"city": "Helsinki"}))
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(list(path.parent.glob(".*.tmp")), [])
                self.assertTrue(main.save_settings({"city": "Helsinki"}))
                self.assertEqual(main.load_settings()["city"], "Helsinki")

    def test_malformed_settings_do_not_prevent_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "settings.json"
            with patch.object(main, "SETTINGS_PATH", settings_path):
                defaults = main.load_settings()
                for payload in (b"\xff\xfe", b"[]", b"{broken", b"[" * 2000 + b"]" * 2000):
                    with self.subTest(payload=payload):
                        settings_path.write_bytes(payload)
                        self.assertEqual(main.load_settings(), defaults)
                for value in ([], {}, False, 12, None):
                    with self.subTest(value=value):
                        settings_path.write_text(json.dumps({
                            "city": "Helsinki",
                            "temperature_unit": value,
                            "popup_theme": value,
                        }), encoding="utf-8")
                        self.assertEqual(main.load_settings(), {**defaults, "city": "Helsinki"})

    def test_desktop_shortcut_uses_redirected_windows_desktop(self) -> None:
        class RegistryKey:
            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

        class FakeWinreg:
            HKEY_CURRENT_USER = object()

            @staticmethod
            def OpenKey(_root, _path):
                return RegistryKey()

            @staticmethod
            def QueryValueEx(_key, _name):
                return (r"%USERPROFILE%\OneDrive\Desktop", 2)

        userprofile = Path(r"C:\Users\Example")
        with (
            patch.dict(main.sys.modules, {"winreg": FakeWinreg}),
            patch.dict(main.os.environ, {"USERPROFILE": str(userprofile)}),
        ):
            shortcut_path = main.get_desktop_shortcut_path()

        self.assertEqual(shortcut_path, userprofile / "OneDrive" / "Desktop" / main.DESKTOP_SHORTCUT_NAME)

    def test_source_shortcut_uses_stable_windowless_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_dir = Path(temporary_dir) / "Weather Report"
            project_dir.mkdir()
            launcher_path = project_dir / "start_weather_app.vbs"
            launcher_path.touch()
            wscript_path = Path(r"C:\Windows\System32\wscript.exe")
            with (
                patch.object(main, "IS_FROZEN", False),
                patch.object(main, "PROJECT_DIR", project_dir),
                patch.object(main, "_resolve_wscript_executable", return_value=wscript_path),
                patch.object(main, "_resolve_pythonw_executable") as resolve_pythonw,
            ):
                target, arguments, working_dir, _icon = main._resolve_shortcut_target()

        self.assertEqual(target, str(wscript_path))
        self.assertEqual(arguments, subprocess.list2cmdline([str(launcher_path.resolve())]))
        self.assertEqual(working_dir, str(project_dir))
        resolve_pythonw.assert_not_called()

    def test_source_shortcut_falls_back_to_quoted_main_script_path(self) -> None:
        project_dir = Path(r"C:\Users\Example User\Weather Report")
        pythonw_path = Path(r"C:\Python\pythonw.exe")
        expected_script = str((project_dir / "main.py").resolve())
        with (
            patch.object(main, "IS_FROZEN", False),
            patch.object(main, "PROJECT_DIR", project_dir),
            patch.object(main, "_resolve_pythonw_executable", return_value=pythonw_path),
        ):
            target, arguments, working_dir, _icon = main._resolve_shortcut_target()

        self.assertEqual(target, str(pythonw_path))
        self.assertEqual(arguments, subprocess.list2cmdline([expected_script]))
        self.assertEqual(working_dir, str(project_dir))

    def test_pythonw_fallback_rejects_unsupported_interpreters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            old_pythonw = root / "Programs" / "Python" / "Python39" / "pythonw.exe"
            current_pythonw = root / "Programs" / "Python" / "Python312" / "pythonw.exe"
            old_pythonw.parent.mkdir(parents=True)
            current_pythonw.parent.mkdir(parents=True)
            old_pythonw.touch()
            current_pythonw.touch()

            with (
                patch.object(main.sys, "executable", str(root / "runtime" / "python.exe")),
                patch.object(main.shutil, "which", return_value=None),
                patch.dict(main.os.environ, {"LOCALAPPDATA": str(root)}),
                patch.object(
                    main,
                    "_is_supported_pythonw",
                    side_effect=lambda path: path == current_pythonw,
                ) as is_supported,
            ):
                resolved = main._resolve_pythonw_executable()

            self.assertEqual(resolved, current_pythonw)
            is_supported.assert_called_once_with(current_pythonw)

    def test_pythonw_probe_handles_success_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            pythonw = Path(temporary_dir) / "pythonw.exe"
            pythonw.touch()
            supported = subprocess.CompletedProcess([], 0)
            with patch.object(main.subprocess, "run", return_value=supported):
                self.assertTrue(main._is_supported_pythonw(pythonw))

            timeout = subprocess.TimeoutExpired([str(pythonw)], 5)
            with patch.object(main.subprocess, "run", side_effect=timeout):
                self.assertFalse(main._is_supported_pythonw(pythonw))

    def test_shortcut_creation_uses_noninteractive_powershell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            shortcut_path = Path(temporary_dir) / "Weather Report.lnk"
            with (
                patch.object(main.shutil, "which", return_value=r"C:\Windows\powershell.exe"),
                patch.object(
                    main,
                    "_resolve_shortcut_target",
                    return_value=("target.exe", "", temporary_dir, "target.exe"),
                ),
                patch.object(main.subprocess, "run", side_effect=lambda *_args, **_kwargs: shortcut_path.touch()) as run,
            ):
                main._write_windows_shortcut(shortcut_path)

        self.assertIn("-NonInteractive", run.call_args.args[0])

    def test_shortcut_creation_rejects_missing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            shortcut_path = Path(temporary_dir) / "Weather Report.lnk"
            with (
                patch.object(main.shutil, "which", return_value="powershell.exe"),
                patch.object(main, "_resolve_shortcut_target", return_value=("target.exe", "", temporary_dir, "target.exe")),
                patch.object(main.subprocess, "run"),
            ):
                with self.assertRaises(OSError):
                    main.create_windows_shortcut(shortcut_path)

    def test_shortcut_replacement_is_atomic_and_cleans_up_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shortcut = Path(directory) / "Weather Report.lnk"
            shortcut.write_bytes(b"old shortcut")

            def write_new(staged):
                self.assertNotEqual(staged, shortcut)
                self.assertEqual(staged.parent.parent, shortcut.parent)
                self.assertEqual(shortcut.read_bytes(), b"old shortcut")
                staged.write_bytes(b"new shortcut")

            with patch.object(main, "_write_windows_shortcut", side_effect=write_new):
                main.create_windows_shortcut(shortcut)
            self.assertEqual(shortcut.read_bytes(), b"new shortcut")
            self.assertEqual(list(Path(directory).iterdir()), [shortcut])

    def test_failed_shortcut_write_or_replacement_preserves_old_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shortcut = Path(directory) / "Weather Report.lnk"
            shortcut.write_bytes(b"old shortcut")

            def incomplete_write(staged):
                staged.write_bytes(b"partial")
                raise OSError("write interrupted")

            with patch.object(main, "_write_windows_shortcut", side_effect=incomplete_write):
                with self.assertRaises(OSError):
                    main.create_windows_shortcut(shortcut)
            self.assertEqual(shortcut.read_bytes(), b"old shortcut")
            self.assertEqual(list(Path(directory).iterdir()), [shortcut])

            with (
                patch.object(main, "_write_windows_shortcut", side_effect=lambda path: path.write_bytes(b"new")),
                patch.object(main.os, "replace", side_effect=PermissionError("locked")),
            ):
                with self.assertRaises(PermissionError):
                    main.create_windows_shortcut(shortcut)
            self.assertEqual(shortcut.read_bytes(), b"old shortcut")
            self.assertEqual(list(Path(directory).iterdir()), [shortcut])

    @unittest.skipUnless(main.os.name == "nt", "Windows shortcut integration")
    def test_atomic_replacement_produces_a_readable_windows_shortcut(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shortcut = Path(directory) / "Weather Report's test.lnk"
            shortcut.write_bytes(b"old invalid shortcut")
            target = str(Path(directory) / "WeatherReport.exe")
            with patch.object(main, "_resolve_shortcut_target", return_value=(target, "--test", directory, target)):
                main.create_windows_shortcut(shortcut)
            command = (
                "$ErrorActionPreference = 'Stop'; "
                "$shell = New-Object -ComObject WScript.Shell; "
                f"$link = $shell.CreateShortcut('{main._ps_escape(str(shortcut))}'); "
                "@{Target=$link.TargetPath; Arguments=$link.Arguments; WorkingDirectory=$link.WorkingDirectory} | ConvertTo-Json -Compress"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True, text=True, check=True, timeout=20, **main._hidden_subprocess_kwargs(),
            )
            actual = json.loads(result.stdout)
            self.assertEqual(actual, {"Target": target, "Arguments": "--test", "WorkingDirectory": directory})
            self.assertEqual(list(Path(directory).iterdir()), [shortcut])

    def test_source_restart_keeps_the_working_python_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            python = Path(temporary_dir) / "venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.touch()
            pythonw = python.with_name("pythonw.exe")
            for windowless in (False, True):
                with self.subTest(windowless=windowless):
                    if windowless:
                        pythonw.touch()
                    with (
                        patch.object(main, "IS_FROZEN", False),
                        patch.object(main.sys, "executable", str(python)),
                        patch.object(main.subprocess, "Popen") as popen,
                    ):
                        process = main.restart_application()
                    expected = pythonw if windowless and main.os.name == "nt" else python
                    self.assertEqual(popen.call_args.args[0], [str(expected), str(main.PROJECT_DIR / "main.py")])
                    self.assertIs(process, popen.return_value)

    def test_startup_repair_does_not_undo_a_later_disable(self) -> None:
        widget = object.__new__(main.WeatherWidget)
        widget._start_background_worker = Mock()
        with (
            patch.object(main, "is_startup_enabled", side_effect=[True, False]),
            patch.object(main, "set_startup_enabled") as set_enabled,
        ):
            widget._refresh_startup_shortcut_if_enabled()
            worker = widget._start_background_worker.call_args.args[0]
            worker()
        set_enabled.assert_not_called()

    def test_startup_paths_include_current_and_legacy_installer_names(self) -> None:
        appdata = Path(r"C:\Users\Example\AppData\Roaming")
        with patch.dict(main.os.environ, {"APPDATA": str(appdata)}):
            paths = main.get_startup_shortcut_paths()

        self.assertEqual(paths[0].name, main.STARTUP_SHORTCUT_NAME)
        self.assertIn(f"{main.APP_NAME}.lnk", [path.name for path in paths])


class TrayMenuTests(unittest.TestCase):
    def test_partial_tray_startup_is_cleaned_up_before_showing_fallback(self) -> None:
        widget = object.__new__(main.WeatherWidget)
        widget.tray_symbol = "cloud"
        widget.status_var = Mock()
        widget.deiconify = Mock()
        tray = Mock()
        tray.run_detached.side_effect = OSError("tray unavailable")
        fake_pystray = Mock()
        fake_pystray.Icon.return_value = tray
        with patch.object(main, "pystray", fake_pystray), patch.object(main, "build_tray_symbol_icon", return_value=object()):
            widget._init_tray_icon()
        tray.stop.assert_called_once()
        self.assertIsNone(widget.tray_icon)
        widget.deiconify.assert_called_once()

    def test_tray_menu_failure_does_not_hide_a_startup_setting_error(self) -> None:
        widget = object.__new__(main.WeatherWidget)
        widget.startup_change_in_progress = True
        widget.status_var = Mock()
        widget.tray_icon = Mock()
        widget.tray_icon.update_menu.side_effect = OSError("tray unavailable")
        widget.report_callback_exception = Mock()
        with patch.object(main.messagebox, "showerror") as show_error:
            widget._finish_startup_change("access denied")
        self.assertFalse(widget.startup_change_in_progress)
        show_error.assert_called_once()
        self.assertIn("access denied", show_error.call_args.args[1])
        widget.report_callback_exception.assert_called_once()

    def test_tray_titles_fit_the_windows_buffer_without_splitting_unicode(self) -> None:
        widget = object.__new__(main.WeatherWidget)
        widget.tray_icon = Mock()
        widget.report_callback_exception = Mock()
        titles = ("Espoo: 18 C", "A" * 127, "A" * 200, "x" + "\U0001f600" * 100)
        for title in titles:
            with self.subTest(length=len(title)), patch.object(main, "build_tray_symbol_icon", return_value=None):
                widget._update_tray_symbol("cloudy", title)
                actual = widget.tray_icon.title
                self.assertLessEqual(len(actual.encode("utf-16-le")), 254)
                ctypes.create_unicode_buffer(128).value = actual
                if len(title.encode("utf-16-le")) <= 254:
                    self.assertEqual(actual, title)
                else:
                    self.assertTrue(actual.endswith("..."))
        widget.report_callback_exception.assert_not_called()

    def test_desktop_shortcut_failure_allows_retry(self) -> None:
        widget = object.__new__(main.WeatherWidget)
        widget.desktop_shortcut_in_progress = False
        widget.status_var = Mock()
        widget._start_background_worker = lambda callback, **_kwargs: callback()
        widget._call_on_ui_thread = lambda callback: callback()
        with (
            patch.object(main, "create_desktop_shortcut", side_effect=[
                OSError("access denied"), Path("Weather Report.lnk"),
            ]) as create,
            patch.object(main.messagebox, "showinfo") as show_info,
            patch.object(main.messagebox, "showerror") as show_error,
        ):
            widget._create_desktop_shortcut_from_tray()
            self.assertFalse(widget.desktop_shortcut_in_progress)
            show_error.assert_called_once()
            show_info.assert_not_called()
            widget._create_desktop_shortcut_from_tray()
            self.assertFalse(widget.desktop_shortcut_in_progress)
            show_info.assert_called_once()
            self.assertEqual(create.call_count, 2)

    def test_desktop_shortcut_creation_does_not_block_ui_or_duplicate_work(self) -> None:
        widget = object.__new__(main.WeatherWidget)
        widget.desktop_shortcut_in_progress = False
        widget.status_var = Mock()
        widget._start_background_worker = Mock()
        widget._call_on_ui_thread = Mock()
        with (
            patch.object(main, "create_desktop_shortcut", return_value=Path("Weather Report.lnk")) as create,
            patch.object(main.messagebox, "showinfo") as show_info,
        ):
            widget._create_desktop_shortcut_from_tray()
            widget._create_desktop_shortcut_from_tray()
            create.assert_not_called()
            widget._start_background_worker.assert_called_once()
            widget._start_background_worker.call_args.args[0]()
            create.assert_called_once()
            show_info.assert_not_called()
            widget._call_on_ui_thread.call_args.args[0]()
        self.assertFalse(widget.desktop_shortcut_in_progress)
        show_info.assert_called_once()

    def test_startup_change_runs_off_ui_thread_and_ignores_duplicate_clicks(self) -> None:
        widget = object.__new__(main.WeatherWidget)
        widget.startup_change_in_progress = False
        widget.status_var = Mock()
        widget.tray_icon = Mock()
        widget._start_background_worker = Mock()
        widget._call_on_ui_thread = Mock()
        with (
            patch.object(main, "is_startup_enabled", return_value=False),
            patch.object(main, "set_startup_enabled") as set_enabled,
        ):
            widget._toggle_startup_from_tray()
            widget._toggle_startup_from_tray()
            self.assertTrue(widget.startup_change_in_progress)
            widget._start_background_worker.assert_called_once()
            set_enabled.assert_not_called()
            widget._start_background_worker.call_args.args[0]()
            set_enabled.assert_called_once_with(True)
            widget.tray_icon.update_menu.assert_not_called()
            widget._call_on_ui_thread.call_args.args[0]()
        self.assertFalse(widget.startup_change_in_progress)
        widget.tray_icon.update_menu.assert_called_once()

    def test_failed_startup_change_releases_guard_and_reports_error(self) -> None:
        widget = object.__new__(main.WeatherWidget)
        widget.startup_change_in_progress = False
        widget.status_var = Mock()
        widget.tray_icon = Mock()
        widget._start_background_worker = lambda callback, **_kwargs: callback()
        widget._call_on_ui_thread = lambda callback: callback()
        with (
            patch.object(main, "is_startup_enabled", return_value=True),
            patch.object(main, "set_startup_enabled", side_effect=OSError("access denied")),
            patch.object(main.messagebox, "showerror") as show_error,
        ):
            widget._toggle_startup_from_tray()
        self.assertFalse(widget.startup_change_in_progress)
        show_error.assert_called_once()
        widget.tray_icon.update_menu.assert_called_once()

    def test_source_tray_menu_exposes_and_dispatches_all_actions(self) -> None:
        class FakeMenuItem:
            def __init__(self, text, action, **kwargs):
                self.text = text
                self.action = action
                self.options = kwargs

        class FakeMenu:
            SEPARATOR = object()

            def __init__(self, *items):
                self.items = list(items)

        class FakeIcon:
            def __init__(self, _name, _image, _title, menu):
                self.menu = menu

            def run_detached(self):
                return None

        class FakePystray:
            MenuItem = FakeMenuItem
            Menu = FakeMenu
            Icon = FakeIcon

        widget = object.__new__(main.WeatherWidget)
        widget.tray_icon = None
        widget.tray_symbol = "cloud"
        widget._call_on_ui_thread = lambda callback: callback()
        widget.status_var = type("Status", (), {"set": lambda _self, _value: None})()
        calls = []
        widget.toggle_popup = lambda: calls.append("toggle")
        widget.refresh_weather = lambda: calls.append("refresh")
        widget._toggle_startup_from_tray = lambda: calls.append("startup")
        widget._create_desktop_shortcut_from_tray = lambda: calls.append("desktop")
        widget._open_taskbar_icon_settings = lambda: calls.append("taskbar")
        widget._quit_from_tray = lambda: calls.append("quit")
        widget.check_for_app_update = lambda manual=False: calls.append(("update", manual))

        with (
            patch.object(main, "pystray", FakePystray),
            patch.object(main, "Image", object()),
            patch.object(main, "IS_FROZEN", False),
            patch.object(main, "build_tray_symbol_icon", return_value=object()),
        ):
            widget._init_tray_icon()

        menu_items = [item for item in widget.tray_icon.menu.items if item is not FakeMenu.SEPARATOR]
        self.assertEqual(
            [item.text for item in menu_items],
            [
                "Näytä/piilota viikkonäkymä",
                "Päivitä sää",
                "Tarkista sovelluspäivitys",
                "Käynnistä tietokoneen käynnistyessä",
                "Luo pikakuvake työpöydälle",
                "Näytä kuvakerivissä",
                "Lopeta",
            ],
        )

        for item in menu_items:
            item.action(None, item)

        self.assertEqual(
            calls,
            ["toggle", "refresh", ("update", True), "startup", "desktop", "taskbar", "quit"],
        )


class UpdateSafetyTests(unittest.TestCase):
    def test_git_commands_disable_hidden_credential_prompts(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with (
            patch.object(main.shutil, "which", return_value=r"C:\Git\git.exe"),
            patch.object(main.subprocess, "run", return_value=completed) as run,
        ):
            main._run_git_command(["status", "--porcelain"])

        self.assertEqual(run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(run.call_args.kwargs["env"]["GCM_INTERACTIVE"], "Never")

    def test_update_status_fetches_origin_main_and_reports_fast_forward(self) -> None:
        inside_worktree = subprocess.CompletedProcess([], 0, stdout="true\n", stderr="")
        fast_forward = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with (
            patch.object(
                main,
                "_git_output",
                side_effect=["main", "", "", "local-sha", "remote-sha"],
            ) as git_output,
            patch.object(
                main,
                "_run_git_command",
                side_effect=[inside_worktree, fast_forward],
            ) as run_git,
        ):
            status = main.check_github_update_status()

        self.assertEqual(status["state"], "available")
        self.assertEqual(status["local"], "local-sha")
        self.assertEqual(status["remote"], "remote-sha")
        self.assertEqual(git_output.call_args_list[2].args[0], ["fetch", "origin", "main"])
        self.assertEqual(
            run_git.call_args_list[1].args[0],
            ["merge-base", "--is-ancestor", "HEAD", "origin/main"],
        )

    def test_current_update_status_includes_running_version(self) -> None:
        with patch.object(
            main,
            "_git_output",
            side_effect=["main", "", "", "local-sha", "local-sha"],
        ), patch.object(
            main,
            "_run_git_command",
            return_value=subprocess.CompletedProcess([], 0, stdout="true\n", stderr=""),
        ):
            status = main.check_github_update_status()

        self.assertEqual(status["state"], "current")
        self.assertIn(main.APP_VERSION_LABEL, status["message"])

    def test_update_status_detects_code_changed_while_process_was_running(self) -> None:
        with patch.object(
            main,
            "_git_output",
            side_effect=["main", ""],
        ) as git_output, patch.object(
            main,
            "_run_git_command",
            return_value=subprocess.CompletedProcess([], 0, stdout="true\n", stderr=""),
        ), patch.object(
            main,
            "RUNTIME_FILE_SIGNATURE_AT_START",
            (("main.py", 1, 1),),
        ), patch.object(
            main,
            "_runtime_file_signature",
            return_value=(("assets/weather-icons/sun.png", 2, 2),),
        ):
            status = main.check_github_update_status()

        self.assertEqual(status["state"], "restart_available")
        self.assertEqual(git_output.call_count, 2)

    def test_runtime_signature_tracks_assets_but_not_documentation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            (root / "main.py").write_text("pass", encoding="utf-8")
            assets = root / "assets"
            assets.mkdir()
            icon = assets / "sun.png"
            with patch.object(main, "PROJECT_DIR", root), patch.object(main, "IS_FROZEN", False):
                original = main._runtime_file_signature()
                (root / "README.md").write_text("docs", encoding="utf-8")
                self.assertEqual(main._runtime_file_signature(), original)
                icon.write_bytes(b"image")
                added = main._runtime_file_signature()
                self.assertNotEqual(added, original)
                icon.write_bytes(b"changed image")
                self.assertNotEqual(main._runtime_file_signature(), added)
                icon.unlink()
                self.assertEqual(main._runtime_file_signature(), original)

    def test_update_status_handles_non_repository_and_git_comparison_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir, patch.object(
            main,
            "PROJECT_DIR",
            Path(temporary_dir),
        ), patch.object(main, "_run_git_command") as run_git:
            status = main.check_github_update_status()
        self.assertEqual(status["state"], "unsupported")
        run_git.assert_not_called()

        repository_error = subprocess.CompletedProcess([], 128, stdout="", stderr="broken repository")
        with patch.object(main, "_run_git_command", return_value=repository_error):
            with self.assertRaisesRegex(RuntimeError, "broken repository"):
                main.check_github_update_status()

        inside_worktree = subprocess.CompletedProcess([], 0, stdout="true\n", stderr="")
        comparison_error = subprocess.CompletedProcess([], 128, stdout="", stderr="broken graph")
        with (
            patch.object(
                main,
                "_git_output",
                side_effect=["main", "", "", "local-sha", "remote-sha"],
            ),
            patch.object(
                main,
                "_run_git_command",
                side_effect=[inside_worktree, comparison_error],
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "broken graph"):
                main.check_github_update_status()

        comparison_timeout = subprocess.TimeoutExpired(["git", "merge-base"], 30)
        with (
            patch.object(
                main,
                "_git_output",
                side_effect=["main", "", "", "local-sha", "remote-sha"],
            ),
            patch.object(
                main,
                "_run_git_command",
                side_effect=[inside_worktree, comparison_timeout],
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "vertailu aikakatkaistiin"):
                main.check_github_update_status()

    def test_git_timeout_is_reported_as_application_error(self) -> None:
        timeout = subprocess.TimeoutExpired(["git", "fetch"], 30)
        with patch.object(main, "_run_git_command", side_effect=timeout):
            with self.assertRaisesRegex(RuntimeError, "aikakatkaistiin"):
                main._git_output(["fetch", "origin", "main"])

    def test_packaged_update_path_is_not_mistaken_for_git_update(self) -> None:
        with patch.object(main, "IS_FROZEN", True):
            status = main.check_github_update_status()

        self.assertEqual(status["state"], "unsupported")

    def test_apply_update_rechecks_worktree_before_pull(self) -> None:
        with (
            patch.object(main, "_git_output", side_effect=[main.UPDATE_BRANCH, " M main.py"]),
            patch.object(main, "_run_git_command") as run_git,
        ):
            with self.assertRaisesRegex(RuntimeError, "Paikallisia muutoksia"):
                main.apply_github_update()

        run_git.assert_not_called()


class UpdateLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.widget = object.__new__(main.WeatherWidget)
        self.widget.update_check_in_progress = True
        self.widget.status_var = Mock()
        self.widget._start_background_worker = Mock()
        self.widget._call_on_ui_thread = lambda callback: callback()
        self.widget.after = Mock(return_value="restart-job")
        self.widget.destroy = Mock()

    def test_update_stays_exclusive_through_confirmation_and_restart(self) -> None:
        widget = self.widget

        def confirm(*_args):
            widget.check_for_app_update(manual=True)
            widget._start_background_worker.assert_not_called()
            return True

        process = Mock()
        process.poll.return_value = None
        with (
            patch.object(main.messagebox, "askyesno", side_effect=confirm),
            patch.object(main, "apply_github_update") as apply_update,
            patch.object(main, "restart_application", return_value=process),
        ):
            widget._handle_update_check_result({"state": "available"}, True)
            self.assertTrue(widget.update_check_in_progress)
            widget.check_for_app_update(manual=True)
            widget._start_background_worker.assert_called_once()
            widget._start_background_worker.call_args.args[0]()
            apply_update.assert_called_once()
            self.assertTrue(widget.update_check_in_progress)
            widget.destroy.assert_not_called()
            widget.after.call_args.args[1]()
        widget.destroy.assert_called_once()

    def test_declining_either_update_action_releases_the_guard(self) -> None:
        for state in ("available", "restart_available"):
            with self.subTest(state=state), patch.object(main.messagebox, "askyesno", return_value=False):
                self.widget.update_check_in_progress = True
                self.widget._handle_update_check_result({"state": state}, True)
                self.assertFalse(self.widget.update_check_in_progress)
        self.widget._start_background_worker.assert_not_called()

    def test_failed_update_is_visible_and_keeps_the_current_app_alive(self) -> None:
        with (
            patch.object(main.messagebox, "showerror") as show_error,
            patch.object(main, "restart_application") as restart,
        ):
            self.widget._finish_app_update("network failed")
        show_error.assert_called_once()
        restart.assert_not_called()
        self.widget.destroy.assert_not_called()
        self.assertFalse(self.widget.update_check_in_progress)

    def test_failed_restart_spawn_keeps_the_current_app_alive(self) -> None:
        with (
            patch.object(main.messagebox, "showerror") as show_error,
            patch.object(main, "restart_application", side_effect=OSError("missing executable")),
        ):
            self.widget._finish_app_update(None)
        show_error.assert_called_once()
        self.widget.after.assert_not_called()
        self.widget.destroy.assert_not_called()
        self.assertFalse(self.widget.update_check_in_progress)

    def test_early_child_exit_keeps_the_current_app_alive(self) -> None:
        for exit_code in (0, 1):
            with self.subTest(exit_code=exit_code):
                self.widget.update_check_in_progress = True
                process = Mock()
                process.poll.return_value = exit_code
                with patch.object(main.messagebox, "showerror") as show_error:
                    self.widget._check_restart_process(process)
                show_error.assert_called_once()
                self.widget.destroy.assert_not_called()
                self.assertFalse(self.widget.update_check_in_progress)


class WeatherResultTests(unittest.TestCase):
    @staticmethod
    def make_result_widget(entry: str = "Espoo"):
        widget = object.__new__(main.WeatherWidget)
        widget.unit_symbol = "C"
        widget.settings = {"city": "Espoo", "popup_theme": main.DEFAULT_POPUP_THEME}
        widget._settings_save_pending = False
        widget.city_var = Mock()
        widget.detail_city_var = Mock()
        widget.detail_city_var.get.return_value = entry
        widget.city_search = Mock()
        widget.city_search.editing = False
        widget.city_search.set_text.side_effect = lambda text, place: widget.detail_city_var.set(text)
        widget.status_var = Mock()
        widget.popup_bg_canvas = Mock()
        widget.footer_label = 1
        widget.hero_updated_label = 2
        widget._apply_current_weather_summary = Mock()
        widget._apply_today_detail_metrics = Mock()
        widget._apply_forecast_cards = Mock()
        widget._update_tray_symbol = Mock()
        widget._schedule_refresh = Mock()
        widget._run_pending_city_search = Mock()
        widget.pending_city_search = None
        return widget

    def test_failed_city_change_keeps_the_selected_location_as_retry_target(self) -> None:
        widget = self.make_result_widget("Espoo")
        old_place = {"name": "Espoo", "latitude": 60.2, "longitude": 24.65}
        new_place = {"name": "Richmond", "latitude": 49.17, "longitude": -123.14}
        weather = {"current": {"weather_code": 3, "temperature_2m": 18}, "daily": {"time": ["2026-09-04"]}}
        widget._persist_settings = Mock()
        widget._apply_weather(old_place, weather, "Espoo")
        widget._start_background_worker = Mock()
        widget._call_on_ui_thread = lambda callback: callback()
        with (
            patch.object(main, "get_weather", side_effect=URLError("offline")),
            patch.object(main, "geocode_city") as geocode,
            patch.object(main.time, "sleep"),
            patch.object(main.messagebox, "showerror"),
        ):
            widget.refresh_weather("Richmond", new_place)
            widget._start_background_worker.call_args.args[0]()
        geocode.assert_not_called()
        self.assertIs(widget.latest_weather, weather)
        self.assertEqual(widget.latest_place, old_place)
        self.assertEqual(widget.settings["city"], "Espoo")
        self.assertFalse(widget.fetch_in_progress)
        widget._fetch_worker = Mock()
        widget.refresh_weather()
        widget._start_background_worker.call_args.args[0]()
        widget._fetch_worker.assert_called_once_with("Richmond", "celsius", new_place)

    def test_rejected_search_does_not_change_the_retry_target(self) -> None:
        widget = self.make_result_widget()
        widget.refresh_target = ("Espoo", None)
        with patch.object(main.messagebox, "showinfo"):
            widget.refresh_weather("  ")
            widget.refresh_weather("a" * (main.MAX_CITY_QUERY_LENGTH + 1))
        self.assertEqual(widget.refresh_target, ("Espoo", None))

    def test_unknown_city_does_not_replace_the_automatic_refresh_target(self) -> None:
        widget = self.make_result_widget("Not a real city")
        old_place = {"name": "Espoo", "latitude": 60.2, "longitude": 24.65}
        weather = {"current": {"weather_code": 3, "temperature_2m": 18}, "daily": {"time": ["2026-09-04"]}}
        widget._persist_settings = Mock()
        widget._apply_weather(old_place, weather, "Espoo")
        widget.city_var.get.return_value = "Espoo"
        widget._start_background_worker = Mock()
        widget._call_on_ui_thread = lambda callback: callback()
        with (
            patch.object(main, "geocode_city", side_effect=main.CityNotFoundError("Not found")),
            patch.object(main.messagebox, "showerror") as show_error,
        ):
            widget.refresh_weather("Not a real city")
            widget._start_background_worker.call_args.args[0]()
        show_error.assert_called_once()
        self.assertEqual(widget.detail_city_var.get(), "Not a real city")
        widget._fetch_worker = Mock()
        widget.refresh_weather()
        widget._start_background_worker.call_args.args[0]()
        widget._fetch_worker.assert_called_once_with("Espoo", "celsius", old_place)

    def test_daily_metrics_and_forecast_start_at_the_current_location_day(self) -> None:
        widget = self.make_result_widget()
        weather = {
            "current": {"weather_code": 3, "temperature_2m": 18, "time": "2026-09-04T23:30-10:00"},
            "daily": {
                "time": ["2026-09-03", "2026-09-04", "2026-09-05"],
                "temperature_2m_max": [90, 20, 21], "temperature_2m_min": [80, 10, 11],
                "precipitation_sum": [99, 2.5, 3], "precipitation_probability_max": [99, 30, 40],
                "sunrise": ["2026-09-03T08:00", "2026-09-04T06:15", "2026-09-05T06:16"],
                "sunset": ["2026-09-03T18:00", "2026-09-04T20:15", "2026-09-05T20:16"],
            },
        }
        widget._apply_weather({"name": "Espoo"}, weather, "Espoo")
        metrics = widget._apply_today_detail_metrics.call_args.kwargs
        self.assertEqual(metrics["high_low_text"], "ylin 20°C / alin 10°C")
        self.assertEqual(metrics["rain_mm"], "2.5 mm")
        self.assertEqual(metrics["rain_probability"], "30%")
        self.assertEqual((metrics["sunrise"], metrics["sunset"]), ("06:15", "20:15"))
        widget._apply_forecast_cards.assert_called_once_with(weather["daily"], start_index=2)

    def test_bad_forecast_does_not_replace_the_last_good_data_or_settings(self) -> None:
        widget = self.make_result_widget()
        weather = {"current": {"weather_code": 3, "temperature_2m": 18}, "daily": {"time": ["2026-09-04"]}}
        widget._apply_weather({"name": "Espoo"}, weather, "Espoo")
        invalid = {"current": weather["current"], "daily": {"time": [None]}}
        with patch.object(main.messagebox, "showerror"):
            widget._handle_weather_result({"name": "Turku"}, invalid, "Turku")
        self.assertIs(widget.latest_weather, weather)
        self.assertEqual(widget.settings["city"], "Espoo")
        self.assertFalse(widget.fetch_in_progress)

    def test_superseded_weather_success_does_not_replace_the_selected_city(self) -> None:
        widget = self.make_result_widget("Richmond")
        widget.fetch_in_progress = True
        widget.pending_city_search = "Richmond"
        widget._apply_weather = Mock()
        widget._handle_weather_result({"name": "Richmond", "latitude": 37.54, "longitude": -77.43}, {}, "Richmond")
        widget._apply_weather.assert_not_called()
        self.assertFalse(widget.fetch_in_progress)
        widget._run_pending_city_search.assert_called_once()

    def test_superseded_weather_error_does_not_interrupt_the_next_search(self) -> None:
        widget = self.make_result_widget("Espoo")
        widget.fetch_in_progress = True
        widget.latest_weather = None
        widget.pending_city_search = "Espoo"
        widget.refresh_target = ("Espoo", None)
        with patch.object(main.messagebox, "showerror") as show_error:
            widget._show_error("Old city not found", notify_user=True, retry_previous_location=True)
        self.assertEqual(widget.refresh_target, ("Espoo", None))
        show_error.assert_not_called()
        widget._update_tray_symbol.assert_not_called()
        widget._schedule_refresh.assert_not_called()
        self.assertFalse(widget.fetch_in_progress)
        widget._run_pending_city_search.assert_called_once()

    def test_weather_refresh_does_not_reset_an_active_same_name_search(self) -> None:
        widget = self.make_result_widget("Espoo")
        widget.city_search.editing = True
        weather = {"current": {"weather_code": 3, "temperature_2m": 18}, "daily": {"time": ["2026-09-04"]}}
        widget._apply_weather({"name": "Espoo"}, weather, "Espoo")
        widget.city_search.set_text.assert_not_called()
        widget._apply_forecast_cards.assert_called_once()

    def test_tray_failure_does_not_interrupt_weather_or_future_refreshes(self) -> None:
        class FailingTray:
            @property
            def icon(self):
                return None

            @icon.setter
            def icon(self, _value):
                raise OSError("tray temporarily unavailable")

        widget = self.make_result_widget()
        del widget._update_tray_symbol
        widget.tray_icon = FailingTray()
        widget.report_callback_exception = Mock()
        weather = {"current": {"weather_code": 3, "temperature_2m": 18}, "daily": {"time": ["2026-09-03"]}}
        with patch.object(main, "build_tray_symbol_icon", return_value=object()):
            widget._apply_weather({"name": "Espoo"}, weather, "Espoo")
        self.assertIs(widget.latest_weather, weather)
        self.assertFalse(widget.fetch_in_progress)
        widget._apply_forecast_cards.assert_called_once()
        widget._schedule_refresh.assert_called_once()
        widget._run_pending_city_search.assert_called_once()
        widget.report_callback_exception.assert_called_once()

    def test_failed_refresh_marks_the_card_without_discarding_good_weather(self) -> None:
        widget = self.make_result_widget()
        weather = {"current": {"weather_code": 3, "temperature_2m": 18}, "daily": {"time": ["2026-09-03"]}}
        widget._apply_weather({"name": "Espoo"}, weather, "Espoo")
        with patch.object(main.messagebox, "showerror") as dialog:
            widget._show_error("Network error")
        self.assertIs(widget.latest_weather, weather)
        self.assertFalse(widget.fetch_in_progress)
        updates = [call.kwargs.get("text", "") for call in widget.popup_bg_canvas.itemconfigure.call_args_list
                   if call.args[0] == widget.hero_updated_label]
        self.assertTrue(any("epäonnistui" in text for text in updates))
        dialog.assert_not_called()
        self.assertEqual(widget._schedule_refresh.call_count, 2)
        self.assertEqual(widget._run_pending_city_search.call_count, 2)

    def test_settings_failure_warns_once_and_retries_with_latest_preferences(self) -> None:
        widget = self.make_result_widget()
        widget.popup_theme_id = main.DEFAULT_POPUP_THEME
        widget.popup = None
        widget._update_theme_dot_color = Mock()
        theme = next(key for key in main.POPUP_THEMES if key != main.DEFAULT_POPUP_THEME)
        weather = {
            "current": {"weather_code": 3, "temperature_2m": 18},
            "daily": {"time": ["2026-09-02"]},
        }
        with (
            patch.object(main, "save_settings", side_effect=[False, False, True, False]) as save,
            patch.object(main.messagebox, "showwarning") as warning,
        ):
            widget._set_popup_theme(theme)
            self.assertEqual(widget.popup_theme_id, theme)
            self.assertTrue(widget._settings_save_pending)
            warning.assert_called_once()
            widget._apply_weather({"name": "Espoo"}, weather, "Espoo")
            self.assertTrue(widget._settings_save_pending)
            warning.assert_called_once()
            widget._apply_weather({"name": "Espoo"}, weather, "Espoo")
            self.assertFalse(widget._settings_save_pending)
            self.assertEqual(save.call_count, 3)
            widget._apply_weather({"name": "Espoo"}, weather, "Espoo")
            self.assertEqual(save.call_count, 3)
            widget._apply_weather({"name": "Helsinki"}, weather, "Helsinki")
            self.assertTrue(widget._settings_save_pending)
            self.assertEqual(warning.call_count, 2)
            save.assert_called_with({"city": "Helsinki", "popup_theme": theme})
            self.assertIs(widget.latest_weather, weather)
            self.assertFalse(widget.fetch_in_progress)

    def test_pending_settings_are_retried_when_closing(self) -> None:
        widget = self.make_result_widget()
        widget._is_destroying = False
        widget._settings_save_pending = True
        widget._stop_tray_icon = Mock()
        for job in ("clock_job", "refresh_job", "bootstrap_job", "update_job", "restart_job", "ui_poll_job"):
            setattr(widget, job, None)
        with patch.object(main, "save_settings", return_value=False) as save, patch.object(main.tk.Tk, "destroy") as destroy:
            widget.destroy()
            widget.destroy()
        save.assert_called_once_with(widget.settings)
        destroy.assert_called_once()

    def test_pending_search_cannot_overtake_a_newer_request(self) -> None:
        widget = object.__new__(main.WeatherWidget)
        widget.fetch_in_progress = False
        widget.pending_city_search = "Turku"
        widget.pending_city_place = None
        widget.popup_bg_canvas = Mock()
        widget.hero_updated_label = 2
        widget._is_destroying = False
        widget.status_var = Mock()
        widget.settings = {}
        widget._start_background_worker = Mock()
        idle_callbacks = []
        widget.after_idle = idle_callbacks.append
        widget._run_pending_city_search()
        widget.refresh_weather("Helsinki")
        for callback in idle_callbacks:
            callback()
        self.assertEqual(widget.pending_city_search, "Helsinki")

    def test_new_search_discards_older_pending_search(self) -> None:
        widget = object.__new__(main.WeatherWidget)
        widget.fetch_in_progress = False
        widget.pending_city_search = "Turku"
        widget.pending_city_place = None
        widget.popup_bg_canvas = Mock()
        widget.hero_updated_label = 2
        widget.status_var = Mock()
        widget.settings = {}
        widget._start_background_worker = Mock()
        widget.refresh_weather("Helsinki")
        self.assertIsNone(widget.pending_city_search)

    def test_completed_fetch_preserves_a_new_city_being_typed(self) -> None:
        for entry, expected in (("Helsinki", "Helsinki"), ("", ""), ("  espoo  ", "Espoo")):
            with self.subTest(entry=entry):
                widget = self.make_result_widget(entry)
                weather = {
                    "current": {"weather_code": 3, "temperature_2m": 18},
                    "daily": {"time": ["2026-09-02"]},
                }
                with patch.object(main, "is_startup_enabled", return_value=False):
                    widget._apply_weather({"name": "Espoo"}, weather, "espoo")
                widget.city_var.set.assert_called_once_with("Espoo")
                self.assertIs(widget.latest_weather, weather)
                self.assertFalse(widget.fetch_in_progress)
                if entry == expected:
                    widget.detail_city_var.set.assert_not_called()
                else:
                    widget.detail_city_var.set.assert_called_once_with(expected)

    def test_pending_search_uses_the_most_recent_request(self) -> None:
        widget = object.__new__(main.WeatherWidget)
        widget.fetch_in_progress = True
        widget.popup_bg_canvas = Mock()
        widget.hero_updated_label = 2
        widget.status_var = Mock()
        widget._is_destroying = False
        widget.refresh_weather("Turku")
        widget.refresh_weather("Tampere")
        self.assertEqual(widget.pending_city_search, "Tampere")
        widget.refresh_weather = Mock()
        widget._run_pending_city_search()
        self.assertIsNone(widget.pending_city_search)
        widget.refresh_weather.assert_called_once_with("Tampere")

    def test_clock_moving_backwards_does_not_keep_old_weather_fresh(self) -> None:
        widget = object.__new__(main.WeatherWidget)
        widget.fetch_in_progress = False
        widget.latest_weather = {"current": {}}
        widget.refresh_weather = Mock()
        widget.last_weather_update = main.datetime.now() + main.timedelta(hours=1)
        widget._ensure_fresh_weather()
        widget.refresh_weather.assert_called_once()


class ThreadDispatchTests(unittest.TestCase):
    def test_worker_start_failure_releases_guards_and_allows_retry(self) -> None:
        cases = (
            ("refresh_weather", "fetch_in_progress"),
            ("_toggle_startup_from_tray", "startup_change_in_progress"),
            ("_create_desktop_shortcut_from_tray", "desktop_shortcut_in_progress"),
            ("check_for_app_update", "update_check_in_progress"),
            ("_apply_app_update", "update_check_in_progress"),
        )
        for action, guard in cases:
            with self.subTest(action=action):
                widget = WeatherResultTests.make_result_widget()
                setattr(widget, guard, False)
                widget.latest_weather = None
                widget.tray_icon = None
                widget.refresh_target = ("Espoo", None)
                widget._call_on_ui_thread = lambda callback: callback()
                widget.destroy = Mock()
                with (
                    patch.object(main, "is_startup_enabled", return_value=False),
                    patch.object(main.threading, "Thread") as thread,
                    patch.object(main.messagebox, "showerror") as show_error,
                ):
                    thread.return_value.start.side_effect = RuntimeError("cannot start new thread")
                    run = getattr(widget, action)
                    run(manual=True) if action == "check_for_app_update" else run()
                    self.assertFalse(getattr(widget, guard))
                    show_error.assert_called_once()
                    widget.destroy.assert_not_called()
                    thread.return_value.start.side_effect = None
                    run(manual=True) if action == "check_for_app_update" else run()
                    self.assertTrue(getattr(widget, guard))
                    self.assertEqual(thread.return_value.start.call_count, 2)

    def test_ui_dispatch_runs_locally_or_queues_without_touching_tk(self) -> None:
        widget = object.__new__(main.WeatherWidget)
        widget._is_destroying = False
        widget._ui_thread_id = threading.get_ident()
        widget._ui_callbacks = queue.SimpleQueue()
        calls = []

        widget._call_on_ui_thread(lambda: calls.append("direct"))
        self.assertEqual(calls, ["direct"])

        widget._ui_thread_id = -1
        widget._call_on_ui_thread(lambda: calls.append("queued"))
        queued_callback = widget._ui_callbacks.get_nowait()
        self.assertEqual(calls, ["direct"])
        queued_callback()
        self.assertEqual(calls, ["direct", "queued"])

        widget._is_destroying = True
        widget._call_on_ui_thread(lambda: calls.append("late"))
        with self.assertRaises(queue.Empty):
            widget._ui_callbacks.get_nowait()


class PackagingManifestTests(unittest.TestCase):
    def test_build_and_installer_default_versions_match(self) -> None:
        build_script = (main.PROJECT_DIR / "build_release.ps1").read_text(encoding="utf-8")
        installer_script = (main.PROJECT_DIR / "installer.iss").read_text(encoding="utf-8")
        build_match = re.search(r"\[string\]\$Version = '([^']+)'", build_script)
        installer_match = re.search(r'#define AppVersion "([^"]+)"', installer_script)

        self.assertIsNotNone(build_match)
        self.assertIsNotNone(installer_match)
        self.assertEqual(main.APP_VERSION, build_match.group(1))
        self.assertEqual(build_match.group(1), installer_match.group(1))

    def test_footer_contains_data_terms_and_version(self) -> None:
        self.assertIn("Säädata: Open-Meteo", main.FOOTER_TEXT)
        self.assertIn("Käyttöehdot", main.FOOTER_TEXT)
        self.assertIn(f"• Versio: {main.APP_VERSION_DATE}", main.FOOTER_TEXT)
        self.assertNotIn(main.APP_VERSION, main.FOOTER_TEXT)

    def test_installers_share_location_and_replace_stale_startup_shortcuts(self) -> None:
        install_script = (main.PROJECT_DIR / "install.ps1").read_text(encoding="utf-8")
        installer_script = (main.PROJECT_DIR / "installer.iss").read_text(encoding="utf-8")

        self.assertIn("Programs\\WeatherReport", install_script)
        self.assertIn("if ($Startup -or $startupWasEnabled)", install_script)
        self.assertIn("-Path $startupShortcutPath", install_script)
        self.assertIn("$newInstallActivated = $true", install_script)
        self.assertIn("previous version could not be fully restored", install_script)
        self.assertIn("DefaultDirName={localappdata}\\Programs\\WeatherReport", installer_script)
        self.assertIn(
            'Name: "{userstartup}\\Weather Report.lnk"; Tasks: startupshortcut',
            installer_script,
        )
        self.assertNotIn(
            'Type: files; Name: "{userstartup}\\weather-report.lnk"',
            installer_script,
        )

    def test_release_publishing_is_restricted_to_main(self) -> None:
        publish_script = (main.PROJECT_DIR / "publish_release.ps1").read_text(encoding="utf-8")

        self.assertIn("$releaseBranch = 'main'", publish_script)
        self.assertIn("Sync-CurrentBranch -ExpectedBranch $releaseBranch", publish_script)
        self.assertIn("function Get-RequiredCommandOutput", publish_script)

    def test_uninstaller_settings_path_has_local_appdata_fallback(self) -> None:
        uninstall_script = (main.PROJECT_DIR / "uninstall.ps1").read_text(encoding="utf-8")

        self.assertIn("else { $env:LOCALAPPDATA }", uninstall_script)

    def test_source_launcher_checks_fallback_python_version(self) -> None:
        launcher = (main.PROJECT_DIR / "start_weather_app.bat").read_text(encoding="utf-8")

        fallback_block = launcher.split("for /f", maxsplit=1)[1].split("where py", maxsplit=1)[0]
        self.assertIn("sys.version_info < (3,10)", fallback_block)

    def test_pyinstaller_manifest_contains_every_runtime_asset(self) -> None:
        class AnalysisStub:
            def __init__(self, *_args, datas, **_kwargs) -> None:
                self.datas = datas
                self.pure = []
                self.scripts = []
                self.binaries = []

        namespace = {
            "SPECPATH": str(main.PROJECT_DIR),
            "Analysis": AnalysisStub,
            "PYZ": lambda *_args, **_kwargs: object(),
            "EXE": lambda *_args, **_kwargs: object(),
            "COLLECT": lambda *_args, **_kwargs: object(),
        }
        spec_path = main.PROJECT_DIR / "WeatherReport.spec"
        exec(compile(spec_path.read_text(encoding="utf-8"), str(spec_path), "exec"), namespace)

        packaged_sources = {Path(source).resolve() for source, _destination in namespace["datas"]}
        required_sources = {
            *(path.resolve() for path in main.WEATHER_ICONS_DIR.iterdir() if path.is_file()),
            *(path.resolve() for path in main.METRIC_ICONS_DIR.iterdir() if path.is_file()),
            *(path.resolve() for path in main.FONTS_DIR.iterdir() if path.is_file()),
            main.APP_ICON_PATH.resolve(),
            main.APP_LOGO_PATH.resolve(),
        }
        self.assertTrue(required_sources)
        self.assertTrue(required_sources.issubset(packaged_sources))
        legacy_tray_asset = (main.ASSETS_DIR / "tray.png").resolve()
        self.assertFalse(legacy_tray_asset.exists())
        self.assertNotIn(legacy_tray_asset, packaged_sources)
        self.assertNotIn((main.PROJECT_DIR / "start_weather_app.bat").resolve(), packaged_sources)


if __name__ == "__main__":
    unittest.main()
