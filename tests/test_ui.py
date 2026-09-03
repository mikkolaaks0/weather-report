import os
import unittest
from unittest.mock import Mock, patch

import main


@unittest.skipUnless(os.name == "nt" and main.ImageTk is not None, "Windows Tk/Pillow smoke test")
class PopupSmokeTests(unittest.TestCase):
    def test_weather_refresh_preserves_suggestions_and_hae_confirms_selection(self) -> None:
        settings = {"city": "Espoo", "temperature_unit": "celsius", "popup_theme": main.DEFAULT_POPUP_THEME}
        espoo = {"name": "Espoo", "latitude": 60.20, "longitude": 24.65}
        espoonlahti = {"name": "Espoonlahti", "latitude": 60.15, "longitude": 24.65}
        weather = {"current": {"weather_code": 3, "temperature_2m": 18}, "daily": {"time": ["2026-09-04"]}}
        with (
            patch.object(main, "load_settings", return_value=settings),
            patch.object(main, "save_settings"),
            patch.object(main, "is_startup_enabled", return_value=False),
            patch.object(main.WeatherWidget, "_init_tray_icon"),
            patch.object(main.WeatherWidget, "_start_background_worker") as worker,
        ):
            widget = main.WeatherWidget()
            try:
                widget._apply_weather(espoo, weather, "Espoo")
                widget.detail_city_var.set("Espoo")
                control = widget.city_search
                control._request()
                generation = control.generation
                control._receive(generation, [espoo, espoonlahti], False)
                control._move(1)
                widget._handle_weather_result(espoo, weather, "Espoo")
                self.assertEqual(control.generation, generation)
                self.assertEqual(control.listbox.curselection(), (1,))
                widget._fetch_worker = Mock()
                widget.search_button.invoke()
                self.assertEqual(widget.detail_city_var.get(), "Espoonlahti")
                self.assertFalse(control.editing)
                worker.call_args.args[0]()
                widget._fetch_worker.assert_called_once_with("Espoonlahti", "celsius", espoonlahti)

                # A same-name background refresh must not cancel an early Enter.
                widget._handle_weather_result(espoonlahti, weather, "Espoonlahti")
                widget.detail_city_var.set("Espoonlahti")
                control.confirm()
                generation = control.generation
                widget._handle_weather_result(espoonlahti, weather, "Espoonlahti")
                self.assertEqual(control.generation, generation)
                self.assertTrue(control.confirm_pending)
                control._receive(generation, [espoonlahti], False)
                self.assertFalse(control.confirm_pending)
                self.assertFalse(widget.winfo_viewable())
                self.assertFalse(widget.popup.winfo_viewable())
            finally:
                widget.destroy()

    def test_current_and_forecast_data_render_in_a_hidden_real_tk_popup(self) -> None:
        settings = {"city": "Espoo", "temperature_unit": "celsius", "popup_theme": main.DEFAULT_POPUP_THEME}
        dates = [f"2026-09-{day:02}" for day in range(2, 9)]
        weather = {
            "current": {"weather_code": 3, "temperature_2m": 18, "is_day": 1},
            "daily": {
                "time": dates,
                "weather_code": [3, 0, 2, 61, 71, 95, 45],
                "temperature_2m_min": [10] * 7,
                "temperature_2m_max": [20] * 7,
            },
        }
        with (
            patch.object(main, "load_settings", return_value=settings),
            patch.object(main, "save_settings"),
            patch.object(main, "is_startup_enabled", return_value=False),
            patch.object(main.WeatherWidget, "_init_tray_icon"),
            patch.object(main.WeatherWidget, "_start_background_worker"),
        ):
            widget = main.WeatherWidget()
            try:
                widget._layout_popup_content(584, 329)
                widget._apply_weather({"name": "Espoo", "admin1": "Uusimaa"}, weather, "Espoo")
                canvas = widget.popup_bg_canvas
                self.assertEqual(canvas.itemcget(widget.hero_temp_label, "text"), "18\N{DEGREE SIGN}C")
                self.assertEqual(canvas.itemcget(widget.footer_label, "text"), main.FOOTER_TEXT)
                icon_items = [(widget.hero_icon_label, (87, 84))]
                for index, card in enumerate(widget.forecast_cards):
                    expected_day = main.WEEKDAY_SHORT_FI[main.datetime.fromisoformat(dates[index + 1]).weekday()]
                    self.assertEqual(canvas.itemcget(card["day"], "text"), expected_day)
                    self.assertEqual(canvas.itemcget(card["temp"], "text"), "20\N{DEGREE SIGN}C / 10\N{DEGREE SIGN}C")
                    icon_items.append((card["icon"], (43, 39)))
                for item, expected_size in icon_items:
                    x1, y1, x2, y2 = canvas.bbox(item)
                    self.assertEqual((x2 - x1, y2 - y1), expected_size)

                with patch.object(main.messagebox, "showerror") as dialog:
                    widget._show_error("Network error")
                self.assertEqual(canvas.itemcget(widget.hero_updated_label, "text"), "Päivitys epäonnistui")
                self.assertEqual(canvas.itemcget(widget.hero_temp_label, "text"), "18\N{DEGREE SIGN}C")
                self.assertIs(widget.latest_weather, weather)
                dialog.assert_not_called()
                widget._apply_weather({"name": "Espoo", "admin1": "Uusimaa"}, weather, "Espoo")
                self.assertTrue(canvas.itemcget(widget.hero_updated_label, "text").startswith("Päivitetty "))
                self.assertFalse(widget.winfo_viewable())
                self.assertFalse(widget.popup.winfo_viewable())

                long_place = {"name": "Lappeenranta", "admin1": "Etelä-Karjala", "latitude": 61.05, "longitude": 28.18}
                weather["current"]["weather_code"] = 99
                widget._apply_weather(long_place, weather, "Lappeenranta")
                self.assertEqual(widget.settings["place"], long_place)
                self.assertEqual(widget.settings["city"], "Lappeenranta")
                self.assertLess(canvas.bbox(widget.hero_city_label)[2], canvas.bbox(widget.today_condition_label)[0])
                weather["current"]["weather_code"] = 3
                widget._apply_weather({"name": "Espoo", "admin1": "Uusimaa"}, weather, "Espoo")
                self.assertEqual(canvas.itemcget(widget.hero_city_label, "text"), "Espoo, Uusimaa")
                widget._layout_popup_content(450, 329)
                self.assertLess(canvas.bbox(widget.hero_city_label)[2], canvas.bbox(widget.today_condition_label)[0])
            finally:
                widget.destroy()
