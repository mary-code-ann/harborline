"""Insert the five fictional Northwind Credit accounts.

Safe to run more than once: an existing external_ref is left alone.
"""

import asyncio
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db.models import Account
from app.db.session import SessionLocal
from app.policy import CREDITOR_NAME


@dataclass(frozen=True)
class SeedAccount:
    external_ref: str
    full_name: str
    date_of_birth: date
    balance: Decimal


# Fictional people. Balances are chosen so the plan rules each have a case:
# $1000 needs more than 10% to finish in 6 months, $240 makes the $25 floor
# bind over 10%, $80 cannot be split into 6 payments of at least $25.
SEED_ACCOUNTS: tuple[SeedAccount, ...] = (
    SeedAccount("NW-1001", "Ava Ellison", date(1986, 3, 14), Decimal("1000.00")),
    SeedAccount("NW-1002", "Marcus Hale", date(1979, 11, 2), Decimal("240.00")),
    SeedAccount("NW-1003", "Priya Nandakumar", date(1992, 7, 28), Decimal("80.00")),
    SeedAccount("NW-1004", "Jonah Briggs", date(1968, 1, 9), Decimal("1575.50")),
    SeedAccount("NW-1005", "Elena Voss", date(2001, 5, 19), Decimal("430.00")),
)


async def seed() -> int:
    inserted = 0
    async with SessionLocal() as session:
        for row in SEED_ACCOUNTS:
            existing = await session.scalar(
                select(Account).where(Account.external_ref == row.external_ref)
            )
            if existing is not None:
                continue
            session.add(
                Account(
                    external_ref=row.external_ref,
                    full_name=row.full_name,
                    date_of_birth=row.date_of_birth,
                    balance=row.balance,
                    creditor_name=CREDITOR_NAME,
                    cease_contact=False,
                )
            )
            inserted += 1
        await session.commit()
    return inserted


def main() -> None:
    inserted = asyncio.run(seed())
    print(f"Inserted {inserted} account(s). {len(SEED_ACCOUNTS)} are defined.")


if __name__ == "__main__":
    main()
