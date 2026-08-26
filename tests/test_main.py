import json
import queue
import re
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
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

            def read(self) -> bytes:
                return self.payload

        with patch.object(main, "urlopen", return_value=Response(b'{"ok": true}')) as mocked_open:
            self.assertEqual(main._get_json("https://example.invalid", {"q": "Espoo"}), {"ok": True})
        request = mocked_open.call_args.args[0]
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(request.get_header("User-agent"), f"{main.APP_SLUG}-desktop")

        with patch.object(main, "urlopen", return_value=Response(b"[]")):
            with self.assertRaises(main.WeatherServiceError):
                main._get_json("https://example.invalid", {})

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
        with patch.object(main, "_get_json", return_value=payload):
            place = main.geocode_city("Espoo")
        self.assertEqual(place["latitude"], 60.2055)
        self.assertEqual(place["longitude"], 24.6559)

    def test_geocoding_distinguishes_not_found_from_invalid_payload(self) -> None:
        with patch.object(main, "_get_json", return_value={"results": []}):
            with self.assertRaises(main.CityNotFoundError):
                main.geocode_city("Missing")

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
    def test_settings_are_whitelisted_and_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "weather_settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "city": "  Espoo  ",
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
                    "city": "Espoo",
                    "temperature_unit": "celsius",
                    "popup_theme": main.DEFAULT_POPUP_THEME,
                },
            )

    def test_atomic_settings_save_keeps_previous_file_on_serialization_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            settings_path = Path(temporary_dir) / "weather_settings.json"
            original = {"city": "Espoo", "temperature_unit": "celsius"}
            with patch.object(main, "SETTINGS_PATH", settings_path):
                main.save_settings(original)
                main.save_settings({"city": object()})

            self.assertEqual(json.loads(settings_path.read_text(encoding="utf-8")), original)
            self.assertEqual(list(settings_path.parent.glob(".*.tmp")), [])

    def test_source_shortcut_quotes_main_script_path(self) -> None:
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

    def test_startup_paths_include_current_and_legacy_installer_names(self) -> None:
        appdata = Path(r"C:\Users\Example\AppData\Roaming")
        with patch.dict(main.os.environ, {"APPDATA": str(appdata)}):
            paths = main.get_startup_shortcut_paths()

        self.assertEqual(paths[0].name, main.STARTUP_SHORTCUT_NAME)
        self.assertIn(f"{main.APP_NAME}.lnk", [path.name for path in paths])


class TrayMenuTests(unittest.TestCase):
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
    def test_apply_update_rechecks_worktree_before_pull(self) -> None:
        with (
            patch.object(main, "_git_output", side_effect=[main.UPDATE_BRANCH, " M main.py"]),
            patch.object(main, "_run_git_command") as run_git,
        ):
            with self.assertRaisesRegex(RuntimeError, "Paikallisia muutoksia"):
                main.apply_github_update()

        run_git.assert_not_called()


class ThreadDispatchTests(unittest.TestCase):
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
        self.assertEqual(build_match.group(1), installer_match.group(1))

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
