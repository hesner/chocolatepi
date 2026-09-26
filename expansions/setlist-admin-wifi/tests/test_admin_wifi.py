"""
wifi.py tests. `nmcli` calls are mocked throughout -- this exercises
the config encryption/decision logic, not real networking, per the
network testing safety protocol (SETLIST_ADMIN_SPECIFICATION.md section
8a): touching real `nmcli` state is only ever done on real hardware,
staged, with Ethernet connected as a safety net, never in a unit test.

Run with: python -m unittest tests/test_admin_wifi.py
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from admin import crypto, wifi  # noqa: E402


class TestNetworkConfigSerialization(unittest.TestCase):
    def test_round_trips_through_json(self):
        config = wifi.NetworkConfig(
            home=wifi.WifiProfile(ssid="HomeNet", password="home-secret"),
            hotspot=wifi.WifiProfile(ssid="PhoneHotspot", password="hotspot-secret"),
        )
        restored = wifi.NetworkConfig.from_json(config.to_json())
        self.assertEqual(restored, config)

    def test_missing_home_profile_round_trips_as_none(self):
        config = wifi.NetworkConfig(home=None, hotspot=wifi.WifiProfile(ssid="Phone", password="pw"))
        restored = wifi.NetworkConfig.from_json(config.to_json())
        self.assertIsNone(restored.home)
        self.assertEqual(restored.hotspot.ssid, "Phone")


class TestConfigFileRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, "network.enc")
        self.key = crypto.derive_key("machine-abc", "usb-123")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_save_then_load_recovers_the_same_config(self):
        config = wifi.NetworkConfig(
            home=wifi.WifiProfile(ssid="Home", password="s3cr3t"),
            hotspot=None,
        )
        wifi.save_config(self.path, self.key, config)

        loaded = wifi.load_config(self.path, self.key)

        self.assertEqual(loaded, config)

    def test_load_missing_file_returns_none_not_an_error(self):
        self.assertIsNone(wifi.load_config(self.path, self.key))

    def test_load_with_wrong_key_returns_none_not_an_error(self):
        # This is the actual behavior the watchdog depends on
        # (specification section 5): a config from a different Pi/USB
        # pairing should be treated the same as "no home WiFi configured",
        # not crash the boot-time flow.
        config = wifi.NetworkConfig(home=wifi.WifiProfile(ssid="Home", password="pw"), hotspot=None)
        wifi.save_config(self.path, self.key, config)

        wrong_key = crypto.derive_key("different-machine", "different-usb")
        self.assertIsNone(wifi.load_config(self.path, wrong_key))

    def test_saved_file_is_not_plaintext_readable(self):
        config = wifi.NetworkConfig(
            home=wifi.WifiProfile(ssid="MyHomeNetworkName", password="SuperSecretPassword123"),
            hotspot=None,
        )
        wifi.save_config(self.path, self.key, config)

        with open(self.path, "rb") as f:
            raw = f.read()
        self.assertNotIn(b"SuperSecretPassword123", raw)
        self.assertNotIn(b"MyHomeNetworkName", raw)


class TestNetworkManagerApplication(unittest.TestCase):
    """All real subprocess calls mocked -- see the module docstring for why."""

    @patch("admin.wifi.subprocess.run")
    def test_apply_home_profile_creates_connection_if_missing(self, mock_run):
        mock_run.side_effect = [
            MagicMock(stdout=""),  # `connection show` -- no existing connections
            MagicMock(),           # `connection add`
            MagicMock(),           # `connection modify`
        ]
        wifi.apply_home_profile(wifi.WifiProfile(ssid="Home", password="pw"))

        commands = [call.args[0] for call in mock_run.call_args_list]
        self.assertIn("add", commands[1])
        self.assertIn("modify", commands[2])

    @patch("admin.wifi.subprocess.run")
    def test_apply_home_profile_modifies_existing_connection_without_re_adding(self, mock_run):
        mock_run.side_effect = [
            MagicMock(stdout="setlist-admin-home\n"),  # already exists
            MagicMock(),  # `connection modify`
        ]
        wifi.apply_home_profile(wifi.WifiProfile(ssid="Home", password="pw"))

        self.assertEqual(mock_run.call_count, 2)
        self.assertIn("modify", mock_run.call_args_list[1].args[0])

    @patch("admin.wifi.subprocess.run")
    def test_apply_none_profile_does_nothing(self, mock_run):
        wifi.apply_home_profile(None)
        mock_run.assert_not_called()

    @patch("admin.wifi.subprocess.run")
    def test_home_profile_gets_higher_priority_than_hotspot(self, mock_run):
        mock_run.side_effect = [
            MagicMock(stdout=""), MagicMock(), MagicMock(),  # home: show/add/modify
            MagicMock(stdout=""), MagicMock(), MagicMock(),  # hotspot: show/add/modify
        ]
        wifi.apply_home_profile(wifi.WifiProfile(ssid="Home", password="pw"))
        wifi.apply_hotspot_profile(wifi.WifiProfile(ssid="Hotspot", password="pw"))

        home_modify_args = mock_run.call_args_list[2].args[0]
        hotspot_modify_args = mock_run.call_args_list[5].args[0]
        home_priority = int(home_modify_args[home_modify_args.index("connection.autoconnect-priority") + 1])
        hotspot_priority = int(hotspot_modify_args[hotspot_modify_args.index("connection.autoconnect-priority") + 1])
        self.assertGreater(home_priority, hotspot_priority)

    @patch("admin.wifi.subprocess.run")
    def test_has_usable_ip_true_when_state_is_connected(self, mock_run):
        mock_run.return_value = MagicMock(stdout="connected\n")
        self.assertTrue(wifi.has_usable_ip())

    @patch("admin.wifi.subprocess.run")
    def test_has_usable_ip_false_when_disconnected(self, mock_run):
        mock_run.return_value = MagicMock(stdout="disconnected\n")
        self.assertFalse(wifi.has_usable_ip())

    @patch("admin.wifi.subprocess.run")
    def test_has_usable_ip_false_when_nmcli_unavailable(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        self.assertFalse(wifi.has_usable_ip())


if __name__ == "__main__":
    unittest.main()
