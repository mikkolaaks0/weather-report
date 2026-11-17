import unittest
from unittest.mock import patch

import main


class WeatherDateTests(unittest.TestCase):
    def test_rollover_uses_the_forecast_offset_in_both_directions(self):
        for offset, timestamp, utc_now, expected in (
            (10800, "2026-09-13T23:45", "2026-09-13T21:01+00:00", True),
            (-36000, "2026-09-13T23:45", "2026-09-14T10:01+00:00", True),
            (-36000, "2026-09-13T20:00", "2026-09-14T06:01+00:00", False),
            (50400, "2026-09-14T00:00", "2026-09-13T10:01+00:00", False),
        ):
            with self.subTest(offset=offset, timestamp=timestamp):
                now = main.datetime.fromisoformat(utc_now)
                with patch.object(main, "datetime", wraps=main.datetime) as clock:
                    clock.now.return_value = now
                    self.assertEqual(main._weather_date_changed({"current": {"time": timestamp}, "utc_offset_seconds": offset}), expected)
                    clock.now.assert_called_once_with(main.timezone.utc)

    def test_missing_or_invalid_timezone_does_not_force_a_refresh(self):
        for offset in (None, True, "bad", 86400, -86400, float("nan")):
            self.assertFalse(main._weather_date_changed({"current": {"time": "2026-09-13T10:00"}, "utc_offset_seconds": offset}))
        self.assertFalse(main._weather_date_changed({"utc_offset_seconds": 0}))

    def test_sun_event_placeholders_are_distinguished_from_real_midnight_events(self):
        for sunrise, sunset, expected in (
            ("2026-11-17T00:00", "2026-11-17T00:00", ("-", "-")),  # Polar night
            ("2026-11-17T00:00", "2026-11-18T00:00", ("-", "-")),  # Polar day
            ("2026-11-17T00:00", "2026-11-17T23:58", ("00:00", "23:58")),
            ("2026-11-17T00:03", "2026-11-18T00:00", ("00:03", "00:00")),
            ("2026-11-17T00:00", None, ("00:00", "-")),
            ("2026-11-17T00:00+03:00", "2026-11-18T00:00+02:00", ("00:00", "00:00")),
            ("2026-11-18T00:00", "2026-11-18T00:00", ("00:00", "00:00")),
            ("2026-11-17T12:20", "2026-11-17T14:02", ("12:20", "14:02")),
        ):
            with self.subTest(sunrise=sunrise, sunset=sunset):
                daily = {
                    "time": ["2026-11-16", "2026-11-17"],
                    "sunrise": ["2026-11-16T06:00", sunrise],
                    "sunset": ["2026-11-16T18:00", sunset],
                }
                self.assertEqual(main._format_sun_events(daily, 1), expected)
