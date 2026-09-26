"""
setlist-admin's HTTP server. Standard library only (`http.server`) --
no Flask, no third-party WSGI stack, matching this project's existing
"no `pip install`" rule (SETLIST_ADMIN_SPECIFICATION.md section 2).

Entry point for `setlist-admin.service` (only ever started by
setlist-network-watchdog.service while there's a usable IP -- section 5).
Runs a `ThreadingHTTPServer` so a slow upload doesn't block the status
endpoint from responding, with `Nice=`/cgroup limits applied at the
systemd level (section 7), not here.
"""

import argparse
import json
import logging
import os
import re
import sys
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from admin.api import AdminAPI, AdminConfig, ApiError  # noqa: E402

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
SESSION_COOKIE_NAME = "setlist_admin_session"

_ROUTES = [
    ("POST", re.compile(r"^/api/pin$"), "set_pin"),
    ("POST", re.compile(r"^/api/login$"), "login"),
    ("GET", re.compile(r"^/api/status$"), "status"),
    ("GET", re.compile(r"^/api/shows$"), "list_shows"),
    ("POST", re.compile(r"^/api/shows$"), "create_show"),
    ("POST", re.compile(r"^/api/shows/active$"), "set_active_show"),
    ("GET", re.compile(r"^/api/shows/(?P<show>[^/]+)/sets$"), "list_sets"),
    ("POST", re.compile(r"^/api/shows/(?P<show>[^/]+)/sets$"), "create_set"),
    ("PUT", re.compile(r"^/api/shows/(?P<show>[^/]+)/sets/(?P<set>\d+)$"), "rename_set"),
    ("DELETE", re.compile(r"^/api/shows/(?P<show>[^/]+)/sets/(?P<set>\d+)$"), "delete_set"),
    ("GET", re.compile(r"^/api/shows/(?P<show>[^/]+)/sets/(?P<set>\d+)/tracks$"), "list_tracks"),
    ("POST", re.compile(r"^/api/shows/(?P<show>[^/]+)/sets/(?P<set>\d+)/tracks/(?P<letter>[A-Za-z])$"), "assign_track"),
    ("PUT", re.compile(r"^/api/shows/(?P<show>[^/]+)/sets/(?P<set>\d+)/tracks/(?P<letter>[A-Za-z])$"), "rename_track"),
    ("DELETE", re.compile(r"^/api/shows/(?P<show>[^/]+)/sets/(?P<set>\d+)/tracks/(?P<letter>[A-Za-z])$"), "delete_track"),
    ("POST", re.compile(r"^/api/shows/(?P<show>[^/]+)/sets/(?P<set>\d+)/swap$"), "swap_tracks"),
    ("GET", re.compile(r"^/api/songs$"), "list_songs"),
    ("POST", re.compile(r"^/api/songs$"), "upload_song"),
    ("PUT", re.compile(r"^/api/songs/(?P<filename>[^/]+)$"), "rename_song"),
    ("DELETE", re.compile(r"^/api/songs/(?P<filename>[^/]+)$"), "delete_song"),
    ("POST", re.compile(r"^/api/shows/(?P<show>[^/]+)/sets/(?P<set>\d+)/tracks/(?P<letter>[A-Za-z])/assign-from-library$"), "assign_song_to_slot"),
    ("POST", re.compile(r"^/api/shows/(?P<show>[^/]+)/sets/(?P<set>\d+)/tracks/(?P<letter>[A-Za-z])/save-to-library$"), "save_track_to_library"),
    ("GET", re.compile(r"^/api/wifi$"), "wifi_status"),
    ("POST", re.compile(r"^/api/wifi/home$"), "set_home_wifi"),
]

# Endpoints reachable before a session exists -- everything else requires
# a valid session cookie (require_session, checked in _dispatch).
_PUBLIC_ROUTES = {"set_pin", "login", "status"}


class _LimitedReader:
    """Wraps a connection-backed stream (self.rfile) so reads never go
    past a fixed total byte count -- the raw stream has no EOF between
    requests, so an unbounded read loop against it would hang forever
    instead of stopping when the upload body actually ends."""

    def __init__(self, stream, total_length: int):
        self._stream = stream
        self._remaining = total_length

    def read(self, size: int) -> bytes:
        if self._remaining <= 0:
            return b""
        chunk = self._stream.read(min(size, self._remaining))
        self._remaining -= len(chunk)
        return chunk


class Handler(BaseHTTPRequestHandler):
    api: AdminAPI  # set once via make_handler_class()

    def log_message(self, format, *args):  # noqa: A002 -- stdlib's own name
        logger.info("%s - %s", self.address_string(), format % args)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str):
        parsed = urlparse(self.path)
        path = parsed.path

        if method == "GET" and (path == "/" or path.startswith("/static/")):
            self._serve_static(path)
            return

        for route_method, pattern, action_name in _ROUTES:
            if route_method != method:
                continue
            match = pattern.match(path)
            if not match:
                continue
            # Path segments arrive percent-encoded (the frontend calls
            # encodeURIComponent() on show/song names before building
            # the URL, so spaces/accents/etc. round-trip correctly) --
            # decode them here, once, so every _action_* handler and
            # library_ops.py always see the real name, never "My%20Show".
            # Found as a real, pre-existing bug: nothing decoded these
            # before, so any show/song name needing encoding at all
            # (any space or accented character) silently failed.
            path_params = {k: unquote(v) if v is not None else v for k, v in match.groupdict().items()}
            self._handle_action(action_name, path_params, parse_qs(parsed.query))
            return

        self._send_json(404, {"error": "Not found"})

    def _handle_action(self, action_name: str, path_params: dict, query: dict):
        # Extra response headers (e.g. Set-Cookie) an action handler
        # needs to add -- collected here rather than written directly
        # by the handler, because BaseHTTPRequestHandler requires
        # send_response() (the status line) to be sent *before* any
        # send_header() call; calling send_header() first corrupts the
        # response. _set_session_cookie() appends here instead of
        # writing immediately, and _send_json() below is the single
        # place that actually calls send_response() then these headers
        # then end_headers(), in the right order.
        self._pending_headers = []
        try:
            if action_name not in _PUBLIC_ROUTES:
                self.api.require_session(self._session_token())

            handler = getattr(self, f"_action_{action_name}")
            status, body = handler(path_params, query)
            self._send_json(status, body)
        except ApiError as e:
            self._send_json(e.status, {"error": e.message})
        except ValueError as e:
            # library_ops.LibraryOpsError (invalid input, name collision,
            # "Show/Set doesn't exist", etc.) is a ValueError -- catching
            # it here, generically, is what actually turns its carefully
            # written user-facing messages into a real 400 response
            # instead of falling through to the 500 below. Found as a
            # real, pre-existing bug: nothing translated it before this.
            self._send_json(400, {"error": str(e)})
        except Exception:
            logger.exception("Unhandled error handling %s", action_name)
            self._send_json(500, {"error": "Internal error"})

    # -- Action handlers: each returns (status_code, response_body) ---------

    def _action_set_pin(self, path_params, query):
        body = self._read_json_body()
        self.api.set_pin(body.get("pin", ""))
        return 200, {"ok": True}

    def _action_login(self, path_params, query):
        body = self._read_json_body()
        token = self.api.login(body.get("pin", ""))
        self._set_session_cookie(token)
        return 200, {"ok": True}

    def _action_status(self, path_params, query):
        first_run = self.api.is_first_run()
        playback_active = False if first_run else self.api.is_playback_likely_active()
        return 200, {"first_run": first_run, "playback_active": playback_active}

    def _action_list_shows(self, path_params, query):
        return 200, self.api.list_shows()

    def _action_create_show(self, path_params, query):
        body = self._read_json_body()
        self.api.create_show(body.get("name", ""))
        return 201, {"ok": True}

    def _action_set_active_show(self, path_params, query):
        body = self._read_json_body()
        self.api.set_active_show(body.get("name", ""))
        return 200, {"ok": True}

    def _action_list_sets(self, path_params, query):
        return 200, self.api.list_sets(path_params["show"])

    def _action_create_set(self, path_params, query):
        body = self._read_json_body()
        self.api.create_set(path_params["show"], int(body.get("number", 0)))
        return 201, {"ok": True}

    def _action_rename_set(self, path_params, query):
        body = self._read_json_body()
        self.api.rename_set(path_params["show"], int(path_params["set"]), int(body.get("number", 0)))
        return 200, {"ok": True}

    def _action_delete_set(self, path_params, query):
        self.api.delete_set(path_params["show"], int(path_params["set"]))
        return 200, {"ok": True}

    def _action_list_tracks(self, path_params, query):
        return 200, self.api.list_tracks(path_params["show"], int(path_params["set"]))

    def _action_assign_track(self, path_params, query):
        display_name, extension = self._parse_upload_filename()
        length = int(self.headers.get("Content-Length", 0))
        # self.rfile is a raw, connection-backed stream -- reading past
        # Content-Length would block waiting for bytes that never come,
        # since an HTTP connection doesn't EOF between requests. Bound
        # it here so library_ops.assign_track()'s chunked read loop
        # actually terminates.
        bounded_source = _LimitedReader(self.rfile, length)
        warning = self.api.assign_track(
            path_params["show"], int(path_params["set"]), path_params["letter"],
            display_name, extension, bounded_source,
        )
        return 200, {"ok": True, "warning": warning}

    def _action_rename_track(self, path_params, query):
        body = self._read_json_body()
        self.api.rename_track(path_params["show"], int(path_params["set"]), path_params["letter"], body.get("display_name", ""))
        return 200, {"ok": True}

    def _action_delete_track(self, path_params, query):
        self.api.delete_track(path_params["show"], int(path_params["set"]), path_params["letter"])
        return 200, {"ok": True}

    def _action_swap_tracks(self, path_params, query):
        body = self._read_json_body()
        self.api.swap_tracks(path_params["show"], int(path_params["set"]), body.get("letter_a", ""), body.get("letter_b", ""))
        return 200, {"ok": True}

    def _action_list_songs(self, path_params, query):
        return 200, self.api.list_songs()

    def _action_upload_song(self, path_params, query):
        display_name, extension = self._parse_upload_filename()
        length = int(self.headers.get("Content-Length", 0))
        bounded_source = _LimitedReader(self.rfile, length)
        warning = self.api.upload_song(display_name, extension, bounded_source)
        return 200, {"ok": True, "warning": warning}

    def _action_rename_song(self, path_params, query):
        body = self._read_json_body()
        self.api.rename_song(path_params["filename"], body.get("display_name", ""))
        return 200, {"ok": True}

    def _action_delete_song(self, path_params, query):
        self.api.delete_song(path_params["filename"])
        return 200, {"ok": True}

    def _action_assign_song_to_slot(self, path_params, query):
        body = self._read_json_body()
        self.api.assign_song_to_slot(
            path_params["show"], int(path_params["set"]), path_params["letter"],
            body.get("song_filename", ""),
        )
        return 200, {"ok": True}

    def _action_save_track_to_library(self, path_params, query):
        self.api.save_track_to_library(path_params["show"], int(path_params["set"]), path_params["letter"])
        return 200, {"ok": True}

    def _action_wifi_status(self, path_params, query):
        return 200, self.api.wifi_status()

    def _action_set_home_wifi(self, path_params, query):
        body = self._read_json_body()
        self.api.set_home_wifi(body.get("ssid", ""), body.get("password", ""))
        return 200, {"ok": True}

    # -- Helpers --------------------------------------------------------------

    def _session_token(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        jar = cookies.SimpleCookie()
        jar.load(raw)
        morsel = jar.get(SESSION_COOKIE_NAME)
        return morsel.value if morsel else None

    def _set_session_cookie(self, token: str):
        self._pending_headers.append(
            ("Set-Cookie", f"{SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict")
        )

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise ApiError(400, "Invalid JSON body")

    def _parse_upload_filename(self):
        """Track uploads are sent as a raw file body with the display
        name and extension in headers, not multipart -- simpler to
        stream straight from self.rfile into library_ops.assign_track()
        without buffering the whole thing here first (section 7)."""
        display_name = self.headers.get("X-Track-Name", "").strip()
        extension = self.headers.get("X-Track-Extension", "").strip()
        if not display_name or not extension:
            raise ApiError(400, "X-Track-Name and X-Track-Extension headers are required")
        return display_name, extension

    def _send_json(self, status: int, body: dict):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        for name, value in getattr(self, "_pending_headers", []):
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def _serve_static(self, path: str):
        if path == "/":
            path = "/static/index.html"
        relative = path[len("/static/"):]
        full_path = os.path.normpath(os.path.join(STATIC_DIR, relative))

        # Reject anything that escapes STATIC_DIR (e.g. "../../etc/passwd")
        if not full_path.startswith(os.path.normpath(STATIC_DIR)):
            self._send_json(404, {"error": "Not found"})
            return

        if not os.path.isfile(full_path):
            self._send_json(404, {"error": "Not found"})
            return

        content_type = _guess_content_type(full_path)
        with open(full_path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _guess_content_type(path: str) -> str:
    if path.endswith(".html"):
        return "text/html; charset=utf-8"
    if path.endswith(".js"):
        return "application/javascript; charset=utf-8"
    if path.endswith(".css"):
        return "text/css; charset=utf-8"
    return "application/octet-stream"


def make_handler_class(api: AdminAPI):
    return type("BoundHandler", (Handler,), {"api": api})


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usb-root", required=True)
    parser.add_argument("--usb-uuid", required=True)
    parser.add_argument("--mount-point", default="/media/usb")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--log-file", default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        filename=args.log_file,
    )
    config = AdminConfig(usb_root=args.usb_root, mount_point=args.mount_point, usb_uuid=args.usb_uuid)
    api = AdminAPI(config)
    server = ThreadingHTTPServer((args.host, args.port), make_handler_class(api))
    logger.info("setlist-admin listening on %s:%d", args.host, args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
