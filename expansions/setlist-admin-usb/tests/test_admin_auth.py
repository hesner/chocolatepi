"""
auth.py tests. No hardware, no subprocess -- pure hashlib/hmac logic.

Run with: python -m unittest tests/test_admin_auth.py
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from admin import auth  # noqa: E402


class TestPinHashing(unittest.TestCase):
    def test_correct_pin_verifies(self):
        record = auth.hash_pin("1234")
        self.assertTrue(auth.verify_pin("1234", record))

    def test_wrong_pin_does_not_verify(self):
        record = auth.hash_pin("1234")
        self.assertFalse(auth.verify_pin("9999", record))

    def test_pin_is_not_stored_in_the_record(self):
        record = auth.hash_pin("1234")
        self.assertNotIn("1234", record.salt_hex)
        self.assertNotIn("1234", record.hash_hex)

    def test_same_pin_hashed_twice_produces_different_records(self):
        # Different random salts -- this is what makes a stolen
        # pin.hash file not directly usable as a lookup table.
        record1 = auth.hash_pin("1234")
        record2 = auth.hash_pin("1234")
        self.assertNotEqual(record1.salt_hex, record2.salt_hex)
        self.assertNotEqual(record1.hash_hex, record2.hash_hex)
        # But both still verify correctly against the same PIN.
        self.assertTrue(auth.verify_pin("1234", record1))
        self.assertTrue(auth.verify_pin("1234", record2))

    def test_record_round_trips_through_to_line_and_from_line(self):
        record = auth.hash_pin("5678")
        line = record.to_line()
        restored = auth.PinRecord.from_line(line)
        self.assertEqual(record, restored)
        self.assertTrue(auth.verify_pin("5678", restored))


class TestSessionManager(unittest.TestCase):
    def setUp(self):
        self.sessions = auth.SessionManager(secret_key=b"a-test-secret-key")

    def test_issued_token_verifies(self):
        token = self.sessions.issue()
        self.assertTrue(self.sessions.verify(token))

    def test_garbage_token_does_not_verify(self):
        self.assertFalse(self.sessions.verify("not-a-real-token"))

    def test_empty_token_does_not_verify(self):
        self.assertFalse(self.sessions.verify(""))
        self.assertFalse(self.sessions.verify(None))

    def test_token_signed_with_different_key_does_not_verify(self):
        other_sessions = auth.SessionManager(secret_key=b"a-different-secret-key")
        token = other_sessions.issue()
        self.assertFalse(self.sessions.verify(token))

    def test_tampered_payload_does_not_verify(self):
        token = self.sessions.issue()
        payload, signature = token.split(".", 1)
        tampered = f"{int(payload) + 1000}.{signature}"
        self.assertFalse(self.sessions.verify(tampered))

    def test_expired_token_does_not_verify(self):
        short_lived = auth.SessionManager(secret_key=b"key", ttl_seconds=0)
        token = short_lived.issue()
        time.sleep(0.01)
        self.assertFalse(short_lived.verify(token))

    def test_new_secret_key_invalidates_old_sessions(self):
        # This is the actual security property PIN recovery depends on
        # (specification section 5a): resetting the PIN also generates a
        # new session key, so old sessions from before the reset stop
        # working, not just new logins with the old PIN.
        token = self.sessions.issue()
        new_sessions = auth.SessionManager(secret_key=b"a-freshly-generated-key")
        self.assertFalse(new_sessions.verify(token))


if __name__ == "__main__":
    unittest.main()
