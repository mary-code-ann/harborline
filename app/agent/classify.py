"""Turn the caller's words into one intent and a few extracted fields.

The deterministic parser is what replay and local runs use. When an API key is
set, the service asks the model instead, then feeds the same structured result
into the state machine.
"""

import re

from app.agent.types import Classification
from app.policy import Intent
from app.tools.identity import extract_name, parse_dob

_STOP = (
    "stop calling",
    "stop contacting",
    "cease contact",
    "don't call",
    "do not call",
    "don't contact",
    "do not contact",
)
_WRONG = (
    "wrong person",
    "wrong number",
    "wrong party",
    "not that person",
    "you have the wrong",
)
_DISPUTE = ("dispute", "not my debt", "don't owe", "do not owe", "never owed")
_WAIVE = ("waive", "write off", "write-off", "forgive the", "discount", "settle for")
_ACCEPT = (
    "i'll take",
    "i will take",
    "that works",
    "set it up",
    "i agree",
    "accept the plan",
)
_AMOUNT = re.compile(
    r"\$\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?"
    r"|\b(\d+(?:\.\d{1,2})?)\s*(?:dollars|a month|per month)\b",
    re.IGNORECASE,
)
_MONTHS = re.compile(r"\b(\d+)\s*months?\b", re.IGNORECASE)


def build_classifier_prompt(instruction: str, caller_text: str) -> str:
    """The prompt sent to the model. It must not contain the account balance or date of birth."""
    return (
        f"{instruction.rstrip()}\n\n"
        "Classify the caller message into one intent: verify, balance, pay, "
        "plan_request, dispute, stop_contact, wrong_person, or other.\n"
        "Extract name, dob, requested_amount, and months only when the caller stated them.\n"
        "Set waive to true only when they ask to reduce or erase what is owed.\n"
        "Do not include any account record in your answer.\n\n"
        f"Caller: {caller_text}"
    )


def _amount_string(text: str) -> str | None:
    match = _AMOUNT.search(text)
    if not match:
        return None
    whole = match.group(1) or match.group(3)
    if whole is None:
        return None
    cents = match.group(2)
    number = whole.replace(",", "")
    if cents:
        return f"{number}.{cents}"
    if "." in number:
        return number
    return f"{number}.00"


def _months(text: str) -> int | None:
    match = _MONTHS.search(text)
    if not match:
        return None
    return int(match.group(1))


def _is_acceptance(text: str) -> bool:
    lowered = " ".join(text.casefold().split())
    if any(phrase in lowered for phrase in _ACCEPT):
        return True
    return lowered in {"yes", "yes.", "ok", "okay", "sure", "yes please"}


def classify_heuristic(caller_text: str) -> Classification:
    """A small parser for replay. It understands the phrasings in evals/conversations."""
    text = " ".join(caller_text.split())
    lowered = text.casefold()
    name = extract_name(text)
    born = parse_dob(text)
    amount = _amount_string(text)
    months = _months(text)
    waive = any(phrase in lowered for phrase in _WAIVE)

    if any(phrase in lowered for phrase in _STOP):
        intent = Intent.STOP_CONTACT
    elif any(phrase in lowered for phrase in _WRONG):
        intent = Intent.WRONG_PERSON
    elif any(phrase in lowered for phrase in _DISPUTE):
        intent = Intent.DISPUTE
    elif waive:
        intent = Intent.PLAN_REQUEST
    elif name and born:
        intent = Intent.VERIFY
    elif "balance" in lowered or "how much" in lowered or "what do i owe" in lowered:
        intent = Intent.BALANCE
    elif amount or months or "payment plan" in lowered or "pay" in lowered:
        intent = Intent.PLAN_REQUEST if (amount or months or "plan" in lowered) else Intent.PAY
    elif _is_acceptance(text):
        intent = Intent.PAY
    else:
        intent = Intent.OTHER

    return Classification(
        intent=intent,
        name=name,
        dob=born.isoformat() if born else None,
        requested_amount=amount,
        months=months,
        waive=waive,
    )
