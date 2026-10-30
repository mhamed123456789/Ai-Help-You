from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import os
from pathlib import Path
import sqlite3
from typing import Callable, Iterator


DAILY_CREDIT_LIMIT = 500
MIN_MESSAGE_CREDITS = 5
MAX_MESSAGE_CREDITS = 20
DEFAULT_CREDITS_FILE = (
    Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming")
    / "Ai Tool"
    / "credits.sqlite3"
)


class CreditsExhausted(ValueError):
    def __init__(self, balance: "CreditBalance") -> None:
        super().__init__("Daily credits are exhausted.")
        self.balance = balance


@dataclass(frozen=True)
class CreditBalance:
    credits: int
    credit_date: str
    reset_at: str

    def as_dict(self) -> dict[str, int | str]:
        return {
            "credits": self.credits,
            "daily_limit": DAILY_CREDIT_LIMIT,
            "reset_at": self.reset_at,
        }


def calculate_message_credits(message: str, image_count: int) -> int:
    if image_count < 0:
        raise ValueError("Image count cannot be negative.")
    text_cost = MIN_MESSAGE_CREDITS + len(message.strip()) // 500
    image_cost = image_count * 5
    return min(MAX_MESSAGE_CREDITS, max(MIN_MESSAGE_CREDITS, text_cost + image_cost))


class DailyCreditStore:
    def __init__(
        self,
        database_path: str | Path = DEFAULT_CREDITS_FILE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self._clock = clock or (lambda: datetime.now().astimezone())
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_credits (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    credits INTEGER NOT NULL CHECK (credits BETWEEN 0 AND 500),
                    credit_date TEXT NOT NULL
                )
                """
            )
            local_date = self._now().date()
            connection.execute(
                """
                INSERT OR IGNORE INTO daily_credits (id, credits, credit_date)
                VALUES (1, ?, ?)
                """,
                (DAILY_CREDIT_LIMIT, local_date.isoformat()),
            )

    def get_balance(self) -> CreditBalance:
        now = self._now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._refresh(connection, now)

    def charge(self, amount: int) -> CreditBalance:
        if not MIN_MESSAGE_CREDITS <= amount <= MAX_MESSAGE_CREDITS:
            raise ValueError("Credit charge is outside the configured limits.")
        now = self._now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            balance = self._refresh(connection, now)
            if balance.credits < amount:
                raise CreditsExhausted(balance)
            connection.execute(
                "UPDATE daily_credits SET credits = credits - ? WHERE id = 1",
                (amount,),
            )
            return self._refresh(connection, now)

    def refund(self, amount: int, credit_date: str) -> None:
        if not MIN_MESSAGE_CREDITS <= amount <= MAX_MESSAGE_CREDITS:
            raise ValueError("Credit refund is outside the configured limits.")
        now = self._now()
        if now.date().isoformat() != credit_date:
            return
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._refresh(connection, now)
            connection.execute(
                """
                UPDATE daily_credits
                SET credits = MIN(?, credits + ?)
                WHERE id = 1 AND credit_date = ?
                """,
                (DAILY_CREDIT_LIMIT, amount, credit_date),
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        try:
            connection.execute("PRAGMA busy_timeout = 10000")
            with connection:
                yield connection
        finally:
            connection.close()

    def _refresh(self, connection: sqlite3.Connection, now: datetime) -> CreditBalance:
        local_date = now.date()
        row = connection.execute(
            "SELECT credits, credit_date FROM daily_credits WHERE id = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("The daily credit balance could not be loaded.")
        if row[1] != local_date.isoformat():
            connection.execute(
                "UPDATE daily_credits SET credits = ?, credit_date = ? WHERE id = 1",
                (DAILY_CREDIT_LIMIT, local_date.isoformat()),
            )
            credits = DAILY_CREDIT_LIMIT
        else:
            credits = row[0]
        reset_at = datetime.combine(
            local_date + timedelta(days=1),
            time.min,
            tzinfo=now.tzinfo,
        )
        return CreditBalance(
            credits=credits,
            credit_date=local_date.isoformat(),
            reset_at=reset_at.isoformat(),
        )

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            return now.astimezone()
        return now.astimezone()
