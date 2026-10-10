"""Code-written replies. Dollar figures in here come only from tool results."""

from decimal import Decimal

from app.policy import DISCLOSURE_TEXT
from app.tools.payments import (
    AMOUNT_RAISED_FOR_PAYOFF,
    BELOW_MINIMUM,
    CAPPED_AT_BALANCE,
    EXCEEDS_MAX_MONTHS,
    NO_WAIVER,
    PAY_IN_FULL_ONLY,
    TERM_SHORTENED_FOR_MINIMUM,
)

REASON_LINES = {
    NO_WAIVER: "I can't waive or reduce the balance.",
    BELOW_MINIMUM: "That monthly amount is below the minimum for this account.",
    EXCEEDS_MAX_MONTHS: "A plan can't run longer than 6 months.",
    AMOUNT_RAISED_FOR_PAYOFF: "That payment would not clear the balance in the allowed time.",
    TERM_SHORTENED_FOR_MINIMUM: "The term has to be shorter so each payment meets the minimum.",
    CAPPED_AT_BALANCE: "The plan collects the balance in one payment.",
    PAY_IN_FULL_ONLY: "The only plan on this account is one payment of the full balance.",
}

GREETING = (
    "Hello. This call is about a personal matter. "
    "Please tell me your full name and date of birth."
)
ASK_IDENTITY = "Please tell me your full name and date of birth."
ASK_IDENTITY_CALM = (
    "I'm sorry this is frustrating. I still have to start by confirming "
    "your full name and date of birth."
)
VERIFY_FAIL = "That does not match. Please tell me your full name and date of birth again."
MAX_ATTEMPTS = "I'm sorry, I can't verify those details. I'll end the call now."
WITHHOLD = "I can talk about the account only after I verify your full name and date of birth."
CEASE = "I'll stop contact about this matter and end the call now."
CEASE_ALREADY = "This matter is already marked cease contact. I won't continue the call."
WRONG_PARTY = "Sorry to have bothered you. I'll end the call now."
DISPUTE = "I've noted a dispute and passed it to a person. I won't argue about it."
HOLD = "I can help with the balance or a payment plan."
ACCEPT = "You're set. I'll end the call now."
ENDED = "This call has ended."
ESCALATED_FOLLOWUP = "A person is reviewing this. I can't continue the conversation."
UNSAFE = "I can't say that. Please ask again and I will follow the same steps."


def plan_script(reasons: list[str], description: str) -> str:
    """Explain limit codes in words, then quote the schedule offer_plan returned."""
    lines = [REASON_LINES[code] for code in reasons if code in REASON_LINES]
    if not lines:
        lines.append("Here is the payment plan.")
    lines.append(description)
    return " ".join(lines)


def balance_script(balance: Decimal, creditor_name: str) -> str:
    return f"The balance with {creditor_name} is ${balance:.2f}."
