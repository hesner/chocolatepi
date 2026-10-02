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
    ("GET", re.compile(r"^/api/sets$"), "list_sets"),
    ("POST", re.compile(r"^/api/sets$"), "create_set"),
    ("POST", re.compile(r"^/api/sets/active$"), "set_active_set"),
    ("GET", re.compile(r"^/api/sets/(?P<set>[^/]+)/banks$"), "list_banks"),
    ("POST", re.compile(r"^/api/sets/(?P<set>[^/]+)/banks$"), "create_bank"),
    ("PUT", re.compile(r"^/api/sets/(?P<set>[^/]+)/banks/(?P<bank>\d+)$"), "rename_bank"),
    ("DELETE", re.compile(r"^/api/sets/(?P<set>[^/]+)/banks/(?P<bank>\d+)$"), "delete_bank"),
    ("GET", re.compile(r"^/api/sets/(?P<set>[^/]+)/banks/(?P<bank>\d+)/tracks$"), "list_tracks"),
    ("POST", re.compile(r"^/api/sets/(?P<set>[^/]+)/banks/(?P<bank>\d+)/tracks/(?P<letter>[A-Za-z])$"), "assign_track"),
    ("PUT", re.compile(r"^/api/sets/(?P<set>[^/]+)/banks/(?P<bank>\d+)/tracks/(?P<letter>[A-Za-z])$"), "rename_track"),
    ("DELETE", re.compile(r"^/api/sets/(?P<set>[^/]+)/banks/(?P<bank>\d+)/tracks/(?P<letter>[A-Za-z])$"), "delete_track"),
    ("POST", re.compile(r"^/api/sets/(?P<set>[^/]+)/banks/(?P<bank>\d+)/swap$"), "swap_tracks"),
    ("GET", re.compile(r"^/api/songs$"), "list_songs"),
    ("POST", re.compile(r"^/api/songs$"), "upload_song"),
    ("PUT", re.compile(r"^/api/songs/(?P<filename>[^/]+)$"), "rename_song"),
    ("DELETE", re.compile(r"^/api/songs/(?P<filename>[^/]+)$"), "delete_song"),
    ("POST", re.compile(r"^/api/songs/(?P<filename>[^/]+)/optimize$"), "optimize_song"),
    ("POST", re.compile(r"^/api/songs/(?P<filename>[^/]+)/optimize/cancel$"), "cancel_optimize_song"),
    ("POST", re.compile(r"^/api/sets/(?P<set>[^/]+)/banks/(?P<bank>\d+)/tracks/(?P<letter>[A-Za-z])/assign-from-library$"), "assign_song_to_slot"),
    ("POST", re.compile(r"^/api/sets/(?P<set>[^/]+)/banks/(?P<bank>\d+)/tracks/(?P<letter>[A-Za-z])/save-to-library$"), "save_track_to_library"),
    ("GET", re.compile(r"^/api/standby$"), "get_standby"),
    ("POST", re.compile(r"^/api/standby$"), "set_standby"),
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

    def drain(self) -> None:
        """Reads and discards whatever's left unread. Real incident found
        live (2026-10-01, in the sibling setlist-admin-usb expansion,
        ported here unchanged): a validation rejection (e.g. a duplicate
        filename) can reject *before* the body is ever read at all --
        library_ops.upload_song()'s duplicate-name check runs before
        _atomic_write_stream() touches the stream. Responding without
        first consuming a large unread body (hundreds of MB, for a real
        video) left the connection in a state the client's own TCP stack
        treated as reset -- "Load failed" in Safari -- even though the
        server's own response was sent correctly and the rejection
        reason was right there in it. Every raw-body upload handler
        drains in a `finally` now, regardless of success or failure, so
        the connection is always left clean. Swallows its own errors --
        if the connection is already broken (a genuine client-side
        disconnect), there's nothing left to drain anyway, and this must
        never mask whatever the real exception already was."""
        try:
            while self.read(65536):
                pass
        except OSError:
            pass


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
            # encodeURIComponent() on Set/song names before building
            # the URL, so spaces/accents/etc. round-trip correctly) --
            # decode them here, once, so every _action_* handler and
            # library_ops.py always see the real name, never "My%20Set".
            # Found as a real, pre-existing bug: nothing decoded these
            # before, so any Set/song name needing encoding at all
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
            # "Bank/Set doesn't exist", etc.) is a ValueError -- catching
            # it here, generically, is what actually turns its carefully
            # written user-facing messages into a real 400 response
            # instead of falling through to the 500 below. Found as a
            # real, pre-existing bug: nothing translated it before this.
            #
            # Also logged (not just sent to the client): a 400 is a
            # normal, expected outcome (bad input, a name collision), not
            # a bug -- but real incident found live (2026-10-01, in the
            # sibling setlist-admin-usb expansion, ported here unchanged):
            # a rejected upload left no trail at all server-side, so when
            # a phone's own alert() wasn't seen in time, there was no way
            # to find out afterward what the app actually rejected and
            # why, short of guessing or reproducing it blind.
            logger.warning("%s rejected: %s", action_name, e)
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

    def _action_list_sets(self, path_params, query):
        return 200, self.api.list_sets()

    def _action_create_set(self, path_params, query):
        body = self._read_json_body()
        self.api.create_set(body.get("name", ""))
        return 201, {"ok": True}

    def _action_set_active_set(self, path_params, query):
        body = self._read_json_body()
        self.api.set_active_set(body.get("name", ""))
        return 200, {"ok": True}

    def _action_list_banks(self, path_params, query):
        return 200, self.api.list_banks(path_params["set"])

    def _action_create_bank(self, path_params, query):
        body = self._read_json_body()
        self.api.create_bank(path_params["set"], self._parse_bank_number(body))
        return 201, {"ok": True}

    def _action_rename_bank(self, path_params, query):
        body = self._read_json_body()
        self.api.rename_bank(path_params["set"], int(path_params["bank"]), self._parse_bank_number(body))
        return 200, {"ok": True}

    def _action_delete_bank(self, path_params, query):
        self.api.delete_bank(path_params["set"], int(path_params["bank"]))
        return 200, {"ok": True}

    def _action_list_tracks(self, path_params, query):
        return 200, self.api.list_tracks(path_params["set"], int(path_params["bank"]))

    def _action_assign_track(self, path_params, query):
        display_name, extension = self._parse_upload_filename()
        length = int(self.headers.get("Content-Length", 0))
        # self.rfile is a raw, connection-backed stream -- reading past
        # Content-Length would block waiting for bytes that never come,
        # since an HTTP connection doesn't EOF between requests. Bound
        # it here so library_ops.assign_track()'s chunked read loop
        # actually terminates.
        bounded_source = _LimitedReader(self.rfile, length)
        try:
            warning = self.api.assign_track(
                path_params["set"], int(path_params["bank"]), path_params["letter"],
                display_name, extension, bounded_source,
            )
        finally:
            bounded_source.drain()
        return 200, {"ok": True, "warning": warning}

    def _action_rename_track(self, path_params, query):
        body = self._read_json_body()
        self.api.rename_track(path_params["set"], int(path_params["bank"]), path_params["letter"], body.get("display_name", ""))
        return 200, {"ok": True}

    def _action_delete_track(self, path_params, query):
        self.api.delete_track(path_params["set"], int(path_params["bank"]), path_params["letter"])
        return 200, {"ok": True}

    def _action_swap_tracks(self, path_params, query):
        body = self._read_json_body()
        self.api.swap_tracks(path_params["set"], int(path_params["bank"]), body.get("letter_a", ""), body.get("letter_b", ""))
        return 200, {"ok": True}

    def _action_list_songs(self, path_params, query):
        return 200, self.api.list_songs()

    def _action_upload_song(self, path_params, query):
        display_name, extension = self._parse_upload_filename()
        overwrite = self.headers.get("X-Track-Overwrite", "").strip().lower() == "true"
        length = int(self.headers.get("Content-Length", 0))
        bounded_source = _LimitedReader(self.rfile, length)
        try:
            warning = self.api.upload_song(display_name, extension, bounded_source, overwrite=overwrite)
        finally:
            bounded_source.drain()
        return 200, {"ok": True, "warning": warning}

    def _action_rename_song(self, path_params, query):
        body = self._read_json_body()
        self.api.rename_song(path_params["filename"], body.get("display_name", ""))
        return 200, {"ok": True}

    def _action_delete_song(self, path_params, query):
        self.api.delete_song(path_params["filename"])
        return 200, {"ok": True}

    def _action_optimize_song(self, path_params, query):
        self.api.request_song_optimization(path_params["filename"])
        return 200, {"ok": True}

    def _action_cancel_optimize_song(self, path_params, query):
        self.api.cancel_song_optimization(path_params["filename"])
        return 200, {"ok": True}

    def _action_assign_song_to_slot(self, path_params, query):
        body = self._read_json_body()
        self.api.assign_song_to_slot(
            path_params["set"], int(path_params["bank"]), path_params["letter"],
            body.get("song_filename", ""),
        )
        return 200, {"ok": True}

    def _action_save_track_to_library(self, path_params, query):
        self.api.save_track_to_library(path_params["set"], int(path_params["bank"]), path_params["letter"])
        return 200, {"ok": True}

    def _action_get_standby(self, path_params, query):
        return 200, self.api.get_standby()

    def _action_set_standby(self, path_params, query):
        body = self._read_json_body()
        self.api.set_standby(body.get("song_filename", ""))
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

    def _parse_bank_number(self, body: dict) -> int:
        """Real, pre-existing bug found on real hardware: a plain
        `int(body.get("number", 0))` crashes with an unhandled 500 if
        the client ever sends `{"number": null}` -- which JSON.stringify()
        silently produces from JS's own `NaN` (e.g. parseInt() on
        unexpected input from a mobile keyboard's autocomplete). The
        default of 0 in .get() only ever applied when the key was
        missing entirely, never when it was present but null."""
        value = body.get("number")
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ApiError(400, "Bank number is required and must be a number")

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
        # Real bug found live (2026-10-02, in the sibling
        # setlist-admin-usb expansion -- ported here unchanged): the
        # exact same class of problem as _serve_static()'s own
        # Cache-Control fix, just for API responses instead of static
        # files -- GET /api/songs is still a plain GET, so a browser's
        # own heuristic caching can serve a stale response for it too.
        # Confirmed live: a song actively being optimized (ffmpeg
        # genuinely running, the real job status genuinely "running")
        # showed as already-optimized in the app, because the phone was
        # reusing a cached response from before the job started. Every
        # API response is small and this app is low-traffic (one admin
        # session at a time), so there's no real cost to never caching
        # any of them.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
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
        # Real bug found live (2026-10-02, in the sibling
        # setlist-admin-usb expansion -- ported here unchanged): with
        # no cache-control header at all, a browser's own heuristic
        # caching can keep a stale index.html/app.js/style.css around
        # indefinitely -- a real problem for an app redeployed
        # repeatedly (every fix this project ships), since a stale
        # app.js referencing a DOM element a newer index.html removed
        # (or vice versa) throws during its own top-level script
        # execution, silently aborting before boot() ever runs -- the
        # page is then stuck showing nothing but the static topbar,
        # intermittently, depending on which files the browser happened
        # to have cached. This app is low-traffic (one admin session at
        # a time) and every file here is tiny, so there's no real cost
        # to never caching them.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
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
    try:
        removed = api.cleanup_stale_temp_files()
        if removed:
            logger.info("Removed %d stale .part/.swaptmp file(s) from an interrupted write", removed)
    except Exception:
        # Not fatal -- worst case a future write's own .part collides
        # and gets cleaned up then instead. Never block startup over
        # housekeeping.
        logger.exception("Could not clean up stale .part/.swaptmp files at startup")
    server = ThreadingHTTPServer((args.host, args.port), make_handler_class(api))
    logger.info("setlist-admin listening on %s:%d", args.host, args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
