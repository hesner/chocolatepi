"""
server.py integration tests: a real ThreadingHTTPServer, real HTTP
requests over a real socket (localhost, an ephemeral port) -- the one
place the unit tests elsewhere don't reach, since api.py's tests call
its methods directly rather than through the HTTP/routing/cookie layer.

Only `usb_mount`'s actual `sudo mount` call is mocked (no real mount in
a test); everything else -- routing, JSON (de)serialization, session
cookies, the upload streaming path and its Content-Length bounding --
runs for real.

Run with: python -m unittest tests/test_admin_server_integration.py
"""

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from admin.api import AdminAPI, AdminConfig  # noqa: E402
from admin.server import make_handler_class  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402


class ServerIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        remount_patcher = patch("admin.usb_mount._remount")
        remount_patcher.start()
        self.addCleanup(remount_patcher.stop)

        self.tmpdir = tempfile.TemporaryDirectory()
        api = AdminAPI(AdminConfig(usb_root=self.tmpdir.name))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler_class(api))
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmpdir.cleanup()

    def _conn(self):
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)

    def _json(self, conn, method, path, body=None, headers=None):
        headers = dict(headers or {})
        payload = json.dumps(body).encode("utf-8") if body is not None else b""
        if body is not None:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        parsed = json.loads(data) if data else {}
        return resp, parsed


class TestAuthFlow(ServerIntegrationTestCase):
    def test_status_reports_first_run_before_any_pin(self):
        conn = self._conn()
        resp, body = self._json(conn, "GET", "/api/status")
        self.assertEqual(resp.status, 200)
        self.assertTrue(body["first_run"])

    def test_protected_endpoint_without_session_is_401(self):
        conn = self._conn()
        resp, body = self._json(conn, "GET", "/api/shows")
        self.assertEqual(resp.status, 401)

    def test_full_pin_then_login_then_authenticated_request(self):
        conn = self._conn()
        resp, _ = self._json(conn, "POST", "/api/pin", {"pin": "1234"})
        self.assertEqual(resp.status, 200)

        resp, _ = self._json(conn, "POST", "/api/login", {"pin": "1234"})
        self.assertEqual(resp.status, 200)
        set_cookie = resp.getheader("Set-Cookie")
        self.assertIsNotNone(set_cookie)
        cookie_value = set_cookie.split(";")[0]

        resp, body = self._json(conn, "GET", "/api/shows", headers={"Cookie": cookie_value})
        self.assertEqual(resp.status, 200)
        self.assertEqual(body["shows"], [])

    def test_login_with_wrong_pin_is_401(self):
        conn = self._conn()
        self._json(conn, "POST", "/api/pin", {"pin": "1234"})
        resp, body = self._json(conn, "POST", "/api/login", {"pin": "0000"})
        self.assertEqual(resp.status, 401)


class TestLibraryFlow(ServerIntegrationTestCase):
    def _authenticated_conn(self):
        conn = self._conn()
        self._json(conn, "POST", "/api/pin", {"pin": "1234"})
        resp, _ = self._json(conn, "POST", "/api/login", {"pin": "1234"})
        cookie_value = resp.getheader("Set-Cookie").split(";")[0]
        return conn, {"Cookie": cookie_value}

    def test_create_show_and_list_it(self):
        conn, headers = self._authenticated_conn()

        resp, _ = self._json(conn, "POST", "/api/shows", {"name": "Live"}, headers)
        self.assertEqual(resp.status, 201)

        resp, body = self._json(conn, "GET", "/api/shows", headers=headers)
        self.assertEqual(body["shows"], ["Live"])

    def test_upload_track_via_raw_body_with_headers(self):
        conn, headers = self._authenticated_conn()
        self._json(conn, "POST", "/api/shows", {"name": "Live"}, headers)
        self._json(conn, "POST", "/api/shows/Live/sets", {"number": 1}, headers)

        file_bytes = b"fake mp3 bytes" * 1000
        upload_headers = dict(headers)
        upload_headers["X-Track-Name"] = "My Song"
        upload_headers["X-Track-Extension"] = "mp3"
        upload_headers["Content-Length"] = str(len(file_bytes))
        conn.request("POST", "/api/shows/Live/sets/1/tracks/A", body=file_bytes, headers=upload_headers)
        resp = conn.getresponse()
        body = json.loads(resp.read())

        self.assertEqual(resp.status, 200)
        self.assertTrue(body["ok"])
        self.assertIsNone(body["warning"])  # mp3 has no video codec to warn about

        resp, tracks = self._json(conn, "GET", "/api/shows/Live/sets/1/tracks", headers=headers)
        self.assertEqual(tracks["A"]["display_name"], "My Song")

    def test_static_index_is_served_at_root(self):
        conn = self._conn()
        conn.request("GET", "/")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIn(b"Setlist Admin", resp.read())

    def test_path_traversal_on_static_files_is_rejected(self):
        conn = self._conn()
        conn.request("GET", "/static/../../../etc/passwd")
        resp = conn.getresponse()
        resp.read()
        self.assertNotEqual(resp.status, 200)


if __name__ == "__main__":
    unittest.main()
