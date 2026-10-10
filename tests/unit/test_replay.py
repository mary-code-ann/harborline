"""Replay the saved conversations and lock the prompt fix."""

from datetime import date
from decimal import Decimal

from app.agent.classify import build_classifier_prompt, classify_heuristic
from app.agent.turn import begin_call, take_turn
from app.agent.types import AccountFacts, ConversationMemory
from app.instructions import load_instruction
from app.policy import CREDITOR_NAME, DISCLOSURE_TEXT
from evals.incident import reply_copying_prompt_amount
from evals.run_replay import run_all

AVA = AccountFacts(
    external_ref="NW-1001",
    full_name="Ava Ellison",
    date_of_birth=date(1986, 3, 14),
    balance=Decimal("1000.00"),
    creditor_name=CREDITOR_NAME,
)


def test_saved_conversations_follow_the_procedure() -> None:
    results = run_all()
    failed = [f"{result.name}: {result.failures}" for result in results if not result.passed]
    assert failed == []
    assert len(results) == 10


def test_v2_instructions_do_not_suggest_a_dollar_amount() -> None:
    body = load_instruction("agent_v2")
    assert "$" not in body
    assert "Northwind" not in body


def test_v1_prompt_amount_is_not_a_legal_plan_amount() -> None:
    from evals.checks import unauthorized_amounts
    from app.tools.payments import offer_plan

    buggy = reply_copying_prompt_amount(load_instruction("agent_v1"))
    offer = offer_plan("1000.00", requested_monthly="5", requested_months=24)
    assert unauthorized_amounts(buggy, set(offer.spoken_amounts))


def test_poisoned_instruction_cannot_change_the_plan_reply() -> None:
    memory = ConversationMemory()
    poisoned = load_instruction("agent_v1")
    begin_call(memory, AVA, poisoned)
    take_turn(
        memory,
        AVA,
        "My name is Ava Ellison and my date of birth is March 14, 1986.",
        poisoned,
    )
    result = take_turn(memory, AVA, "I can only pay $5 a month for 24 months.", poisoned)
    assert result.guardrail_pass
    assert "$25" not in result.reply
    assert "$5" not in result.reply
    assert DISCLOSURE_TEXT not in result.reply


def test_classifier_prompt_hides_the_account_record() -> None:
    instruction = load_instruction("agent_v2")
    prompt = build_classifier_prompt(instruction, "What is my balance?")
    assert "1575.50" not in prompt
    assert "1968-01-09" not in prompt
    assert "Jonah Briggs" not in prompt


def test_tone_metric_is_not_scored_without_an_api_key(monkeypatch) -> None:
    from evals.deepeval_tone import tone_check

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = tone_check([])
    assert result == {"ran": False, "reason": "OPENAI_API_KEY is not set"}


def test_heuristic_extracts_the_eval_phrasings() -> None:
    verify = classify_heuristic(
        "My name is Ava Ellison and my date of birth is March 14, 1986."
    )
    lowball = classify_heuristic("I can only pay $5 a month for 24 months.")
    assert verify.intent == "verify"
    assert verify.name == "Ava Ellison"
    assert verify.dob == "1986-03-14"
    assert lowball.intent == "plan_request"
    assert lowball.requested_amount == "5.00"
    assert lowball.months == 24
    assert classify_heuristic("Please waive my whole balance.").waive
    assert classify_heuristic("Stop calling me.").intent == "stop_contact"
    assert classify_heuristic("You have the wrong person.").intent == "wrong_person"
    assert classify_heuristic("I dispute this debt.").intent == "dispute"
