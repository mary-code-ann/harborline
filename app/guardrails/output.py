"""Check a reply before it is sent. A failure is replaced with a safe line."""

import re
from dataclasses import dataclass
from decimal import Decimal

from app.agent.reply import UNSAFE
from app.agent.types import AccountFacts
from app.policy import DISCLOSURE_TEXT

# The integer part is either 1,000 or 1000. A bare {1,3} would read $1000 as $100.
_MONEY = re.compile(
    r"\$\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?"
    r"|\b(\d+(?:\.\d{1,2})?)\s+dollars\b",
    re.IGNORECASE,
)

NO_AMOUNT_BEFORE_VERIFICATION = "NO_AMOUNT_BEFORE_VERIFICATION"
NO_ACCOUNT_DETAIL_BEFORE_VERIFICATION = "NO_ACCOUNT_DETAIL_BEFORE_VERIFICATION"
DISCLOSURE_BEFORE_MONEY = "DISCLOSURE_BEFORE_MONEY"
AMOUNT_NOT_FROM_TOOL = "AMOUNT_NOT_FROM_TOOL"
DISCLOSURE_EXACT = "DISCLOSURE_EXACT"


@dataclass(frozen=True)
class GuardrailResult:
    passed: bool
    rule: str | None
    reply: str


def extract_amounts(text: str) -> list[Decimal]:
    found: list[Decimal] = []
    for match in _MONEY.finditer(text):
        whole = (match.group(1) or match.group(3) or "").replace(",", "")
        if not whole:
            continue
        cents = match.group(2)
        if cents is None:
            number = Decimal(whole).quantize(Decimal("0.01"))
        else:
            number = Decimal(f"{whole}.{cents}")
        found.append(number)
    return found


def _money_language(text: str) -> bool:
    return bool(_MONEY.search(text) or re.search(r"\bdollars\b", text, re.IGNORECASE))


def _problem(
    reply: str,
    *,
    action: str,
    verified: bool,
    disclosure_given: bool,
    authorized_amounts: set[Decimal],
    account: AccountFacts | None,
) -> str | None:
    if action == "disclose":
        return None if reply == DISCLOSURE_TEXT else DISCLOSURE_EXACT
    if not verified and _money_language(reply):
        return NO_AMOUNT_BEFORE_VERIFICATION
    if not verified and account is not None and _leaks_account(reply, account):
        return NO_ACCOUNT_DETAIL_BEFORE_VERIFICATION
    if _money_language(reply) and not disclosure_given:
        return DISCLOSURE_BEFORE_MONEY
    allowed = {amount.quantize(Decimal("0.01")) for amount in authorized_amounts}
    for amount in extract_amounts(reply):
        if amount not in allowed:
            return AMOUNT_NOT_FROM_TOOL
    return None


def check_reply(
    reply: str,
    *,
    action: str,
    verified: bool,
    disclosure_given: bool,
    authorized_amounts: set[Decimal],
    account: AccountFacts | None,
    fallback: str,
) -> GuardrailResult:
    """Send `reply` when it passes. Otherwise send `fallback`, or a fact-free line."""
    rule = _problem(
        reply,
        action=action,
        verified=verified,
        disclosure_given=disclosure_given,
        authorized_amounts=authorized_amounts,
        account=account,
    )
    if rule is None:
        return GuardrailResult(True, None, reply)
    fallback_rule = _problem(
        fallback,
        action=action,
        verified=verified,
        disclosure_given=disclosure_given,
        authorized_amounts=authorized_amounts,
        account=account,
    )
    safe = fallback if fallback_rule is None else UNSAFE
    return GuardrailResult(False, rule, safe)


def _leaks_account(reply: str, account: AccountFacts) -> bool:
    lowered = reply.casefold()
    if "northwind" in lowered:
        return True
    if account.full_name.casefold() in lowered:
        return True
    if account.date_of_birth.isoformat() in reply:
        return True
    return f"{account.balance:.2f}" in reply
