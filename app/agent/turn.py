"""Run one caller turn: classify, decide, call a tool, phrase, then guard."""

from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter

from app.agent.classify import build_classifier_prompt, classify_heuristic
from app.agent.machine import Action, decide
from app.agent.reply import (
    ACCEPT,
    ASK_IDENTITY,
    ASK_IDENTITY_CALM,
    CEASE,
    CEASE_ALREADY,
    DISPUTE,
    ENDED,
    ESCALATED_FOLLOWUP,
    GREETING,
    HOLD,
    MAX_ATTEMPTS,
    UNSAFE,
    VERIFY_FAIL,
    WITHHOLD,
    WRONG_PARTY,
    balance_script,
    plan_script,
)
from app.agent.types import AccountFacts, Classification, ConversationMemory, TurnResult
from app.guardrails.output import check_reply
from app.policy import DISCLOSURE_TEXT, EndReason, Intent
from app.tools.identity import names_match
from app.tools.payments import PlanOffer, offer_plan


@dataclass
class _Tool:
    name: str | None
    input: dict | None
    output: dict | None
    script: str
    authorized: set[Decimal]
    escalation_reason: str | None = None
    plan_record: dict | None = None
    accept_plan: bool = False
    cease_contact: bool = False


def begin_call(memory: ConversationMemory, account: AccountFacts, instruction: str) -> TurnResult:
    """The opening line. The model is not called, and no account fact is spoken."""
    started = perf_counter()
    before = memory.state
    if account.cease_contact or memory.cease_contact:
        memory.state = "ENDED"
        memory.end_reason = EndReason.CEASE_CONTACT
        memory.cease_contact = True
        script = CEASE_ALREADY
        action = Action.CEASE
    else:
        memory.state = "VERIFYING"
        script = GREETING
        action = Action.ASK_IDENTITY
    checked = check_reply(
        script,
        action=action,
        verified=False,
        disclosure_given=False,
        authorized_amounts=set(),
        account=account,
        fallback=UNSAFE,
    )
    return _result(
        memory,
        before=before,
        classification=None,
        prompt_text="code: opening line, model not called\n" + instruction,
        tool=_Tool(None, None, None, checked.reply, set()),
        action=action,
        checked_pass=checked.passed,
        checked_rule=checked.rule,
        reply=checked.reply,
        started=started,
    )


def take_turn(
    memory: ConversationMemory,
    account: AccountFacts,
    caller_text: str,
    instruction: str,
    classification: Classification | None = None,
) -> TurnResult:
    """Advance one caller message. `classification` overrides the local parser."""
    started = perf_counter()
    before = memory.state
    prompt = build_classifier_prompt(instruction, caller_text)
    if classification is None:
        classification = classify_heuristic(caller_text)

    if memory.state in ("ESCALATED", "ENDED"):
        script = ESCALATED_FOLLOWUP if memory.state == "ESCALATED" else ENDED
        tool = _Tool(None, None, None, script, set())
        decision_action = Action.ENDED
        checked = _guard(memory, account, decision_action, script, set(), script)
        return _result(
            memory,
            before=before,
            classification=classification,
            prompt_text=prompt,
            tool=tool,
            action=decision_action,
            checked_pass=checked.passed,
            checked_rule=checked.rule,
            reply=checked.reply,
            started=started,
        )

    matched = _matched(account, classification)
    if classification.intent == Intent.VERIFY and matched is None:
        matched = False
    decision = decide(
        memory.state,
        classification.intent,
        matched=matched,
        attempts=memory.verification_attempts,
        has_new_terms=classification.has_new_terms(),
        has_pending_offer=memory.pending_offer is not None,
    )
    if decision.failed_attempt:
        memory.verification_attempts += 1
    tool = _run_tool(decision.action, memory, account, classification, caller_text)
    if decision.action == Action.DISCLOSE:
        memory.verified = True
        memory.disclosure_given = True
    if decision.action == Action.CEASE:
        memory.cease_contact = True
        account.cease_contact = True
    if decision.end_reason:
        memory.end_reason = decision.end_reason
    memory.state = decision.next_state

    checked = _guard(memory, account, decision.action, tool.script, tool.authorized, tool.script)
    return _result(
        memory,
        before=before,
        classification=classification,
        prompt_text=prompt,
        tool=tool,
        action=decision.action,
        checked_pass=checked.passed,
        checked_rule=checked.rule,
        reply=checked.reply,
        started=started,
    )


def apply_phrased_reply(
    result: TurnResult,
    phrased: str,
    phrase_prompt: str,
    account: AccountFacts,
    *,
    verified_before: bool,
    disclosure_before: bool,
) -> TurnResult:
    """Guard a model-written reply. On failure the caller hears the code script."""
    checked = check_reply(
        phrased,
        action=result.action,
        verified=verified_before or result.action == Action.DISCLOSE,
        disclosure_given=disclosure_before or result.action == Action.DISCLOSE,
        authorized_amounts=result.authorized_amounts,
        account=account,
        fallback=result.script or UNSAFE,
    )
    result.reply = checked.reply
    result.guardrail_pass = checked.passed
    result.guardrail_rule = checked.rule
    result.prompt_text = result.prompt_text + "\n---\n" + phrase_prompt
    return result


def _matched(account: AccountFacts, classification: Classification) -> bool | None:
    born = classification.birth_date()
    if not classification.name and born is None:
        return None
    if not classification.name or born is None:
        return False
    return names_match(classification.name, account.full_name) and born == account.date_of_birth


def _run_tool(
    action: str,
    memory: ConversationMemory,
    account: AccountFacts,
    classification: Classification,
    caller_text: str = "",
) -> _Tool:
    if action == Action.DISCLOSE:
        return _Tool("verify_identity", _stated(classification), {"matched": True}, DISCLOSURE_TEXT, set())
    if action == Action.VERIFY_FAIL:
        return _Tool(
            "verify_identity",
            _stated(classification),
            {"matched": False},
            VERIFY_FAIL,
            set(),
        )
    if action == Action.MAX_ATTEMPTS:
        return _Tool(
            "end_call",
            {"reason": EndReason.MAX_ATTEMPTS},
            {"ended": True},
            MAX_ATTEMPTS,
            set(),
        )
    if action == Action.WITHHOLD:
        return _Tool("get_account", {"verified": False}, {"verified": False}, WITHHOLD, set())
    if action == Action.ASK_IDENTITY:
        script = _identity_prompt(classification.intent, caller_text)
        return _Tool(None, None, None, script, set())
    if action == Action.CEASE:
        return _Tool(
            "end_call",
            {"reason": EndReason.CEASE_CONTACT},
            {"ended": True, "cease_contact": True},
            CEASE,
            set(),
            escalation_reason=EndReason.CEASE_CONTACT,
            cease_contact=True,
        )
    if action == Action.WRONG_PARTY:
        return _Tool(
            "end_call",
            {"reason": EndReason.WRONG_PARTY},
            {"ended": True},
            WRONG_PARTY,
            set(),
            escalation_reason=EndReason.WRONG_PARTY,
        )
    if action == Action.DISPUTE:
        return _Tool(
            "escalate",
            {"reason": EndReason.DISPUTE},
            {"escalated": True},
            DISPUTE,
            set(),
            escalation_reason=EndReason.DISPUTE,
        )
    if action == Action.BALANCE:
        payload = {
            "verified": True,
            "full_name": account.full_name,
            "balance": f"{account.balance:.2f}",
            "creditor_name": account.creditor_name,
        }
        return _Tool(
            "get_account",
            {"verified": True},
            payload,
            balance_script(account.balance, account.creditor_name),
            {account.balance},
        )
    if action == Action.OFFER_PLAN:
        offer = offer_plan(
            account.balance,
            requested_monthly=classification.amount(),
            requested_months=classification.months,
            waive=classification.waive,
        )
        record = _offer_payload(offer)
        memory.pending_offer = record
        return _Tool(
            "offer_plan",
            {
                "balance": f"{account.balance:.2f}",
                "requested_monthly": classification.requested_amount,
                "requested_months": classification.months,
                "waive": classification.waive,
            },
            record,
            plan_script(list(offer.reasons), offer.describe()),
            set(offer.spoken_amounts),
            plan_record=record,
        )
    if action == Action.ACCEPT_PLAN:
        record = memory.pending_offer or {}
        return _Tool(
            "record_payment_plan",
            record,
            {"status": "accepted"},
            ACCEPT,
            set(),
            plan_record=record,
            accept_plan=True,
        )
    if action == Action.HOLD:
        return _Tool(None, None, None, HOLD, set())
    return _Tool(None, None, None, ENDED, set())


def _identity_prompt(intent: str, caller_text: str) -> str:
    upset = any(
        word in caller_text.casefold() for word in ("furious", "ridiculous", "thieves", "angry")
    )
    if intent == Intent.OTHER and upset:
        return ASK_IDENTITY_CALM
    if intent == Intent.OTHER:
        return (
            "I can only help with this call. Please tell me your full name and date of birth."
        )
    return ASK_IDENTITY


def _stated(classification: Classification) -> dict:
    return {"name": classification.name, "dob": classification.dob}


def _offer_payload(offer: PlanOffer) -> dict:
    return {
        "monthly_amount": f"{offer.monthly_amount:.2f}",
        "months": offer.months,
        "total_amount": f"{offer.total_amount:.2f}",
        "schedule": [f"{part:.2f}" for part in offer.schedule],
        "reasons": list(offer.reasons),
        "waiver_refused": offer.waiver_refused,
        "description": offer.describe(),
    }


def _guard(memory, account, action, script, authorized, fallback):
    verified = memory.verified and action != Action.DISCLOSE
    # The disclose action is the moment verification succeeds. The reply itself
    # is the disclosure, so money rules use the pre-reply flags.
    disclosure_given = memory.disclosure_given and action != Action.DISCLOSE
    if action == Action.DISCLOSE:
        verified = False
        disclosure_given = False
    return check_reply(
        script,
        action=action,
        verified=verified,
        disclosure_given=disclosure_given,
        authorized_amounts=authorized,
        account=account,
        fallback=fallback if action != Action.DISCLOSE else DISCLOSURE_TEXT,
    )


def _result(
    memory: ConversationMemory,
    *,
    before: str,
    classification: Classification | None,
    prompt_text: str,
    tool: _Tool,
    action: str,
    checked_pass: bool,
    checked_rule: str | None,
    reply: str,
    started: float,
) -> TurnResult:
    extracted = classification.model_dump() if classification else {}
    return TurnResult(
        reply=reply,
        state_before=before,
        state_after=memory.state,
        intent=classification.intent if classification else None,
        extracted=extracted,
        prompt_text=prompt_text,
        tool_name=tool.name,
        tool_input=tool.input,
        tool_output=tool.output,
        guardrail_pass=checked_pass,
        guardrail_rule=checked_rule,
        action=action,
        end_reason=memory.end_reason,
        verified=memory.verified,
        disclosure_given=memory.disclosure_given,
        verification_attempts=memory.verification_attempts,
        cease_contact=memory.cease_contact,
        escalation_reason=tool.escalation_reason,
        plan_record=tool.plan_record,
        accept_plan=tool.accept_plan,
        latency_ms=int((perf_counter() - started) * 1000),
        script=tool.script,
        authorized_amounts=set(tool.authorized),
    )
