"""Save calls, traces, plans, and escalations. The agent itself stays free of SQL."""

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.classify import classify_heuristic
from app.agent.openai_model import classify_with_openai, phrase_with_openai
from app.agent.turn import apply_phrased_reply, begin_call, take_turn
from app.agent.types import AccountFacts, ConversationMemory, TurnResult
from app.config import get_settings
from app.db.models import Account, Conversation, Escalation, PaymentPlan, Trace, Turn
from app.instructions import ensure_instruction, load_instruction
from app.policy import ConversationState

logger = logging.getLogger("harborline")


class AccountNotFound(Exception):
    pass


class DatabaseUnavailable(Exception):
    pass


def facts_from(account: Account) -> AccountFacts:
    return AccountFacts(
        external_ref=account.external_ref,
        full_name=account.full_name,
        date_of_birth=account.date_of_birth,
        balance=account.balance,
        creditor_name=account.creditor_name,
        cease_contact=account.cease_contact,
    )


async def open_conversation(session: AsyncSession, account_ref: str) -> dict:
    account = await _account(session, account_ref)
    instruction_row = await _instruction(session)
    body = instruction_row.body
    conversation = Conversation(
        account_id=account.id,
        state=ConversationState.GREETING,
        instruction_version_id=instruction_row.id,
    )
    session.add(conversation)
    await session.flush()
    memory = ConversationMemory(cease_contact=account.cease_contact)
    result = begin_call(memory, facts_from(account), body)
    _apply(conversation, account, memory)
    await _save_trace(session, conversation, turn_number=1, caller_text="", result=result)
    await session.commit()
    return _payload(conversation.id, result)


async def post_message(session: AsyncSession, conversation_id: int, caller_text: str) -> dict:
    try:
        conversation = await session.get(Conversation, conversation_id)
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        raise DatabaseUnavailable() from exc
    if conversation is None:
        raise AccountNotFound()
    account = await session.get(Account, conversation.account_id)
    if account is None:
        raise AccountNotFound()
    body = await _body(session, conversation)
    memory = await _memory(session, conversation, account)
    verified_before = memory.verified
    disclosure_before = memory.disclosure_given
    classification, prompt, classifier_name = await _classify(caller_text, body)
    result = take_turn(
        memory,
        facts_from(account),
        caller_text,
        body,
        classification=classification,
    )
    result.prompt_text = f"classifier: {classifier_name}\n{prompt}"
    if classifier_name == "openai" and result.action != "disclose" and result.guardrail_pass:
        result = await _phrase(result, facts_from(account), verified_before, disclosure_before)
    _apply(conversation, account, memory)
    await _save_side_effects(session, conversation, account, result)
    turn_number = await _next_turn(session, conversation.id)
    await _save_trace(
        session,
        conversation,
        turn_number=turn_number,
        caller_text=caller_text,
        result=result,
    )
    await session.commit()
    return _payload(conversation.id, result)


async def read_trace(session: AsyncSession, conversation_id: int) -> dict:
    try:
        conversation = await session.get(Conversation, conversation_id)
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        raise DatabaseUnavailable() from exc
    if conversation is None:
        raise AccountNotFound()
    account = await session.get(Account, conversation.account_id)
    rows = (
        await session.scalars(
            select(Trace)
            .where(Trace.conversation_id == conversation_id)
            .order_by(Trace.turn_number)
        )
    ).all()
    transcript = format_transcript(rows)
    return {
        "conversation_id": conversation.id,
        "account_ref": account.external_ref if account else None,
        "state": conversation.state,
        "end_reason": conversation.end_reason,
        "verified": conversation.verified,
        "disclosure_given": conversation.disclosure_given,
        "instruction_version_id": conversation.instruction_version_id,
        "transcript": transcript,
        "turns": [_trace_dict(row) for row in rows],
    }


def format_transcript(rows: list[Trace]) -> str:
    blocks: list[str] = []
    for row in rows:
        guard = "pass" if row.guardrail_pass else f"fail {row.guardrail_rule or ''}".strip()
        blocks.append(
            "\n".join(
                [
                    (
                        f"Turn {row.turn_number} | {row.state_before} -> {row.state_after} | "
                        f"intent={row.classified_intent or '-'} | tool={row.tool_name or '-'} | "
                        f"guardrail={guard} | {row.latency_ms if row.latency_ms is not None else '-'} ms"
                    ),
                    f"Caller: {row.caller_text}",
                    f"Agent: {row.final_reply}",
                ]
            )
        )
    return "\n\n".join(blocks)


async def _account(session: AsyncSession, account_ref: str) -> Account:
    try:
        account = await session.scalar(select(Account).where(Account.external_ref == account_ref))
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        raise DatabaseUnavailable() from exc
    if account is None:
        raise AccountNotFound()
    return account


async def _instruction(session: AsyncSession):
    try:
        return await ensure_instruction(session)
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        raise DatabaseUnavailable() from exc


async def _body(session: AsyncSession, conversation: Conversation) -> str:
    if conversation.instruction_version_id is None:
        return load_instruction()
    from app.db.models import InstructionVersion

    row = await session.get(InstructionVersion, conversation.instruction_version_id)
    if row is None:
        return load_instruction()
    return row.body


async def _memory(
    session: AsyncSession, conversation: Conversation, account: Account
) -> ConversationMemory:
    pending = await session.scalar(
        select(PaymentPlan)
        .where(
            PaymentPlan.conversation_id == conversation.id,
            PaymentPlan.status == "offered",
        )
        .order_by(PaymentPlan.id.desc())
    )
    offer = None
    if pending is not None:
        offer = {
            "monthly_amount": f"{pending.monthly_amount:.2f}",
            "months": pending.months,
            "total_amount": f"{pending.total_amount:.2f}",
            "schedule": pending.schedule,
            "reasons": [],
            "waiver_refused": False,
            "description": "",
        }
    return ConversationMemory(
        state=conversation.state,
        verified=conversation.verified,
        disclosure_given=conversation.disclosure_given,
        verification_attempts=conversation.verification_attempts,
        end_reason=conversation.end_reason,
        pending_offer=offer,
        cease_contact=account.cease_contact,
    )


async def _classify(caller_text: str, instruction: str):
    settings = get_settings()
    if not settings.openai_api_key:
        return classify_heuristic(caller_text), _prompt(instruction, caller_text), "heuristic"
    try:
        classification, prompt = await classify_with_openai(caller_text, instruction, settings)
        return classification, prompt, "openai"
    except Exception:
        logger.exception("classifier failed; using the deterministic parser")
        return classify_heuristic(caller_text), _prompt(instruction, caller_text), "heuristic"


def _prompt(instruction: str, caller_text: str) -> str:
    from app.agent.classify import build_classifier_prompt

    return build_classifier_prompt(instruction, caller_text)


async def _phrase(result: TurnResult, account: AccountFacts, verified_before: bool, disclosure_before: bool):
    settings = get_settings()
    try:
        phrased, phrase_prompt = await phrase_with_openai(result.script, settings)
    except Exception:
        logger.exception("reply phrasing failed; keeping the code reply")
        return result
    return apply_phrased_reply(
        result,
        phrased,
        phrase_prompt,
        account,
        verified_before=verified_before,
        disclosure_before=disclosure_before,
    )


def _apply(conversation: Conversation, account: Account, memory: ConversationMemory) -> None:
    conversation.state = memory.state
    conversation.verified = memory.verified
    conversation.disclosure_given = memory.disclosure_given
    conversation.verification_attempts = memory.verification_attempts
    conversation.end_reason = memory.end_reason
    conversation.updated_at = datetime.now(timezone.utc)
    if memory.cease_contact:
        account.cease_contact = True


async def _save_side_effects(
    session: AsyncSession, conversation: Conversation, account: Account, result: TurnResult
) -> None:
    if result.escalation_reason:
        session.add(
            Escalation(
                account_id=account.id,
                conversation_id=conversation.id,
                reason_code=result.escalation_reason,
                note=result.intent,
            )
        )
    if result.accept_plan and result.plan_record:
        await _accept_plan(session, conversation, account, result.plan_record)
    elif result.plan_record:
        _insert_plan(session, conversation, account, result.plan_record, status="offered")


def _insert_plan(session, conversation, account, record: dict, status: str) -> None:
    if not _plan_matches_balance(record, account.balance):
        logger.error("refusing to store a plan that does not equal the balance")
        return
    session.add(
        PaymentPlan(
            account_id=account.id,
            conversation_id=conversation.id,
            monthly_amount=record["monthly_amount"],
            months=int(record["months"]),
            total_amount=record["total_amount"],
            schedule=record["schedule"],
            status=status,
        )
    )


async def _accept_plan(session, conversation, account, record: dict) -> None:
    if not _plan_matches_balance(record, account.balance):
        logger.error("refusing to accept a plan that does not equal the balance")
        return
    current = await session.scalar(
        select(PaymentPlan)
        .where(
            PaymentPlan.conversation_id == conversation.id,
            PaymentPlan.status == "offered",
        )
        .order_by(PaymentPlan.id.desc())
    )
    if current is None:
        _insert_plan(session, conversation, account, record, status="accepted")
        return
    current.status = "accepted"


def _plan_matches_balance(record: dict, balance) -> bool:
    from decimal import Decimal

    from app.tools.payments import money

    try:
        total = money(str(record["total_amount"]))
        months = int(record["months"])
        monthly = money(str(record["monthly_amount"]))
    except (KeyError, TypeError, ValueError):
        return False
    return total == money(balance) and monthly > 0 and 1 <= months <= 6 and total > Decimal("0")


async def _next_turn(session: AsyncSession, conversation_id: int) -> int:
    current = await session.scalar(
        select(func.max(Trace.turn_number)).where(Trace.conversation_id == conversation_id)
    )
    return int(current or 0) + 1


async def _save_trace(
    session: AsyncSession,
    conversation: Conversation,
    *,
    turn_number: int,
    caller_text: str,
    result: TurnResult,
) -> None:
    if caller_text:
        session.add(
            Turn(
                conversation_id=conversation.id,
                turn_number=turn_number,
                role="caller",
                text=caller_text,
            )
        )
    session.add(
        Turn(
            conversation_id=conversation.id,
            turn_number=turn_number,
            role="agent",
            text=result.reply,
        )
    )
    session.add(
        Trace(
            conversation_id=conversation.id,
            turn_number=turn_number,
            caller_text=caller_text,
            classified_intent=result.intent,
            extracted_fields=result.extracted or None,
            state_before=result.state_before,
            state_after=result.state_after,
            instruction_version_id=conversation.instruction_version_id,
            prompt_text=result.prompt_text,
            tool_name=result.tool_name,
            tool_input=result.tool_input,
            tool_output=result.tool_output,
            guardrail_pass=result.guardrail_pass,
            guardrail_rule=result.guardrail_rule,
            final_reply=result.reply,
            latency_ms=result.latency_ms,
        )
    )


def _payload(conversation_id: int, result: TurnResult) -> dict:
    return {
        "role": "agent",
        "conversation_id": conversation_id,
        "text": result.reply,
        "state": result.state_after,
        "end_reason": result.end_reason,
    }


def _trace_dict(row: Trace) -> dict:
    return {
        "turn_number": row.turn_number,
        "caller_text": row.caller_text,
        "classified_intent": row.classified_intent,
        "extracted_fields": row.extracted_fields,
        "state_before": row.state_before,
        "state_after": row.state_after,
        "instruction_version_id": row.instruction_version_id,
        "prompt_text": row.prompt_text,
        "tool_name": row.tool_name,
        "tool_input": row.tool_input,
        "tool_output": row.tool_output,
        "guardrail": {"pass": row.guardrail_pass, "rule": row.guardrail_rule},
        "final_reply": row.final_reply,
        "latency_ms": row.latency_ms,
    }
