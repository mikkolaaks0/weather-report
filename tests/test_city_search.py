import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main
from city_search import CitySearch


def place(name="Helsinki", latitude=60.17, longitude=24.94):
    return {"name": name, "latitude": latitude, "longitude": longitude,
            "admin1": "Uusimaa", "country": "Suomi"}


class LocationSearchTests(unittest.TestCase):
    def test_validated_results_are_deduplicated_without_reordering_relevance(self):
        helsinki = place()
        results = [place("Helsingborg"), None, {"name": "Broken"}, helsinki, helsinki]
        with patch.object(main, "_get_json", return_value={"results": results}) as get:
            self.assertEqual(main.search_cities("  HELSINKI "), [place("Helsingborg"), helsinki])
        self.assertEqual(get.call_args.args[1]["count"], 5)
        self.assertEqual(get.call_args.args[1]["name"], "HELSINKI")

    def test_suggestions_keep_service_order_and_never_exceed_five(self):
        results = [place(f"Hel{i}", longitude=i) for i in range(8)]
        with patch.object(main, "_get_json", return_value={"results": results}):
            self.assertEqual(main.search_cities("Hel"), results[:5])
        with patch.object(main, "_get_json", return_value={}):
            self.assertEqual(main.search_cities("Hel"), [])

    def test_saved_location_is_whitelisted_and_must_match_city(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(main, "SETTINGS_PATH", path):
                main.save_settings({"city": "Helsinki", "place": {**place(), "extra": "ignored"}})
                self.assertEqual(main.load_settings()["place"], place())
                for value in (place("Espoo"), place(latitude=100), None, {"name": "Helsinki"}):
                    main.save_settings({"city": "Helsinki", "place": value})
                    self.assertNotIn("place", main.load_settings())

    def test_selected_location_reaches_worker_without_name_lookup(self):
        widget = object.__new__(main.WeatherWidget)
        widget._call_on_ui_thread = lambda callback: callback()
        widget._handle_weather_result = Mock()
        weather = {"current": {"weather_code": 3, "temperature_2m": 18}, "daily": {"time": ["2026-09-03"]}}
        selected = place("Richmond", 49.17, -123.14)
        with patch.object(main, "geocode_city") as geocode, patch.object(main, "get_weather", return_value=weather) as get:
            widget._fetch_worker("Richmond", "celsius", selected)
        geocode.assert_not_called()
        get.assert_called_once_with(49.17, -123.14, "celsius")
        widget._handle_weather_result.assert_called_once_with(selected, weather, "Richmond")

    def test_queued_search_keeps_latest_coordinates(self):
        widget = object.__new__(main.WeatherWidget)
        widget.fetch_in_progress = True
        widget._is_destroying = False
        widget.status_var = Mock()
        widget.popup_bg_canvas = Mock()
        widget.hero_updated_label = 1
        selected = place("Richmond", 49.17, -123.14)
        widget.refresh_weather("Richmond", place("Richmond", 37.54, -77.43))
        widget.refresh_weather("Richmond", selected)
        widget.refresh_weather = Mock()
        widget._run_pending_city_search()
        widget.refresh_weather.assert_called_once_with("Richmond", selected)
        self.assertIsNone(widget.pending_city_place)

    def test_latest_free_text_search_clears_queued_coordinates(self):
        widget = object.__new__(main.WeatherWidget)
        widget.fetch_in_progress = True
        widget.status_var = Mock()
        widget.popup_bg_canvas = Mock()
        widget.hero_updated_label = 1
        widget.refresh_weather("Helsinki", place())
        widget.refresh_weather("Espoo")
        self.assertIsNone(widget.pending_city_place)
        self.assertEqual(widget.pending_city_search, "Espoo")

    def test_runtime_signature_includes_autocomplete_module(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(main, "PROJECT_DIR", root), patch.object(main, "IS_FROZEN", False):
                original = main._runtime_file_signature()
                (root / "city_search.py").write_text("pass", encoding="utf-8")
                self.assertNotEqual(main._runtime_file_signature(), original)


@unittest.skipUnless(os.name == "nt", "Windows Tk interaction tests")
class AutocompleteTests(unittest.TestCase):
    def test_hover_only_updates_selection_when_the_row_changes(self):
        self.variable.set("Hel")
        self.control._request()
        self.control._receive(self.control.generation, [place(), place("Helsingborg")], False)
        with (
            patch.object(self.control.listbox, "nearest", return_value=1),
            patch.object(self.control, "_select", wraps=self.control._select) as select,
        ):
            for _ in range(20):
                self.control._hover(SimpleNamespace(y=25))
            select.assert_called_once_with(1)
        self.assertEqual(self.control.listbox.curselection(), (1,))
        self.assertEqual(self.control.listbox.index("active"), 1)
        self.control.confirm()
        self.submit.assert_called_once_with("Helsingborg", place("Helsingborg"))

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.canvas = tk.Canvas(self.root, width=584, height=329)
        self.canvas.pack()
        self.variable = tk.StringVar(self.root)
        self.entry = tk.Entry(self.canvas, textvariable=self.variable)
        self.entry.place(x=350, y=12, width=140, height=26)
        self.button = tk.Button(self.canvas)
        self.workers = []
        self.search = Mock(return_value=[place(), place("Helsingborg")])
        self.submit = Mock()
        self.control = CitySearch(
            self.canvas, self.entry, self.variable, self.button,
            search=self.search, submit=self.submit, dispatch=lambda callback: callback(),
            start_worker=self.workers.append, font=("Segoe UI", 10),
            background="#173B49", max_query_length=120,
        )
        self.root.update_idletasks()

    def tearDown(self):
        self.root.destroy()

    def finish_request(self):
        self.workers.pop(0)()

    def results_for(self, query="Hel"):
        self.variable.set(query)
        self.control._request()
        self.finish_request()

    def test_typing_is_debounced_and_short_queries_do_not_request(self):
        self.variable.set("H")
        self.assertIsNone(self.control.debounce_job)
        self.variable.set("He")
        old_job = self.control.debounce_job
        self.variable.set("Hel")
        self.assertNotEqual(self.control.debounce_job, old_job)
        self.assertNotIn(old_job, self.root.tk.call("after", "info"))
        self.assertEqual(self.workers, [])
        self.control._request()
        self.finish_request()
        self.search.assert_called_once_with("Hel")

    def test_repeated_query_uses_cached_suggestions_and_keeps_keyboard_selection(self):
        self.results_for()
        self.control.dismiss()
        self.variable.set("  Hel  ")
        self.control._request()
        self.assertEqual(self.workers, [])
        self.search.assert_called_once_with("Hel")
        self.assertIsNone(self.control.debounce_job)
        self.assertFalse(self.control.inflight)
        self.assertFalse(self.control.ready)
        self.assertTrue(self.control.complete)
        self.control._move(1)
        self.control.confirm()
        self.submit.assert_called_once_with("Helsingborg", place("Helsingborg"))

    def test_enter_can_confirm_a_cached_query_without_starting_a_worker(self):
        self.results_for()
        self.variable.set("Hel")
        self.control.confirm()
        self.assertEqual(self.workers, [])
        self.submit.assert_called_once_with("Helsinki", place())
        self.assertFalse(self.control.confirm_pending)
        self.assertFalse(self.control.editing)
        self.assertFalse(self.control.winfo_manager())

    def test_cache_expires_from_network_response_not_last_use(self):
        with patch("city_search.monotonic", return_value=100) as now:
            self.results_for()
            now.return_value = 100 + self.control.CACHE_TTL_SECONDS - 1
            self.variable.set("Hel")
            self.control._request()
            self.assertEqual(self.workers, [])
            now.return_value += 1
            self.variable.set("Hel")
            self.control._request()
            self.assertEqual(len(self.workers), 1)
            self.finish_request()
        self.assertEqual(self.search.call_count, 2)

    def test_cache_evicts_least_recently_used_query(self):
        with patch.object(self.control, "CACHE_LIMIT", 2):
            self.results_for("Hel")
            self.results_for("Esp")
            self.variable.set("Hel")
            self.control._request()
            self.results_for("Tam")
            self.assertEqual(list(self.control._query_cache), ["Hel", "Tam"])
            self.results_for("Esp")
            self.assertEqual(len(self.control._query_cache), 2)
        self.assertEqual([call.args[0] for call in self.search.call_args_list], ["Hel", "Esp", "Tam", "Esp"])

    def test_empty_and_failed_queries_are_not_cached(self):
        for error in (False, True):
            with self.subTest(error=error):
                self.search.side_effect = OSError("offline") if error else None
                self.search.return_value = []
                self.results_for("Unknown")
                self.assertFalse(self.control._query_cache)
                self.search.side_effect = None
                self.search.return_value = [place()]
                self.results_for("Unknown")
                self.assertEqual(self.control.rows, [place()])
                self.control._query_cache.clear()

    def test_cached_rows_are_independent_of_displayed_and_service_results(self):
        self.results_for()
        self.search.return_value[0]["name"] = "Modified"
        self.control.rows[1]["name"] = "Modified"
        for _ in range(2):
            self.variable.set("Hel")
            self.control._request()
            self.assertEqual(self.control.rows, [place(), place("Helsingborg")])
            self.control.rows[0]["name"] = "Modified again"
        self.search.assert_called_once_with("Hel")

    def test_cached_confirmation_still_wins_over_an_inflight_different_query(self):
        self.results_for("Hel")
        self.variable.set("Esp")
        self.control._request()
        self.variable.set("Hel")
        self.control.confirm()
        self.assertEqual(len(self.workers), 1)
        self.submit.assert_called_once_with("Helsinki", place())
        self.assertTrue(self.control.inflight)
        self.search.return_value = [place("Espoo")]
        self.finish_request()
        self.assertEqual(self.workers, [])
        self.submit.assert_called_once_with("Helsinki", place())
        self.assertNotIn("Esp", self.control._query_cache)
        self.assertFalse(self.control.inflight)

    def test_editing_after_cached_results_still_waits_for_only_one_network_request(self):
        self.results_for("Hel")
        self.variable.set("Esp")
        self.control._request()
        self.variable.set("Hel")
        self.control._request()
        self.assertEqual(self.control.rows, [place(), place("Helsingborg")])
        self.assertTrue(self.control.inflight)
        self.variable.set("Tam")
        self.control.confirm()
        self.assertEqual(len(self.workers), 1)
        self.search.return_value = [place("Espoo")]
        self.finish_request()
        self.submit.assert_not_called()
        self.assertEqual(len(self.workers), 1)
        self.search.return_value = [place("Tampere")]
        self.finish_request()
        self.submit.assert_called_once_with("Tampere", place("Tampere"))
        self.assertFalse(self.control.inflight)

    def test_unchanged_layout_preserves_rows_selection_and_scroll_position(self):
        self.results_for()
        self.control._select(1)
        self.control.listbox.xview_moveto(0.25)
        scroll = self.control.listbox.xview()
        with (
            patch.object(self.control.listbox, "delete", wraps=self.control.listbox.delete) as delete,
            patch.object(self.control.listbox, "insert", wraps=self.control.listbox.insert) as insert,
            patch.object(self.control, "_select", wraps=self.control._select) as select,
        ):
            for _ in range(5):
                self.control.reposition()
            delete.assert_not_called()
            insert.assert_not_called()
            select.assert_not_called()
        self.assertEqual(self.control.listbox.curselection(), (1,))
        self.assertEqual(self.control.listbox.index("active"), 1)
        self.assertEqual(self.control.listbox.xview(), scroll)

    def test_resizing_rebuilds_labels_only_when_needed_and_preserves_selection(self):
        self.results_for()
        self.control._select(1)
        with patch.object(self.canvas, "winfo_width", return_value=400):
            self.control.reposition()
            full_labels = self.control.listbox.get(0, "end")
            self.assertEqual(full_labels[0], "Helsinki, Uusimaa, Suomi")
        with patch.object(self.canvas, "winfo_width", return_value=100):
            self.control.reposition()
        self.assertNotEqual(self.control.listbox.get(0, "end"), full_labels)
        self.assertTrue(all(label.endswith("...") for label in self.control.listbox.get(0, "end")))
        self.assertEqual(self.control.listbox.curselection(), (1,))
        self.control.confirm()
        self.submit.assert_called_once_with("Helsingborg", place("Helsingborg"))

    def test_edit_state_is_kept_until_confirmation_finishes(self):
        self.assertFalse(self.control.editing)
        self.variable.set("Hel")
        self.assertTrue(self.control.editing)
        self.control.confirm()
        self.assertTrue(self.control.editing)
        self.finish_request()
        self.assertFalse(self.control.editing)
        self.assertTrue(self.entry.bind("<KP_Enter>"))

    def test_free_text_confirmation_also_finishes_edit_state(self):
        self.search.return_value = []
        self.results_for("Missing")
        self.assertTrue(self.control.editing)
        self.control.confirm()
        self.assertFalse(self.control.editing)

    def test_enter_uses_first_suggestion_and_returns_full_name(self):
        self.results_for()
        self.assertEqual(self.control.listbox.curselection(), (0,))
        self.assertEqual(self.control.confirm(), "break")
        self.submit.assert_called_once_with("Helsinki", place())
        self.assertEqual(self.variable.get(), "Helsinki")
        self.assertFalse(self.control.winfo_manager())
        self.assertIsNone(self.control.debounce_job)

    def test_enter_before_debounce_waits_for_first_current_result(self):
        self.variable.set("Espoo")
        self.search.return_value = [place("Espoo")]
        self.control.confirm()
        self.control.confirm()
        self.submit.assert_not_called()
        self.assertEqual(len(self.workers), 1)
        self.finish_request()
        self.submit.assert_called_once_with("Espoo", place("Espoo"))

    def test_confirmation_blurs_field_without_canceling_pending_lookup(self):
        self.variable.set("Hel")
        with (
            patch.object(self.canvas, "focus_set") as focus,
            patch.object(self.entry, "selection_clear") as selection,
            patch.object(self.control, "focus_get", return_value=self.entry),
        ):
            self.control.confirm()
            focus.assert_called_once()
            selection.assert_called_once()
        with patch.object(self.control, "focus_get", return_value=self.canvas):
            self.control._check_focus()
        self.assertTrue(self.control.confirm_pending)
        self.finish_request()
        self.submit.assert_called_once_with("Helsinki", place())

    def test_confirming_visible_result_also_finishes_editing(self):
        self.results_for()
        with patch.object(self.canvas, "focus_set") as focus, patch.object(self.control, "focus_get", return_value=self.entry):
            self.control.confirm()
        focus.assert_called_once()
        self.assertFalse(self.control.confirm_pending)

    def test_confirmed_search_survives_hiding_and_never_steals_focus_on_completion(self):
        for action in ("hide", "focus_out", "outside_click"):
            with self.subTest(action=action):
                self.variable.set("Hel " + action)
                self.control.confirm()
                with patch.object(self.control, "focus_get", return_value=None), patch.object(self.canvas, "focus_set") as focus:
                    if action == "hide":
                        self.control.hide()
                    elif action == "focus_out":
                        self.control._check_focus()
                    else:
                        self.control._outside_click(SimpleNamespace(widget=self.canvas))
                    self.assertTrue(self.control.confirm_pending)
                    self.assertFalse(self.control.winfo_manager())
                    self.control.reposition()
                    self.assertFalse(self.control.winfo_manager())
                    self.finish_request()
                    focus.assert_not_called()
                self.submit.assert_called_once_with("Helsinki", place())
                self.submit.reset_mock()

    def test_hiding_unconfirmed_suggestions_discards_their_late_result(self):
        self.variable.set("Hel")
        self.control._request()
        self.control.hide()
        self.finish_request()
        self.assertFalse(self.control.winfo_manager())
        self.assertEqual(self.control.rows, [])
        self.submit.assert_not_called()

    def test_worker_start_failure_allows_the_next_lookup(self):
        self.variable.set("Hel")
        with patch.object(self.control, "start_worker", side_effect=RuntimeError("thread limit")):
            self.control._request()
        self.assertFalse(self.control.inflight)
        self.results_for("Espoo")
        self.assertTrue(self.control.rows)

    def test_arrows_and_enter_choose_another_result(self):
        self.results_for()
        self.control._move(1)
        self.control.confirm()
        self.submit.assert_called_once_with("Helsingborg", place("Helsingborg"))

    def test_mouse_click_confirms_the_clicked_row(self):
        self.results_for()
        with patch.object(self.control.listbox, "nearest", return_value=1):
            self.control._click(SimpleNamespace(y=28))
        self.submit.assert_called_once_with("Helsingborg", place("Helsingborg"))

    def test_escape_cancels_pending_enter_and_late_response(self):
        self.variable.set("Hel")
        self.control.confirm()
        self.assertEqual(self.control.handle_escape(), "break")
        self.finish_request()
        self.submit.assert_not_called()
        self.assertFalse(self.control.winfo_manager())
        self.assertIsNone(self.control.handle_escape())

    def test_newer_query_wins_and_only_one_network_request_runs(self):
        self.variable.set("Hel")
        self.control._request()
        self.variable.set("Espoo")
        self.control.confirm()
        self.assertEqual(len(self.workers), 1)
        self.finish_request()
        self.submit.assert_not_called()
        self.assertEqual(len(self.workers), 1)
        self.search.return_value = [place("Espoo")]
        self.finish_request()
        self.submit.assert_called_once_with("Espoo", place("Espoo"))

    def test_edit_after_enter_cancels_automatic_confirmation(self):
        self.variable.set("Hel")
        self.control.confirm()
        self.variable.set("Espoo")
        self.finish_request()
        self.submit.assert_not_called()
        self.assertEqual(self.workers, [])
        self.assertIsNotNone(self.control.debounce_job)

    def test_empty_or_failed_suggestions_fall_back_only_on_confirmation(self):
        for error in (False, True):
            with self.subTest(error=error):
                self.search.side_effect = OSError("offline") if error else None
                self.search.return_value = []
                self.results_for("Unknown")
                self.submit.assert_not_called()
                self.assertTrue(self.control.message.winfo_manager())
                self.control.confirm()
                self.submit.assert_called_once_with("Unknown", None)
                self.submit.reset_mock()

    def test_no_results_after_early_enter_falls_back(self):
        self.search.return_value = []
        self.variable.set("Unknown")
        self.control.confirm()
        self.finish_request()
        self.submit.assert_called_once_with("Unknown", None)

    def test_programmatic_update_never_opens_suggestions(self):
        self.control.set_text("Helsinki", place())
        self.assertIsNone(self.control.debounce_job)
        self.assertFalse(self.control.winfo_manager())
        self.control.confirm()
        self.submit.assert_called_once_with("Helsinki", place())
        self.search.assert_not_called()

    def test_dismissed_dropdown_does_not_reappear_during_layout(self):
        self.results_for()
        self.control.dismiss()
        self.control.reposition()
        self.assertFalse(self.control.winfo_manager())
        self.control._outside_click(SimpleNamespace(widget=self.entry))
        self.control._outside_click(SimpleNamespace(widget=self.button))

    def test_destroy_cancels_callbacks_and_ignores_outstanding_result(self):
        self.variable.set("Hel")
        self.control._request()
        self.control.destroy()
        self.finish_request()
        self.variable.set("Espoo")
        self.submit.assert_not_called()
        self.assertEqual(self.workers, [])

    def test_long_input_is_not_sent_to_suggestion_service(self):
        query = "a" * 121
        self.variable.set(query)
        self.assertIsNone(self.control.debounce_job)
        self.control.confirm()
        self.submit.assert_called_once_with(query, None)
        self.search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
