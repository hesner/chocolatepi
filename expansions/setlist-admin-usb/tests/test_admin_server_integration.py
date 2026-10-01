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
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from admin.api import AdminAPI, AdminConfig  # noqa: E402
from admin.server import make_handler_class, _LimitedReader  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402


class ServerIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        remount_patcher = patch("admin.usb_mount._remount")
        remount_patcher.start()
        self.addCleanup(remount_patcher.stop)

        ensure_mounted_patcher = patch("admin.usb_mount.ensure_mounted")
        ensure_mounted_patcher.start()
        self.addCleanup(ensure_mounted_patcher.stop)

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
        resp, body = self._json(conn, "GET", "/api/sets")
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

        resp, body = self._json(conn, "GET", "/api/sets", headers={"Cookie": cookie_value})
        self.assertEqual(resp.status, 200)
        self.assertEqual(body["sets"], [])

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

    def test_create_set_and_list_it(self):
        conn, headers = self._authenticated_conn()

        resp, _ = self._json(conn, "POST", "/api/sets", {"name": "Live"}, headers)
        self.assertEqual(resp.status, 201)

        resp, body = self._json(conn, "GET", "/api/sets", headers=headers)
        self.assertEqual(body["sets"], ["Live"])

    def test_upload_track_via_raw_body_with_headers(self):
        conn, headers = self._authenticated_conn()
        self._json(conn, "POST", "/api/sets", {"name": "Live"}, headers)
        self._json(conn, "POST", "/api/sets/Live/banks", {"number": 1}, headers)

        file_bytes = b"fake mp3 bytes" * 1000
        upload_headers = dict(headers)
        upload_headers["X-Track-Name"] = "My Song"
        upload_headers["X-Track-Extension"] = "mp3"
        upload_headers["Content-Length"] = str(len(file_bytes))
        conn.request("POST", "/api/sets/Live/banks/1/tracks/A", body=file_bytes, headers=upload_headers)
        resp = conn.getresponse()
        body = json.loads(resp.read())

        self.assertEqual(resp.status, 200)
        self.assertTrue(body["ok"])
        self.assertIsNone(body["warning"])  # mp3 has no video codec to warn about

        resp, tracks = self._json(conn, "GET", "/api/sets/Live/banks/1/tracks", headers=headers)
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

    def test_set_name_needing_url_encoding_round_trips_correctly(self):
        # Real, pre-existing bug found while adding the song library:
        # the frontend calls encodeURIComponent() on Set names, but
        # nothing decoded them server-side, so any name actually
        # needing encoding (any space, in practice) silently broke.
        conn, headers = self._authenticated_conn()
        set_name = "Gira Verano 2026"

        resp, _ = self._json(conn, "POST", "/api/sets", {"name": set_name}, headers)
        self.assertEqual(resp.status, 201)

        import urllib.parse
        encoded = urllib.parse.quote(set_name, safe="")
        resp, body = self._json(conn, "GET", f"/api/sets/{encoded}/banks", headers=headers)
        self.assertEqual(resp.status, 200)
        self.assertEqual(body["banks"], [])

    def test_validation_error_from_library_ops_is_a_400_not_a_500(self):
        # Real, pre-existing bug: LibraryOpsError (raised for almost
        # every invalid-input/name-collision case in library_ops.py)
        # was never translated into an ApiError, so it fell through to
        # server.py's generic 500 "Internal error" -- none of its
        # carefully written user-facing messages ever reached a client.
        conn, headers = self._authenticated_conn()
        self._json(conn, "POST", "/api/sets", {"name": "Live"}, headers)

        resp, body = self._json(conn, "POST", "/api/sets", {"name": "Live"}, headers)

        self.assertEqual(resp.status, 400)
        self.assertIn("already exists", body["error"])

    def test_create_bank_with_null_number_is_a_400_not_a_500(self):
        # Real, pre-existing bug found on real hardware: the frontend's
        # parseInt() can return NaN on unexpected prompt() input (e.g. a
        # stray invisible character from a mobile keyboard), which
        # JSON.stringify() silently turns into `{"number": null}` --
        # int(body.get("number", 0)) then crashed with an unhandled
        # TypeError/500, since .get()'s default only applies when the
        # key is missing, not when it's present but null.
        conn, headers = self._authenticated_conn()
        self._json(conn, "POST", "/api/sets", {"name": "Live"}, headers)

        resp, body = self._json(conn, "POST", "/api/sets/Live/banks", {"number": None}, headers)

        self.assertEqual(resp.status, 400)
        self.assertIn("number", body["error"])


class TestSongLibraryFlow(ServerIntegrationTestCase):
    def _authenticated_conn(self):
        conn = self._conn()
        self._json(conn, "POST", "/api/pin", {"pin": "1234"})
        resp, _ = self._json(conn, "POST", "/api/login", {"pin": "1234"})
        cookie_value = resp.getheader("Set-Cookie").split(";")[0]
        return conn, {"Cookie": cookie_value}

    def test_upload_song_then_list_it(self):
        conn, headers = self._authenticated_conn()
        upload_headers = dict(headers)
        upload_headers["X-Track-Name"] = "My Song"
        upload_headers["X-Track-Extension"] = "mp3"
        body_bytes = b"fake mp3 bytes"
        upload_headers["Content-Length"] = str(len(body_bytes))
        conn.request("POST", "/api/songs", body=body_bytes, headers=upload_headers)
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        resp.read()

        resp, body = self._json(conn, "GET", "/api/songs", headers=headers)
        self.assertEqual(resp.status, 200)
        self.assertEqual([s["filename"] for s in body["songs"]], ["My Song.mp3"])

    def test_assign_from_library_then_appears_in_the_bank(self):
        conn, headers = self._authenticated_conn()
        upload_headers = dict(headers)
        upload_headers["X-Track-Name"] = "Reusable"
        upload_headers["X-Track-Extension"] = "wav"
        body_bytes = b"fake wav bytes"
        upload_headers["Content-Length"] = str(len(body_bytes))
        conn.request("POST", "/api/songs", body=body_bytes, headers=upload_headers)
        conn.getresponse().read()

        self._json(conn, "POST", "/api/sets", {"name": "Live"}, headers)
        self._json(conn, "POST", "/api/sets/Live/banks", {"number": 1}, headers)

        resp, _ = self._json(
            conn, "POST", "/api/sets/Live/banks/1/tracks/A/assign-from-library",
            {"song_filename": "Reusable.wav"}, headers,
        )
        self.assertEqual(resp.status, 200)

        resp, tracks = self._json(conn, "GET", "/api/sets/Live/banks/1/tracks", headers=headers)
        self.assertEqual(tracks["A"]["display_name"], "Reusable")

        # And the library's own copy is still there for the next Set.
        resp, body = self._json(conn, "GET", "/api/songs", headers=headers)
        self.assertEqual([s["filename"] for s in body["songs"]], ["Reusable.wav"])

    def test_save_track_to_library_then_reusable_elsewhere(self):
        conn, headers = self._authenticated_conn()
        self._json(conn, "POST", "/api/sets", {"name": "OldSet"}, headers)
        self._json(conn, "POST", "/api/sets/OldSet/banks", {"number": 1}, headers)
        upload_headers = dict(headers)
        upload_headers["X-Track-Name"] = "From Old Set"
        upload_headers["X-Track-Extension"] = "mp3"
        # Delete it from the library first so this test exercises
        # save-to-library in isolation, not assign_track()'s automatic add.
        body_bytes = b"data"
        upload_headers["Content-Length"] = str(len(body_bytes))
        conn.request("POST", "/api/sets/OldSet/banks/1/tracks/A", body=body_bytes, headers=upload_headers)
        conn.getresponse().read()
        self._json(conn, "DELETE", "/api/songs/From%20Old%20Set.mp3", headers=headers)

        resp, _ = self._json(
            conn, "POST", "/api/sets/OldSet/banks/1/tracks/A/save-to-library", headers=headers,
        )
        self.assertEqual(resp.status, 200)

        resp, body = self._json(conn, "GET", "/api/songs", headers=headers)
        self.assertEqual([s["filename"] for s in body["songs"]], ["From Old Set.mp3"])

    def test_rejected_duplicate_upload_still_returns_a_clean_response(self):
        """Real incident found live on real hardware (2026-10-01): a
        duplicate-name upload is rejected by library_ops.upload_song()
        *before* it ever reads the request body (the name-collision
        check runs first) -- for a real multi-hundred-MB video, sending
        a 400 without first draining the still-unread body left the
        connection in a state the client's own TCP stack treated as
        reset ("Load failed" in Safari), even though the server's
        response itself, with the real rejection reason, was sent
        correctly. _LimitedReader.drain() (see its own unit tests below
        for the precise behavior) fixes this; this just confirms the
        end-to-end response a client actually gets is still well-formed."""
        conn, headers = self._authenticated_conn()
        file_bytes = b"x" * (64 * 1024)
        upload_headers = dict(headers)
        upload_headers["X-Track-Name"] = "Dup"
        upload_headers["X-Track-Extension"] = "mp4"
        upload_headers["Content-Length"] = str(len(file_bytes))

        conn.request("POST", "/api/songs", body=file_bytes, headers=upload_headers)
        resp = conn.getresponse()
        resp.read()
        self.assertEqual(resp.status, 200)

        conn2 = self._conn()
        conn2.request("POST", "/api/songs", body=file_bytes, headers=upload_headers)
        resp = conn2.getresponse()
        body = json.loads(resp.read())
        self.assertEqual(resp.status, 400)
        self.assertIn("already exists", body["error"])


class TestLimitedReaderDrain(unittest.TestCase):
    """_LimitedReader.drain() (server.py) in isolation -- the OS-level
    TCP-reset timing the real incident above depends on isn't reliably
    reproducible in a fast loopback test, so this pins down the actual
    logic fix directly instead: an early rejection must still fully
    consume whatever was left of the request body."""

    def test_drain_consumes_everything_remaining(self):
        stream = io.BytesIO(b"x" * 1000)
        reader = _LimitedReader(stream, total_length=1000)
        reader.read(100)  # a partial read, like an early rejection leaves behind

        reader.drain()

        self.assertEqual(reader.read(1), b"")  # nothing left to read
        self.assertEqual(stream.tell(), 1000)  # the real stream was fully consumed

    def test_drain_on_an_already_fully_read_stream_is_a_no_op(self):
        stream = io.BytesIO(b"x" * 100)
        reader = _LimitedReader(stream, total_length=100)
        reader.read(100)

        reader.drain()  # must not raise

    def test_drain_swallows_a_broken_underlying_stream(self):
        class _BrokenStream:
            def read(self, size):
                raise OSError("Connection reset by peer")

        reader = _LimitedReader(_BrokenStream(), total_length=1000)

        reader.drain()  # must not raise -- a genuinely dead connection has
        # nothing left to meaningfully drain, and this must never mask
        # whatever the real/original error already was


if __name__ == "__main__":
    unittest.main()
