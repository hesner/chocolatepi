"""
crypto.py tests. Needs a real `openssl` binary on PATH (present on
Raspberry Pi OS and on any dev machine with git/openssl installed) --
no mocking here, this is deliberately an integration test of the actual
subprocess call, since a hand-rolled mock of openssl's behavior
wouldn't actually prove the encryption round-trips correctly.

Run with: python -m unittest tests/test_admin_crypto.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from admin import crypto  # noqa: E402


class TestKeyDerivation(unittest.TestCase):
    def test_same_inputs_produce_same_key(self):
        key1 = crypto.derive_key("machine-abc", "usb-123")
        key2 = crypto.derive_key("machine-abc", "usb-123")
        self.assertEqual(key1, key2)

    def test_different_machine_id_produces_different_key(self):
        key1 = crypto.derive_key("machine-abc", "usb-123")
        key2 = crypto.derive_key("machine-xyz", "usb-123")
        self.assertNotEqual(key1, key2)

    def test_different_usb_uuid_produces_different_key(self):
        key1 = crypto.derive_key("machine-abc", "usb-123")
        key2 = crypto.derive_key("machine-abc", "usb-999")
        self.assertNotEqual(key1, key2)

    def test_key_is_hex_string(self):
        key = crypto.derive_key("machine-abc", "usb-123")
        int(key, 16)  # raises ValueError if not valid hex


class TestEncryptDecryptRoundTrip(unittest.TestCase):
    def test_round_trip_recovers_original_plaintext(self):
        key = crypto.derive_key("machine-abc", "usb-123")
        plaintext = b'{"ssid": "HomeNetwork", "password": "correct horse battery staple"}'

        ciphertext = crypto.encrypt(plaintext, key)
        recovered = crypto.decrypt(ciphertext, key)

        self.assertEqual(recovered, plaintext)

    def test_ciphertext_does_not_contain_plaintext(self):
        # Not a rigorous cryptographic property test -- just a sanity
        # check that this isn't accidentally a no-op / base64 pass-through.
        key = crypto.derive_key("machine-abc", "usb-123")
        plaintext = b"a very specific and identifiable secret string"

        ciphertext = crypto.encrypt(plaintext, key)

        self.assertNotIn(plaintext, ciphertext)

    def test_wrong_key_fails_to_decrypt(self):
        # This is the actual security property this project cares about
        # (specification section 5): a copy of this file on a different
        # Pi/USB pairing -- i.e. a different derived key -- must not
        # decrypt.
        right_key = crypto.derive_key("machine-abc", "usb-123")
        wrong_key = crypto.derive_key("machine-different", "usb-different")
        plaintext = b"home wifi password"

        ciphertext = crypto.encrypt(plaintext, right_key)

        with self.assertRaises(crypto.DecryptionError):
            crypto.decrypt(ciphertext, wrong_key)

    def test_corrupted_ciphertext_fails_to_decrypt(self):
        key = crypto.derive_key("machine-abc", "usb-123")
        ciphertext = crypto.encrypt(b"some data", key)
        corrupted = ciphertext[:-5] + b"xxxxx"

        with self.assertRaises(crypto.DecryptionError):
            crypto.decrypt(corrupted, key)

    def test_empty_plaintext_round_trips(self):
        key = crypto.derive_key("machine-abc", "usb-123")
        ciphertext = crypto.encrypt(b"", key)
        self.assertEqual(crypto.decrypt(ciphertext, key), b"")


class TestReadMachineId(unittest.TestCase):
    def test_reads_and_strips_file_contents(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".id") as f:
            f.write("  abc123def456  \n")
            path = f.name
        try:
            self.assertEqual(crypto.read_machine_id(path), "abc123def456")
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
