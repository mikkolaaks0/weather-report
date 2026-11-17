import io
import threading
import unittest
from datetime import datetime, timedelta
from email.message import Message
from http.client import IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request
from urllib.response import addinfourl

import main


class HTTPClientTests(unittest.TestCase):
    def setUp(self):
        # Keep transport fixtures on loopback even on machines with a proxy.
        bypass = patch.dict(main.os.environ, {
            "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
        })
        bypass.start()
        self.addCleanup(bypass.stop)

    def serve(self, replies):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                index = len(requests)
                requests.append(self.path)
                headers, body = replies[min(index, len(replies) - 1)]
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Connection", "close")
                for name, value in headers:
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()
                self.close_connection = True

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        worker.start()

        def close():
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)

        self.addCleanup(close)
        return f"http://127.0.0.1:{server.server_port}/", requests

    def test_truncated_json_is_a_transport_error(self):
        body = b'{"value":'
        url, requests = self.serve([([("Content-Length", "30")], body)])
        with self.assertRaises(IncompleteRead) as raised:
            main._get_json(url, {})
        self.assertEqual(raised.exception.partial, body)
        self.assertEqual(raised.exception.expected, 30 - len(body))
        self.assertEqual(len(requests), 1)

    def test_valid_json_shorter_than_content_length_is_not_accepted(self):
        body = b'{"ok": true}'
        url, _requests = self.serve([([("Content-Length", str(len(body) + 10))], body)])
        with self.assertRaises(IncompleteRead) as raised:
            main._get_json(url, {})
        self.assertEqual(raised.exception.partial, body)
        self.assertEqual(raised.exception.expected, 10)

    def test_truncated_body_retries_and_accepts_the_complete_response(self):
        complete = b'{"ok": true}'
        url, requests = self.serve([
            ([("Content-Length", "30")], b'{"value":'),
            ([("Content-Length", str(len(complete)))], complete),
        ])
        with patch.object(main.time, "sleep") as sleep:
            result = main._request_with_retry(lambda: main._get_json(url, {}))
        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(requests), 2)
        sleep.assert_called_once_with(1.0)

    def test_a_complete_body_without_content_length_is_accepted(self):
        url, requests = self.serve([([], b'{"ok": true}')])
        self.assertEqual(main._get_json(url, {}), {"ok": True})
        self.assertEqual(requests, ["/"])

    def test_chunked_framing_takes_precedence_over_content_length(self):
        body = b'{"ok": true}'
        chunked = f"{len(body):X}\r\n".encode("ascii") + body + b"\r\n0\r\n\r\n"
        url, _requests = self.serve([
            ([("Transfer-Encoding", "chunked"), ("Content-Length", "100")], chunked),
        ])
        with patch.object(main, "MAX_JSON_RESPONSE_BYTES", 32):
            self.assertEqual(main._get_json(url, {}), {"ok": True})

    def test_over_limit_declared_length_is_rejected_without_waiting_for_body(self):
        request = Request("https://example.invalid")
        response = self.https_response(request, 200)
        response.length = 1024
        response.read = Mock(side_effect=AssertionError("oversized response body was read"))
        with (
            patch.object(main, "MAX_JSON_RESPONSE_BYTES", 32),
            patch.object(main, "_open_weather_request", return_value=response),
            self.assertRaisesRegex(main.WeatherServiceError, "liian suuri"),
        ):
            main._get_json(request.full_url, {})
        self.assertTrue(response.closed)
        response.read.assert_not_called()

    def test_an_oversized_body_is_not_retried_as_a_truncated_response(self):
        body = b'{"value": "' + b"x" * 60 + b'"}'
        url, requests = self.serve([([("Content-Length", str(len(body)))], body)])
        with (
            patch.object(main, "MAX_JSON_RESPONSE_BYTES", 32),
            patch.object(main.time, "sleep") as sleep,
            self.assertRaisesRegex(main.WeatherServiceError, "liian suuri"),
        ):
            main._request_with_retry(lambda: main._get_json(url, {}))
        self.assertEqual(len(requests), 1)
        sleep.assert_not_called()

    @staticmethod
    def https_response(request, code, body=b"", headers=()):
        message = Message()
        message["Content-Type"] = "application/json"
        for name, value in headers:
            message[name] = value
        response = addinfourl(io.BytesIO(body), message, request.full_url, code)
        response.msg = "Found" if code != 200 else "OK"
        return response

    def test_https_downgrades_are_blocked_before_any_plaintext_request(self):
        plaintext_url, requests = self.serve([([], b'{"downgraded": true}')])
        targets = (plaintext_url, plaintext_url.replace("http://", "ftp://", 1))
        for code in (301, 302, 303, 307, 308):
            for target in targets:
                with self.subTest(code=code, target=target):
                    responses = []

                    def fake_https_open(handler, request):
                        response = self.https_response(request, code, headers=[("Location", target)])
                        responses.append(response)
                        return response

                    with (
                        patch.object(HTTPSHandler, "https_open", fake_https_open),
                        patch.object(main.time, "sleep") as sleep,
                        self.assertRaises(HTTPError) as raised,
                    ):
                        main._request_with_retry(lambda: main._get_json("https://example.invalid/start", {}))
                    self.assertEqual(raised.exception.code, code)
                    self.assertEqual(len(responses), 1)
                    self.assertTrue(responses[0].closed)
                    sleep.assert_not_called()
        self.assertEqual(requests, [])

    def test_https_redirects_preserve_tls_context_headers_and_timeout(self):
        for target in ("https://other.invalid/final", "/final", "//other.invalid/final"):
            with self.subTest(target=target):
                context = main._create_https_context()
                opened = []

                def fake_https_open(handler, request):
                    opened.append((handler._context, request, request.timeout))
                    if len(opened) == 1:
                        return self.https_response(request, 302, headers=[("Location", target)])
                    return self.https_response(request, 200, b'{"ok": true}')

                with (
                    patch.object(main, "_create_https_context", return_value=context),
                    patch.object(HTTPSHandler, "https_open", fake_https_open),
                ):
                    self.assertEqual(main._get_json("https://example.invalid/start", {"q": "Espoo"}), {"ok": True})
                self.assertEqual(len(opened), 2)
                for actual_context, request, timeout in opened:
                    self.assertIs(actual_context, context)
                    self.assertEqual(request.type, "https")
                    self.assertEqual(timeout, 12)
                    self.assertEqual(request.get_header("Accept"), "application/json")
                    self.assertEqual(request.get_header("User-agent"), f"{main.APP_SLUG}-desktop")

    def test_redirect_bodies_are_closed_without_being_read(self):
        for code in (301, 302, 303, 307, 308):
            with self.subTest(code=code):
                redirects = []
                opened = []

                def fake_https_open(handler, request):
                    opened.append(request.full_url)
                    if len(opened) == 1:
                        response = self.https_response(
                            request, code, b"x" * 100_000, [("Location", "/final")],
                        )
                        response.read = Mock(side_effect=AssertionError("redirect body was read"))
                        redirects.append(response)
                        return response
                    return self.https_response(request, 200, b'{"ok": true}')

                with (
                    patch.object(main, "MAX_JSON_RESPONSE_BYTES", 32),
                    patch.object(HTTPSHandler, "https_open", fake_https_open),
                ):
                    self.assertEqual(main._get_json("https://example.invalid/start", {}), {"ok": True})
                self.assertEqual(len(opened), 2)
                self.assertTrue(redirects[0].closed)
                redirects[0].read.assert_not_called()

    def test_308_and_head_redirects_work_with_a_python_310_style_handler(self):
        original_redirect = HTTPRedirectHandler.redirect_request

        def legacy_redirect(handler, request, response, code, message, headers, new_url):
            if code == 308:
                raise HTTPError(request.full_url, code, message, headers, response)
            redirected = original_redirect(handler, request, response, code, message, headers, new_url)
            redirected.__dict__.pop("method", None)  # Python 3.10 creates a default GET Request.
            return redirected

        for method in ("GET", "HEAD"):
            with self.subTest(method=method):
                opened = []

                def fake_https_open(handler, request):
                    opened.append(request.get_method())
                    if len(opened) == 1:
                        return self.https_response(request, 308, headers=[("Location", "/final")])
                    return self.https_response(request, 200, b'{"ok": true}')

                with (
                    patch.object(HTTPRedirectHandler, "redirect_request", legacy_redirect),
                    patch.object(HTTPSHandler, "https_open", fake_https_open),
                    main._open_weather_request(
                        Request("https://example.invalid/start", method=method),
                        timeout=12, context=main._create_https_context(),
                    ) as response,
                ):
                    self.assertEqual(response.status, 200)
                self.assertEqual(opened, [method, method])


class ForecastRequestTests(unittest.TestCase):
    def test_fractional_timezone_range_keeps_the_last_overlapping_hour(self):
        # Open-Meteo can align the hourly range to 02:00 while the displayed
        # current time is already 03:30 in a fractional-offset timezone.
        # The 09:00–10:00 forecast still overlaps the next six hours.
        start = datetime(2026, 11, 18, 2)

        def forecast(_url, params):
            count = params.get("forecast_hours", 24 * params["forecast_days"])
            times = [start + timedelta(hours=index) for index in range(count)]
            return {
                "current": {"time": "2026-11-18T03:30"},
                "hourly": {
                    "time": [time.isoformat(timespec="minutes") for time in times],
                    "precipitation_probability": [90 if time.hour == 10 else 10 for time in times],
                },
                "daily": {"time": [
                    (start.date() + timedelta(days=index)).isoformat()
                    for index in range(params["forecast_days"])
                ]},
            }

        with patch.object(main, "_get_json", side_effect=forecast):
            weather = main.get_weather(27.72, 85.32)
        self.assertEqual(main.max_precipitation_probability_next_hours(weather), 90)
        self.assertEqual(len(weather["daily"]["time"]), 7)
        self.assertLess(len(weather["hourly"]["time"]), 24)
