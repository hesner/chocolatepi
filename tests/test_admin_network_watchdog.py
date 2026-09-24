"""
network_watchdog.py tests. Everything real (nmcli, systemctl,
/etc/machine-id) is mocked -- this only exercises the decision logic:
what gets applied/started/stopped under which conditions, and crucially,
that --dry-run (network testing safety protocol stage 3,
SETLIST_ADMIN_SPECIFICATION.md section 8a) truly never calls any of the
real-effecting functions.

Run with: python -m unittest tests/test_admin_network_watchdog.py
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from admin import network_watchdog, wifi  # noqa: E402


class TestTick(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.usb_root = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    @patch("admin.network_watchdog._set_admin_service_running")
    @patch("admin.network_watchdog.wifi.active_connection_name", return_value=None)
    @patch("admin.network_watchdog.wifi.has_usable_ip", return_value=True)
    @patch("admin.network_watchdog.wifi.apply_home_profile")
    @patch("admin.network_watchdog.wifi.apply_hotspot_profile")
    @patch("admin.network_watchdog._load_config_if_available", return_value=None)
    def test_dry_run_never_applies_profiles_or_touches_the_service(
        self, mock_load, mock_apply_hotspot, mock_apply_home, mock_has_ip,
        mock_active_name, mock_set_running,
    ):
        network_watchdog._tick(self.usb_root, "test-uuid", dry_run=True)

        mock_apply_home.assert_not_called()
        mock_apply_hotspot.assert_not_called()
        mock_set_running.assert_not_called()

    @patch("admin.network_watchdog._set_admin_service_running")
    @patch("admin.network_watchdog.wifi.active_connection_name", return_value="setlist-admin-home")
    @patch("admin.network_watchdog.wifi.has_usable_ip", return_value=True)
    @patch("admin.network_watchdog.wifi.apply_home_profile")
    @patch("admin.network_watchdog.wifi.apply_hotspot_profile")
    def test_real_run_applies_both_profiles_when_config_available(
        self, mock_apply_hotspot, mock_apply_home, mock_has_ip,
        mock_active_name, mock_set_running,
    ):
        config = wifi.NetworkConfig(
            home=wifi.WifiProfile(ssid="Home", password="pw"),
            hotspot=wifi.WifiProfile(ssid="Hotspot", password="pw"),
        )
        with patch("admin.network_watchdog._load_config_if_available", return_value=config):
            network_watchdog._tick(self.usb_root, "test-uuid", dry_run=False)

        mock_apply_home.assert_called_once_with(config.home)
        mock_apply_hotspot.assert_called_once_with(config.hotspot)

    @patch("admin.network_watchdog._set_admin_service_running")
    @patch("admin.network_watchdog.wifi.active_connection_name", return_value=None)
    @patch("admin.network_watchdog.wifi.has_usable_ip", return_value=True)
    @patch("admin.network_watchdog._load_config_if_available", return_value=None)
    def test_admin_service_started_when_connected(self, mock_load, mock_has_ip, mock_active_name, mock_set_running):
        network_watchdog._tick(self.usb_root, "test-uuid", dry_run=False)
        mock_set_running.assert_called_once_with(True)

    @patch("admin.network_watchdog._set_admin_service_running")
    @patch("admin.network_watchdog.wifi.active_connection_name", return_value=None)
    @patch("admin.network_watchdog.wifi.has_usable_ip", return_value=False)
    @patch("admin.network_watchdog._load_config_if_available", return_value=None)
    def test_admin_service_stopped_when_not_connected(self, mock_load, mock_has_ip, mock_active_name, mock_set_running):
        network_watchdog._tick(self.usb_root, "test-uuid", dry_run=False)
        mock_set_running.assert_called_once_with(False)

    def test_missing_usb_does_not_raise(self):
        # No USB mounted at all -- _load_config_if_available's own
        # os.path.isdir check should make this a no-op, not a crash.
        nonexistent_root = os.path.join(self.usb_root, "not-mounted")
        result = network_watchdog._load_config_if_available(nonexistent_root, "test-uuid")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
