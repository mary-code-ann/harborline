"""Guardrail rules. Dollar amounts have to come from a tool, and only after disclosure."""

from datetime import date
from decimal import Decimal

from app.agent.types import AccountFacts
from app.guardrails.output import (
    AMOUNT_NOT_FROM_TOOL,
    DISCLOSURE_BEFORE_MONEY,
    DISCLOSURE_EXACT,
    NO_ACCOUNT_DETAIL_BEFORE_VERIFICATION,
    NO_AMOUNT_BEFORE_VERIFICATION,
    check_reply,
)
from app.policy import DISCLOSURE_TEXT
from app.tools.payments import offer_plan

ACCOUNT = AccountFacts(
    external_ref="NW-1001",
    full_name="Ava Ellison",
    date_of_birth=date(1986, 3, 14),
    balance=Decimal("1000.00"),
    creditor_name="Northwind Credit",
)


def _check(reply: str, **kwargs):
    defaults = dict(
        action="hold",
        verified=False,
        disclosure_given=False,
        authorized_amounts=set(),
        account=ACCOUNT,
        fallback="Please tell me your full name and date of birth.",
    )
    defaults.update(kwargs)
    return check_reply(reply, **defaults)


def test_dollar_amount_before_verification_is_replaced() -> None:
    result = _check("Your balance is $1000.00.")
    assert not result.passed
    assert result.rule == NO_AMOUNT_BEFORE_VERIFICATION
    assert "$" not in result.reply


def test_creditor_name_before_verification_is_replaced() -> None:
    result = _check("This is Northwind Credit calling.")
    assert result.rule == NO_ACCOUNT_DETAIL_BEFORE_VERIFICATION
    assert "northwind" not in result.reply.casefold()


def test_disclosure_must_be_exact() -> None:
    result = _check(
        "This is an attempt to collect a debt.",
        action="disclose",
        fallback=DISCLOSURE_TEXT,
    )
    assert result.rule == DISCLOSURE_EXACT
    assert result.reply == DISCLOSURE_TEXT


def test_exact_disclosure_passes() -> None:
    result = _check(DISCLOSURE_TEXT, action="disclose", fallback=DISCLOSURE_TEXT)
    assert result.passed
    assert result.reply == DISCLOSURE_TEXT


def test_money_before_disclosure_fails_even_after_a_name_match() -> None:
    result = _check(
        "The balance is $1000.00.",
        action="balance",
        verified=True,
        disclosure_given=False,
        authorized_amounts={Decimal("1000.00")},
    )
    assert result.rule == DISCLOSURE_BEFORE_MONEY


def test_amount_that_offer_plan_did_not_return_fails() -> None:
    offer = offer_plan("1000.00", requested_monthly="5", requested_months=24)
    result = _check(
        "We can set this up for $25 a month.",
        action="offer_plan",
        verified=True,
        disclosure_given=True,
        authorized_amounts=set(offer.spoken_amounts),
        fallback=offer.describe(),
    )
    assert result.rule == AMOUNT_NOT_FROM_TOOL
    assert result.reply == offer.describe()
    assert "$25" not in result.reply


def test_schedule_from_offer_plan_passes() -> None:
    offer = offer_plan("1000.00")
    result = _check(
        offer.describe(),
        action="offer_plan",
        verified=True,
        disclosure_given=True,
        authorized_amounts=set(offer.spoken_amounts),
        fallback="I can't say that.",
    )
    assert result.passed
    assert result.reply == offer.describe()
