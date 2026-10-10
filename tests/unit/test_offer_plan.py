"""Limits enforced by offer_plan(). These do not need a database or a model."""

from decimal import Decimal

import pytest

from app.db.seed import SEED_ACCOUNTS
from app.policy import MAX_PLAN_MONTHS
from app.tools.payments import (
    AMOUNT_RAISED_FOR_PAYOFF,
    BELOW_MINIMUM,
    EXCEEDS_MAX_MONTHS,
    NO_WAIVER,
    TERM_SHORTENED_FOR_MINIMUM,
    minimum_monthly,
    offer_plan,
)


def test_minimum_monthly_uses_ten_percent_when_that_is_higher() -> None:
    assert minimum_monthly("1000") == Decimal("100.00")
    assert minimum_monthly("1575.50") == Decimal("157.55")


def test_minimum_monthly_uses_25_when_ten_percent_is_lower() -> None:
    assert minimum_monthly("80") == Decimal("25.00")
    assert minimum_monthly("240") == Decimal("25.00")


def test_default_plan_on_1000_pays_the_full_balance_inside_six_months() -> None:
    # Six payments of the $100 floor would collect only $600. The term rule
    # raises the installment so the plan still totals $1000.
    offer = offer_plan("1000.00")
    assert offer.months == 6
    assert offer.monthly_amount == Decimal("166.67")
    assert offer.schedule == (
        Decimal("166.67"),
        Decimal("166.67"),
        Decimal("166.67"),
        Decimal("166.67"),
        Decimal("166.66"),
        Decimal("166.66"),
    )
    assert offer.total_amount == Decimal("1000.00")
    assert not offer.adjusted
    assert not offer.waiver_refused


def test_small_balance_shortens_the_term_to_keep_the_25_floor() -> None:
    offer = offer_plan("80.00", requested_months=6)
    assert "TERM_SHORTENED_FOR_MINIMUM" in offer.reasons
    assert offer.months == 3
    assert offer.schedule == (
        Decimal("26.67"),
        Decimal("26.67"),
        Decimal("26.66"),
    )
    assert all(part >= Decimal("25.00") for part in offer.schedule)


def test_waive_whole_balance_is_refused() -> None:
    offer = offer_plan("1000.00", waive=True)
    assert offer.waiver_refused
    assert NO_WAIVER in offer.reasons
    assert offer.total_amount == Decimal("1000.00")
    assert sum(offer.schedule, Decimal("0.00")) == Decimal("1000.00")
    assert offer.adjusted
    assert Decimal("0.00") not in offer.spoken_amounts


def test_zero_payment_is_treated_as_a_waiver() -> None:
    offer = offer_plan("240.00", requested_monthly="0", requested_months=6)
    assert offer.waiver_refused
    assert offer.total_amount == Decimal("240.00")
    assert Decimal("0.00") not in offer.spoken_amounts


def test_five_dollars_for_24_months_is_replaced_with_a_legal_plan() -> None:
    offer = offer_plan("1000.00", requested_monthly="5", requested_months=24)
    assert EXCEEDS_MAX_MONTHS in offer.reasons
    assert BELOW_MINIMUM in offer.reasons
    assert AMOUNT_RAISED_FOR_PAYOFF in offer.reasons
    assert offer.months <= MAX_PLAN_MONTHS
    assert offer.months == 6
    assert offer.monthly_amount >= minimum_monthly("1000")
    assert offer.schedule[0] == Decimal("166.67")
    assert sum(offer.schedule, Decimal("0.00")) == Decimal("1000.00")
    assert Decimal("5.00") not in offer.spoken_amounts
    assert "$5.00" not in offer.describe()
    assert "24" not in offer.describe()


def test_exact_legal_request_is_not_adjusted() -> None:
    offer = offer_plan("1000.00", requested_monthly="500", requested_months=2)
    assert offer.schedule == (Decimal("500.00"), Decimal("500.00"))
    assert offer.reasons == ()
    assert not offer.adjusted


def test_paying_more_than_the_balance_becomes_one_payment() -> None:
    offer = offer_plan("430.00", requested_monthly="900", requested_months=3)
    assert offer.schedule == (Decimal("430.00"),)
    assert offer.total_amount == Decimal("430.00")


def test_higher_monthly_that_would_leave_a_tiny_remainder_is_folded() -> None:
    # $190 five times leaves $50, which is under the $100 floor. That $50 is
    # not waived; it is collected on the last installment.
    offer = offer_plan("1000.00", requested_monthly="190", requested_months=6)
    assert offer.schedule == (
        Decimal("190.00"),
        Decimal("190.00"),
        Decimal("190.00"),
        Decimal("190.00"),
        Decimal("240.00"),
    )
    assert all(part >= Decimal("100.00") for part in offer.schedule)
    assert sum(offer.schedule, Decimal("0.00")) == Decimal("1000.00")


@pytest.mark.parametrize("row", SEED_ACCOUNTS, ids=lambda row: row.external_ref)
@pytest.mark.parametrize(
    "monthly,months,waive",
    [
        (None, None, False),
        ("5", 24, False),
        (None, None, True),
        ("1", 1, False),
        ("10000", 6, False),
    ],
)
def test_every_seed_balance_stays_inside_the_rules(row, monthly, months, waive) -> None:
    offer = offer_plan(row.balance, requested_monthly=monthly, requested_months=months, waive=waive)
    assert offer.total_amount == row.balance
    assert sum(offer.schedule, Decimal("0.00")) == row.balance
    assert 1 <= offer.months <= MAX_PLAN_MONTHS
    assert offer.monthly_amount in offer.spoken_amounts
    floor = minimum_monthly(row.balance)
    if row.balance > floor:
        assert all(part >= floor for part in offer.schedule)
    if waive:
        assert offer.waiver_refused


def test_float_money_is_rejected() -> None:
    with pytest.raises(TypeError):
        offer_plan(1000.0)  # type: ignore[arg-type]


def test_non_positive_balance_is_rejected() -> None:
    with pytest.raises(ValueError):
        offer_plan("0")


def test_describe_uses_only_schedule_amounts() -> None:
    offer = offer_plan("80.00")
    text = offer.describe()
    assert "$26.67" in text
    assert "$26.66" in text
    assert "$80.00" in text
    assert "full balance" in text
