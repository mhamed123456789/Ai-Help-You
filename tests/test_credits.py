from datetime import datetime
import tempfile
import unittest
from pathlib import Path

from credits import (
    DAILY_CREDIT_LIMIT,
    CreditsExhausted,
    DailyCreditStore,
    calculate_message_credits,
)


class DailyCreditStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.now = [datetime(2026, 10, 30, 12, 0).astimezone()]
        self.database_path = Path(self.temporary.name) / "credits.sqlite3"
        self.store = DailyCreditStore(
            self.database_path,
            clock=lambda: self.now[0],
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_first_install_starts_with_500_credits_and_persists_balance(self):
        self.assertEqual(self.store.get_balance().credits, DAILY_CREDIT_LIMIT)
        self.store.charge(20)

        reopened = DailyCreditStore(
            self.database_path,
            clock=lambda: self.now[0],
        )
        self.assertEqual(reopened.get_balance().credits, 480)

    def test_daily_allowance_resets_on_local_midnight(self):
        self.store.charge(20)
        self.now[0] = self.now[0].replace(hour=23, minute=59, second=59)
        self.assertEqual(self.store.get_balance().credits, 480)
        self.now[0] = self.now[0].replace(day=31, hour=0, minute=0, second=0)

        balance = self.store.get_balance()
        self.assertEqual(balance.credits, DAILY_CREDIT_LIMIT)
        self.assertTrue(balance.reset_at.startswith("2026-11-01T00:00:00"))

    def test_empty_balance_rejects_another_message(self):
        for _ in range(25):
            self.store.charge(20)

        with self.assertRaises(CreditsExhausted) as error:
            self.store.charge(5)

        self.assertEqual(error.exception.balance.credits, 0)

    def test_refund_restores_credits_after_failure_but_not_after_daily_reset(self):
        balance = self.store.charge(15)
        self.store.refund(15, balance.credit_date)
        self.assertEqual(self.store.get_balance().credits, DAILY_CREDIT_LIMIT)

        old_date = self.store.charge(15).credit_date
        self.now[0] = self.now[0].replace(day=31, hour=0, minute=0)
        self.store.get_balance()
        self.store.refund(15, old_date)
        self.assertEqual(self.store.get_balance().credits, DAILY_CREDIT_LIMIT)

    def test_credit_cost_is_between_five_and_twenty_per_message(self):
        self.assertEqual(calculate_message_credits("Hi", 0), 5)
        self.assertEqual(calculate_message_credits("x" * 2500, 0), 10)
        self.assertEqual(calculate_message_credits("Hi", 1), 10)
        self.assertEqual(calculate_message_credits("x" * 20_000, 4), 20)


if __name__ == "__main__":
    unittest.main()
