"""
setlist-network-watchdog: reapplies WiFi profiles to NetworkManager at
boot and periodically thereafter, and starts/stops setlist-admin.service
based on whether there's an actual usable IP (SETLIST_ADMIN_SPECIFICATION.md
section 5).

Entry point for `setlist-network-watchdog.service`. Run directly with
`--dry-run` for stage 3 of the network testing safety protocol (section
8a): every decision is logged, nothing is actually applied to
NetworkManager and no service is started/stopped. This is the mode this
project's own rollout is required to run in first, on real hardware,
before ever letting this touch a live connection.
"""

import argparse
import logging
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from admin import crypto, wifi  # noqa: E402

logger = logging.getLogger(__name__)

_ADMIN_SERVICE_NAME = "setlist-admin.service"
_DEFAULT_CHECK_INTERVAL_SECONDS = 30


def run_forever(usb_root: str, usb_uuid: str, check_interval: int, dry_run: bool) -> None:
    logger.info("setlist-network-watchdog starting (dry_run=%s)", dry_run)
    while True:
        try:
            _tick(usb_root, usb_uuid, dry_run)
        except Exception:
            # A single bad tick must never kill the watchdog -- there is
            # no one to restart it by hand on a headless appliance, same
            # reasoning as pedal-core.service's own Restart=always.
            logger.exception("Unhandled error in watchdog tick, continuing")
        time.sleep(check_interval)


def _tick(usb_root: str, usb_uuid: str, dry_run: bool) -> None:
    config = _load_config_if_available(usb_root, usb_uuid)

    if dry_run:
        logger.info(
            "[dry-run] would apply hotspot=%s home=%s",
            bool(config and config.hotspot), bool(config and config.home),
        )
    else:
        if config:
            wifi.apply_hotspot_profile(config.hotspot)
            wifi.apply_home_profile(config.home)

    connected = wifi.has_usable_ip()
    active = wifi.active_connection_name()
    logger.info("Connectivity: usable_ip=%s active_connection=%s", connected, active)

    if dry_run:
        logger.info(
            "[dry-run] would %s %s",
            "start" if connected else "stop", _ADMIN_SERVICE_NAME,
        )
        return

    _set_admin_service_running(connected)


def _load_config_if_available(usb_root: str, usb_uuid: str):
    config_path = os.path.join(usb_root, wifi.NETWORK_CONFIG_FILENAME)
    if not os.path.isdir(usb_root):
        logger.info("USB not present at %s, skipping WiFi config reapply this tick", usb_root)
        return None
    try:
        machine_id = crypto.read_machine_id()
    except OSError:
        logger.warning("Could not read %s", crypto.MACHINE_ID_PATH)
        return None
    key = crypto.derive_key(machine_id, usb_uuid)
    return wifi.load_config(config_path, key)


def _set_admin_service_running(should_run: bool) -> None:
    action = "start" if should_run else "stop"
    try:
        subprocess.run(
            ["sudo", "systemctl", action, _ADMIN_SERVICE_NAME],
            capture_output=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("Could not %s %s: %s", action, _ADMIN_SERVICE_NAME, e)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usb-root", required=True, help="Where the library USB is mounted")
    parser.add_argument("--usb-uuid", required=True, help="The library USB's UUID (same as pedal-core.service's --usb-uuid)")
    parser.add_argument("--check-interval", type=int, default=_DEFAULT_CHECK_INTERVAL_SECONDS)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Log every decision without touching NetworkManager or "
             "setlist-admin.service -- required for stage 3 of the "
             "network testing safety protocol before this ever runs for real.",
    )
    parser.add_argument("--log-file", default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        filename=args.log_file,
    )
    run_forever(args.usb_root, args.usb_uuid, args.check_interval, args.dry_run)


if __name__ == "__main__":
    main()
