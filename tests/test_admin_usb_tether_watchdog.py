"""Tests for admin.usb_tether_watchdog's driver-matching logic
(SETLIST_ADMIN_USB_SPECIFICATION.md section 10) -- no real hardware or
real /sys tree needed: os.listdir is exercised against a real temp
directory (plain subdirectories, no symlinks required), and driver
resolution / IP checks are mocked directly so this runs identically on
Windows dev machines and the real Pi.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from admin import usb_tether_watchdog as watchdog


class FindTetheredInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sys_class_net = self.tmp.name

    def _make_iface(self, name: str) -> None:
        os.makedirs(os.path.join(self.sys_class_net, name))

    @patch("admin.usb_tether_watchdog._has_usable_ip", return_value=True)
    @patch("admin.usb_tether_watchdog._driver_for_interface")
    def test_finds_android_rndis_interface(self, mock_driver, mock_ip):
        self._make_iface("eth0")
        self._make_iface("usb0")
        mock_driver.side_effect = lambda root, iface: {
            "eth0": "smsc95xx", "usb0": "rndis_host",
        }[iface]

        result = watchdog.find_tethered_interface(self.sys_class_net)

        self.assertEqual(result, "usb0")

    @patch("admin.usb_tether_watchdog._has_usable_ip", return_value=True)
    @patch("admin.usb_tether_watchdog._driver_for_interface")
    def test_finds_iphone_ipheth_interface(self, mock_driver, mock_ip):
        self._make_iface("eth0")
        self._make_iface("eth1")
        mock_driver.side_effect = lambda root, iface: {
            "eth0": "smsc95xx", "eth1": "ipheth",
        }[iface]

        result = watchdog.find_tethered_interface(self.sys_class_net)

        self.assertEqual(result, "eth1")

    @patch("admin.usb_tether_watchdog._has_usable_ip", return_value=True)
    @patch("admin.usb_tether_watchdog._driver_for_interface")
    def test_permanent_ethernet_never_matches(self, mock_driver, mock_ip):
        self._make_iface("eth0")
        mock_driver.return_value = "smsc95xx"

        result = watchdog.find_tethered_interface(self.sys_class_net)

        self.assertIsNone(result)

    @patch("admin.usb_tether_watchdog._has_usable_ip", return_value=False)
    @patch("admin.usb_tether_watchdog._driver_for_interface", return_value="rndis_host")
    def test_matching_driver_without_ip_is_not_usable_yet(self, mock_driver, mock_ip):
        self._make_iface("usb0")

        result = watchdog.find_tethered_interface(self.sys_class_net)

        self.assertIsNone(result)

    def test_missing_sys_class_net_returns_none(self):
        result = watchdog.find_tethered_interface(os.path.join(self.sys_class_net, "does-not-exist"))

        self.assertIsNone(result)

    @patch("admin.usb_tether_watchdog._driver_for_interface", return_value=None)
    def test_interface_with_no_driver_symlink_is_skipped(self, mock_driver):
        self._make_iface("lo")

        result = watchdog.find_tethered_interface(self.sys_class_net)

        self.assertIsNone(result)


class TickTests(unittest.TestCase):
    @patch("admin.usb_tether_watchdog._set_admin_service_running")
    @patch("admin.usb_tether_watchdog.find_tethered_interface", return_value="usb0")
    def test_dry_run_never_touches_the_service(self, mock_find, mock_set_running):
        watchdog._tick(dry_run=True, sys_class_net="/sys/class/net")

        mock_set_running.assert_not_called()

    @patch("admin.usb_tether_watchdog._set_admin_service_running")
    @patch("admin.usb_tether_watchdog.find_tethered_interface", return_value="usb0")
    def test_live_run_starts_service_when_phone_present(self, mock_find, mock_set_running):
        watchdog._tick(dry_run=False, sys_class_net="/sys/class/net")

        mock_set_running.assert_called_once_with(True)

    @patch("admin.usb_tether_watchdog._set_admin_service_running")
    @patch("admin.usb_tether_watchdog.find_tethered_interface", return_value=None)
    def test_live_run_stops_service_when_no_phone(self, mock_find, mock_set_running):
        watchdog._tick(dry_run=False, sys_class_net="/sys/class/net")

        mock_set_running.assert_called_once_with(False)


if __name__ == "__main__":
    unittest.main()
