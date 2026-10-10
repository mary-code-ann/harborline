"""Checks the replay runner applies to every saved conversation."""

from decimal import Decimal

from app.guardrails.output import extract_amounts
from app.policy import DISCLOSURE_TEXT


def unauthorized_amounts(reply: str, allowed: set[Decimal]) -> list[Decimal]:
    permitted = {amount.quantize(Decimal("0.01")) for amount in allowed}
    return [amount for amount in extract_amounts(reply) if amount not in permitted]


def leaks_before_disclosure(
    replies: list[str], full_name: str, dob_iso: str, balance: Decimal
) -> list[str]:
    """Account facts are forbidden on every reply before the exact disclosure sentence."""
    problems: list[str] = []
    for reply in replies:
        if reply == DISCLOSURE_TEXT:
            break
        lowered = reply.casefold()
        if "$" in reply or "dollar" in lowered:
            problems.append(f"money before disclosure: {reply}")
        if "northwind" in lowered:
            problems.append(f"creditor name before disclosure: {reply}")
        if full_name.casefold() in lowered:
            problems.append(f"account name before disclosure: {reply}")
        if dob_iso in reply or f"{balance:.2f}" in reply:
            problems.append(f"account fact before disclosure: {reply}")
    return problems
