"""Tests for admin.usb_tether_watchdog's driver-matching logic
(SPECIFICATION.md section 10) -- no real hardware or
real /sys tree needed: os.listdir is exercised against a real temp
directory (plain subdirectories, no symlinks required), and driver
resolution / IP checks are mocked directly so this runs identically on
Windows dev machines and the real Pi.
"""

import os
import tempfile
import unittest
from unittest.mock import Mock, patch

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
    @patch("admin.usb_tether_watchdog.wifi_connected_to_profile", return_value=False)
    @patch("admin.usb_tether_watchdog._set_admin_service_running")
    @patch("admin.usb_tether_watchdog.find_tethered_interface", return_value="usb0")
    def test_dry_run_never_touches_the_service(self, mock_find, mock_set_running, mock_wifi):
        watchdog._tick(dry_run=True, sys_class_net="/sys/class/net")

        mock_set_running.assert_not_called()

    @patch("admin.usb_tether_watchdog.wifi_connected_to_profile", return_value=False)
    @patch("admin.usb_tether_watchdog._set_admin_service_running")
    @patch("admin.usb_tether_watchdog.find_tethered_interface", return_value="usb0")
    def test_live_run_starts_service_when_phone_present(self, mock_find, mock_set_running, mock_wifi):
        watchdog._tick(dry_run=False, sys_class_net="/sys/class/net")

        mock_set_running.assert_called_once_with(True)

    @patch("admin.usb_tether_watchdog.wifi_connected_to_profile", return_value=False)
    @patch("admin.usb_tether_watchdog._set_admin_service_running")
    @patch("admin.usb_tether_watchdog.find_tethered_interface", return_value=None)
    def test_live_run_stops_service_when_neither_phone_nor_wifi(self, mock_find, mock_set_running, mock_wifi):
        watchdog._tick(dry_run=False, sys_class_net="/sys/class/net")

        mock_set_running.assert_called_once_with(False)

    @patch("admin.usb_tether_watchdog.wifi_connected_to_profile", return_value=True)
    @patch("admin.usb_tether_watchdog._set_admin_service_running")
    @patch("admin.usb_tether_watchdog.find_tethered_interface", return_value=None)
    def test_live_run_starts_service_when_only_wifi_present(self, mock_find, mock_set_running, mock_wifi):
        watchdog._tick(dry_run=False, sys_class_net="/sys/class/net")

        mock_set_running.assert_called_once_with(True)

    @patch("admin.usb_tether_watchdog.wifi_connected_to_profile", return_value=True)
    @patch("admin.usb_tether_watchdog._set_admin_service_running")
    @patch("admin.usb_tether_watchdog.find_tethered_interface", return_value="usb0")
    def test_live_run_starts_service_when_both_phone_and_wifi_present(self, mock_find, mock_set_running, mock_wifi):
        watchdog._tick(dry_run=False, sys_class_net="/sys/class/net")

        mock_set_running.assert_called_once_with(True)


class WifiConnectedToProfileTests(unittest.TestCase):
    def _mock_result(self, stdout):
        result = Mock()
        result.stdout = stdout
        return result

    @patch("admin.usb_tether_watchdog._has_usable_ip", return_value=True)
    @patch("admin.usb_tether_watchdog.subprocess.run")
    def test_matches_exact_profile_name_with_usable_ip(self, mock_run, mock_ip):
        mock_run.return_value = self._mock_result(
            "preconfigured:802-11-wireless:wlan0\n"
        )

        self.assertTrue(watchdog.wifi_connected_to_profile("preconfigured"))

    @patch("admin.usb_tether_watchdog._has_usable_ip", return_value=True)
    @patch("admin.usb_tether_watchdog.subprocess.run")
    def test_never_trusts_a_different_network_name(self, mock_run, mock_ip):
        mock_run.return_value = self._mock_result(
            "some-other-wifi:802-11-wireless:wlan0\n"
        )

        self.assertFalse(watchdog.wifi_connected_to_profile("preconfigured"))

    @patch("admin.usb_tether_watchdog._has_usable_ip", return_value=False)
    @patch("admin.usb_tether_watchdog.subprocess.run")
    def test_matching_profile_without_usable_ip_is_not_connected_yet(self, mock_run, mock_ip):
        mock_run.return_value = self._mock_result(
            "preconfigured:802-11-wireless:wlan0\n"
        )

        self.assertFalse(watchdog.wifi_connected_to_profile("preconfigured"))

    @patch("admin.usb_tether_watchdog._has_usable_ip", return_value=True)
    @patch("admin.usb_tether_watchdog.subprocess.run")
    def test_matches_regardless_of_which_actual_network_the_profile_points_at(self, mock_run, mock_ip):
        """Real user request (2026-10-03): confirm that relocating the
        band's home WiFi -- a different SSID/password entirely, applied
        via the documented `nmcli connection modify preconfigured ...`
        procedure that updates the *same* profile in place -- needs no
        code change here. This function only ever asks `nmcli` for
        NAME/TYPE/DEVICE, never SSID or password, so it has no way to
        notice (or care) that the underlying network changed, as long
        as the profile keeps the same name."""
        mock_run.return_value = self._mock_result(
            "preconfigured:802-11-wireless:wlan0\n"
        )

        self.assertTrue(watchdog.wifi_connected_to_profile("preconfigured"))
        called_args = mock_run.call_args[0][0]
        self.assertNotIn("ssid", " ".join(called_args).lower())
        self.assertNotIn("psk", " ".join(called_args).lower())

    @patch("admin.usb_tether_watchdog.subprocess.run")
    def test_no_active_connections_returns_false(self, mock_run):
        mock_run.return_value = self._mock_result("")

        self.assertFalse(watchdog.wifi_connected_to_profile("preconfigured"))

    @patch("admin.usb_tether_watchdog.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_nmcli_binary_returns_false(self, mock_run):
        self.assertFalse(watchdog.wifi_connected_to_profile("preconfigured"))


if __name__ == "__main__":
    unittest.main()
