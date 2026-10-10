"""Decide the one action this turn is allowed to take.

The function is pure. It does not read the database and it does not call the model.
"""

from dataclasses import dataclass

from app.policy import MAX_VERIFY_ATTEMPTS, ConversationState, EndReason, Intent


class Action:
    DISCLOSE = "disclose"
    VERIFY_FAIL = "verify_fail"
    MAX_ATTEMPTS = "max_attempts"
    WITHHOLD = "withhold"
    ASK_IDENTITY = "ask_identity"
    BALANCE = "balance"
    OFFER_PLAN = "offer_plan"
    ACCEPT_PLAN = "accept_plan"
    CEASE = "cease"
    WRONG_PARTY = "wrong_party"
    DISPUTE = "dispute"
    HOLD = "hold"
    ENDED = "ended"


@dataclass(frozen=True)
class Decision:
    action: str
    next_state: str
    end_reason: str | None = None
    failed_attempt: bool = False


def decide(
    state: str,
    intent: str,
    *,
    matched: bool | None,
    attempts: int,
    has_new_terms: bool,
    has_pending_offer: bool,
) -> Decision:
    """Return the next action. `matched` is True, False, or None when no identity was offered."""
    if state in ConversationState.TERMINAL:
        return Decision(Action.ENDED, state, end_reason=None)

    if intent == Intent.STOP_CONTACT:
        return Decision(Action.CEASE, ConversationState.ENDED, EndReason.CEASE_CONTACT)
    if intent == Intent.WRONG_PERSON:
        return Decision(Action.WRONG_PARTY, ConversationState.ENDED, EndReason.WRONG_PARTY)
    if intent == Intent.DISPUTE:
        return Decision(Action.DISPUTE, ConversationState.ESCALATED, EndReason.DISPUTE)

    if state == ConversationState.DISCLOSURE:
        state = ConversationState.NEGOTIATING
    elif state == ConversationState.GREETING:
        state = ConversationState.VERIFYING

    if state == ConversationState.VERIFYING:
        return _while_verifying(intent, matched, attempts)

    return _while_negotiating(intent, has_new_terms, has_pending_offer)


def _while_verifying(intent: str, matched: bool | None, attempts: int) -> Decision:
    if matched is True:
        return Decision(Action.DISCLOSE, ConversationState.DISCLOSURE)
    if matched is False:
        if attempts + 1 >= MAX_VERIFY_ATTEMPTS:
            return Decision(
                Action.MAX_ATTEMPTS,
                ConversationState.ENDED,
                EndReason.MAX_ATTEMPTS,
                failed_attempt=True,
            )
        return Decision(Action.VERIFY_FAIL, ConversationState.VERIFYING, failed_attempt=True)
    if intent in (Intent.BALANCE, Intent.PAY, Intent.PLAN_REQUEST):
        return Decision(Action.WITHHOLD, ConversationState.VERIFYING)
    return Decision(Action.ASK_IDENTITY, ConversationState.VERIFYING)


def _while_negotiating(intent: str, has_new_terms: bool, has_pending_offer: bool) -> Decision:
    if intent == Intent.BALANCE:
        return Decision(Action.BALANCE, ConversationState.NEGOTIATING)
    if intent == Intent.PAY and not has_new_terms and has_pending_offer:
        return Decision(Action.ACCEPT_PLAN, ConversationState.ENDED, EndReason.COMPLETED)
    if intent in (Intent.PLAN_REQUEST, Intent.PAY):
        return Decision(Action.OFFER_PLAN, ConversationState.NEGOTIATING)
    return Decision(Action.HOLD, ConversationState.NEGOTIATING)
