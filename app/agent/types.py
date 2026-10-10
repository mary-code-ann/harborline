"""Shared values for one call. These stay in memory until the API writes them."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.policy import ConversationState, Intent
from app.tools.identity import parse_dob
from app.tools.payments import money


class Classification(BaseModel):
    """Structured output from the classifier. Money stays a string so a float cannot sneak in."""

    intent: str = Intent.OTHER
    name: str | None = None
    dob: str | None = None
    requested_amount: str | None = None
    months: int | None = None
    waive: bool = False

    def birth_date(self) -> date | None:
        if not self.dob:
            return None
        parsed = parse_dob(self.dob)
        if parsed is not None:
            return parsed
        try:
            return date.fromisoformat(self.dob)
        except ValueError:
            return None

    def amount(self) -> Decimal | None:
        if self.requested_amount is None or self.requested_amount == "":
            return None
        try:
            return money(self.requested_amount)
        except (TypeError, ValueError):
            return None

    def has_new_terms(self) -> bool:
        return self.waive or self.amount() is not None or self.months is not None


@dataclass
class AccountFacts:
    external_ref: str
    full_name: str
    date_of_birth: date
    balance: Decimal
    creditor_name: str
    cease_contact: bool = False


@dataclass
class ConversationMemory:
    state: str = ConversationState.GREETING
    verified: bool = False
    disclosure_given: bool = False
    verification_attempts: int = 0
    end_reason: str | None = None
    pending_offer: dict | None = None
    cease_contact: bool = False


@dataclass
class TurnResult:
    reply: str
    state_before: str
    state_after: str
    intent: str | None
    extracted: dict
    prompt_text: str
    tool_name: str | None
    tool_input: dict | None
    tool_output: dict | None
    guardrail_pass: bool
    guardrail_rule: str | None
    action: str
    end_reason: str | None = None
    verified: bool = False
    disclosure_given: bool = False
    verification_attempts: int = 0
    cease_contact: bool = False
    escalation_reason: str | None = None
    plan_record: dict | None = None
    accept_plan: bool = False
    latency_ms: int = 0
    script: str = ""
    authorized_amounts: set[Decimal] = field(default_factory=set)


class CallerMessage(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class OpenCall(BaseModel):
    account_ref: str = Field(min_length=1, max_length=32)
