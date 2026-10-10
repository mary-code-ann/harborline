"""The written procedure and the fictional seed stay aligned with the code."""

from pathlib import Path

from app.db.base import Base
from app.db.seed import SEED_ACCOUNTS
from app.policy import CREDITOR_NAME, DISCLOSURE_TEXT, EndReason

EXPECTED_TABLES = {
    "accounts",
    "conversations",
    "turns",
    "traces",
    "instruction_versions",
    "payment_plans",
    "escalations",
    "eval_runs",
}


def test_procedure_contains_the_exact_disclosure() -> None:
    text = Path("docs/procedure.md").read_text(encoding="utf-8")
    assert DISCLOSURE_TEXT in text
    assert EndReason.DISPUTE in text
    assert EndReason.CEASE_CONTACT in text
    assert EndReason.WRONG_PARTY in text
    assert "offer_plan()" in text


def test_seed_is_five_fictional_accounts() -> None:
    assert len(SEED_ACCOUNTS) == 5
    refs = [row.external_ref for row in SEED_ACCOUNTS]
    assert len(set(refs)) == 5
    for row in SEED_ACCOUNTS:
        assert row.full_name.strip()
        assert row.date_of_birth.year
        assert row.balance > 0
        assert row.external_ref.startswith("NW-")


def test_creditor_name_is_the_fictional_one() -> None:
    assert CREDITOR_NAME == "Northwind Credit"


def test_metadata_registers_every_table() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES
