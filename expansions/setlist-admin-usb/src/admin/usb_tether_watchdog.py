"""
usb-tether-watchdog: detects a phone tethered over USB (Android's USB
tethering or iPhone's Personal Hotspot via cable) and starts/stops
setlist-admin.service accordingly (SETLIST_ADMIN_USB_SPECIFICATION.md
section 4c).

Detection is by kernel driver name, not IP range or interface name --
those vary too much across phone models/OS versions to hardcode, but
the driver a tethered phone's virtual network adapter binds to is
stable: rndis_host / cdc_ether / cdc_ncm for Android, ipheth for
iPhone. A permanently-attached Ethernet cable (used for development)
never matches any of these, so it never spuriously starts the admin
server.

Run directly with `--dry-run` for hardware testing (section 10): every
decision is logged, nothing is actually started/stopped.
"""

import argparse
import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)

_ADMIN_SERVICE_NAME = "setlist-admin.service"
_DEFAULT_CHECK_INTERVAL_SECONDS = 5
_DEFAULT_SYS_CLASS_NET = "/sys/class/net"

PHONE_TETHER_DRIVERS = frozenset({"rndis_host", "cdc_ether", "cdc_ncm", "ipheth"})


def find_tethered_interface(sys_class_net: str = _DEFAULT_SYS_CLASS_NET):
    """Returns the name of the first network interface whose kernel
    driver matches a known phone-tethering driver and that has a
    usable IPv4 address, or None if none is found."""
    try:
        interfaces = os.listdir(sys_class_net)
    except OSError:
        return None
    for iface in sorted(interfaces):
        driver = _driver_for_interface(sys_class_net, iface)
        if driver in PHONE_TETHER_DRIVERS and _has_usable_ip(iface):
            return iface
    return None


def _driver_for_interface(sys_class_net: str, iface: str):
    driver_link = os.path.join(sys_class_net, iface, "device", "driver")
    try:
        target = os.readlink(driver_link)
    except OSError:
        return None
    return os.path.basename(target)


def _has_usable_ip(iface: str) -> bool:
    try:
        result = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", iface],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return bool(result.stdout.strip())


def run_forever(check_interval: int, dry_run: bool, sys_class_net: str = _DEFAULT_SYS_CLASS_NET) -> None:
    logger.info("usb-tether-watchdog starting (dry_run=%s)", dry_run)
    while True:
        try:
            _tick(dry_run, sys_class_net)
        except Exception:
            # A single bad tick must never kill the watchdog -- there is
            # no one to restart it by hand on a headless appliance, same
            # reasoning as pedal-core.service's own Restart=always.
            logger.exception("Unhandled error in watchdog tick, continuing")
        time.sleep(check_interval)


def _tick(dry_run: bool, sys_class_net: str) -> None:
    iface = find_tethered_interface(sys_class_net)
    logger.info("Tethered interface: %s", iface or "none")
    if dry_run:
        logger.info(
            "[dry-run] would %s %s",
            "start" if iface else "stop", _ADMIN_SERVICE_NAME,
        )
        return
    _set_admin_service_running(bool(iface))


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
    parser.add_argument("--check-interval", type=int, default=_DEFAULT_CHECK_INTERVAL_SECONDS)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Log every decision without starting/stopping setlist-admin.service "
             "-- required for the first hardware-testing stage before this ever "
             "runs for real (SETLIST_ADMIN_USB_SPECIFICATION.md section 10).",
    )
    parser.add_argument("--sys-class-net", default=_DEFAULT_SYS_CLASS_NET)
    parser.add_argument("--log-file", default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        filename=args.log_file,
    )
    run_forever(args.check_interval, args.dry_run, args.sys_class_net)


if __name__ == "__main__":
    main()
