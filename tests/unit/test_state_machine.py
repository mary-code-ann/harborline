"""State machine transitions. These do not call a model or a database."""

from app.agent.machine import Action, decide
from app.policy import ConversationState, EndReason, Intent


def test_match_moves_to_disclosure() -> None:
    decision = decide(
        ConversationState.VERIFYING,
        Intent.VERIFY,
        matched=True,
        attempts=0,
        has_new_terms=False,
        has_pending_offer=False,
    )
    assert decision.action == Action.DISCLOSE
    assert decision.next_state == ConversationState.DISCLOSURE
    assert not decision.failed_attempt


def test_two_failures_stay_in_verifying_and_the_third_ends() -> None:
    first = decide(
        ConversationState.VERIFYING,
        Intent.VERIFY,
        matched=False,
        attempts=0,
        has_new_terms=False,
        has_pending_offer=False,
    )
    second = decide(
        ConversationState.VERIFYING,
        Intent.VERIFY,
        matched=False,
        attempts=1,
        has_new_terms=False,
        has_pending_offer=False,
    )
    third = decide(
        ConversationState.VERIFYING,
        Intent.VERIFY,
        matched=False,
        attempts=2,
        has_new_terms=False,
        has_pending_offer=False,
    )
    assert first.action == Action.VERIFY_FAIL
    assert first.next_state == ConversationState.VERIFYING
    assert second.action == Action.VERIFY_FAIL
    assert third.action == Action.MAX_ATTEMPTS
    assert third.next_state == ConversationState.ENDED
    assert third.end_reason == EndReason.MAX_ATTEMPTS


def test_balance_before_verification_does_not_count_as_an_attempt() -> None:
    decision = decide(
        ConversationState.VERIFYING,
        Intent.BALANCE,
        matched=None,
        attempts=0,
        has_new_terms=False,
        has_pending_offer=False,
    )
    assert decision.action == Action.WITHHOLD
    assert decision.next_state == ConversationState.VERIFYING
    assert not decision.failed_attempt


def test_stop_and_wrong_person_end_from_verifying() -> None:
    stop = decide(
        ConversationState.VERIFYING,
        Intent.STOP_CONTACT,
        matched=None,
        attempts=0,
        has_new_terms=False,
        has_pending_offer=False,
    )
    wrong = decide(
        ConversationState.GREETING,
        Intent.WRONG_PERSON,
        matched=None,
        attempts=0,
        has_new_terms=False,
        has_pending_offer=False,
    )
    assert stop.action == Action.CEASE
    assert stop.end_reason == EndReason.CEASE_CONTACT
    assert stop.next_state == ConversationState.ENDED
    assert wrong.action == Action.WRONG_PARTY
    assert wrong.end_reason == EndReason.WRONG_PARTY


def test_dispute_escalates_without_ending_as_a_normal_call() -> None:
    decision = decide(
        ConversationState.NEGOTIATING,
        Intent.DISPUTE,
        matched=True,
        attempts=0,
        has_new_terms=False,
        has_pending_offer=False,
    )
    assert decision.action == Action.DISPUTE
    assert decision.next_state == ConversationState.ESCALATED
    assert decision.end_reason == EndReason.DISPUTE


def test_disclosure_state_handles_the_next_request_as_negotiation() -> None:
    decision = decide(
        ConversationState.DISCLOSURE,
        Intent.PLAN_REQUEST,
        matched=True,
        attempts=1,
        has_new_terms=True,
        has_pending_offer=False,
    )
    assert decision.action == Action.OFFER_PLAN
    assert decision.next_state == ConversationState.NEGOTIATING


def test_accepting_a_pending_plan_completes_the_call() -> None:
    decision = decide(
        ConversationState.NEGOTIATING,
        Intent.PAY,
        matched=True,
        attempts=1,
        has_new_terms=False,
        has_pending_offer=True,
    )
    assert decision.action == Action.ACCEPT_PLAN
    assert decision.end_reason == EndReason.COMPLETED


def test_new_terms_offer_a_plan_instead_of_accepting_the_old_one() -> None:
    decision = decide(
        ConversationState.NEGOTIATING,
        Intent.PAY,
        matched=True,
        attempts=1,
        has_new_terms=True,
        has_pending_offer=True,
    )
    assert decision.action == Action.OFFER_PLAN


def test_terminal_states_stay_put() -> None:
    ended = decide(
        ConversationState.ENDED,
        Intent.BALANCE,
        matched=True,
        attempts=3,
        has_new_terms=False,
        has_pending_offer=False,
    )
    escalated = decide(
        ConversationState.ESCALATED,
        Intent.PLAN_REQUEST,
        matched=True,
        attempts=1,
        has_new_terms=True,
        has_pending_offer=False,
    )
    assert ended.action == Action.ENDED
    assert ended.next_state == ConversationState.ENDED
    assert escalated.next_state == ConversationState.ESCALATED
