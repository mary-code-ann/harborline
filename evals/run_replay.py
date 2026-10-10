"""Replay saved caller lines through the agent and check the procedure."""

import json
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from app.agent.turn import begin_call, take_turn
from app.agent.types import AccountFacts, ConversationMemory, TurnResult
from app.db.seed import SEED_ACCOUNTS
from app.instructions import load_instruction
from app.policy import CREDITOR_NAME, DISCLOSURE_TEXT
from app.tools.payments import money, offer_plan
from evals.checks import leaks_before_disclosure, unauthorized_amounts

CASES = Path(__file__).resolve().parent / "conversations"
INSTRUCTION = "agent_v2"


@dataclass
class CaseResult:
    name: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)
    end_reason: str | None = None
    final_state: str | None = None


def load_cases() -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(CASES.glob("*.json"))
    ]


def replay_case(case: dict, instruction: str | None = None) -> CaseResult:
    seed = next(row for row in SEED_ACCOUNTS if row.external_ref == case["account_ref"])
    account = AccountFacts(
        external_ref=seed.external_ref,
        full_name=seed.full_name,
        date_of_birth=seed.date_of_birth,
        balance=seed.balance,
        creditor_name=CREDITOR_NAME,
    )
    text = instruction if instruction is not None else load_instruction(INSTRUCTION)
    memory = ConversationMemory()
    turns = [begin_call(memory, account, text)]
    for line in case["callers"]:
        turns.append(take_turn(memory, account, line, text))
    return _judge(case, account, memory, turns)


def run_all(instruction: str | None = None) -> list[CaseResult]:
    return [replay_case(case, instruction) for case in load_cases()]


def fresh_offer(turn: TurnResult, balance: Decimal):
    payload = turn.tool_input or {}
    return offer_plan(
        balance,
        requested_monthly=payload.get("requested_monthly"),
        requested_months=payload.get("requested_months"),
        waive=bool(payload.get("waive")),
    )


def _judge(
    case: dict,
    account: AccountFacts,
    memory: ConversationMemory,
    turns: list[TurnResult],
) -> CaseResult:
    expect = case["expect"]
    failures: list[str] = []
    replies = [turn.reply for turn in turns]
    allowed: set[Decimal] = set()

    for turn in turns:
        if not turn.guardrail_pass:
            failures.append(f"guardrail {turn.guardrail_rule} on: {turn.reply}")
        if turn.tool_name == "offer_plan":
            fresh = fresh_offer(turn, account.balance)
            output = turn.tool_output or {}
            if output.get("schedule") != [f"{part:.2f}" for part in fresh.schedule]:
                failures.append("offer_plan trace does not match a fresh offer_plan() call")
            if output.get("total_amount") != f"{fresh.total_amount:.2f}":
                failures.append("plan total in the trace is not the balance")
            allowed |= {amount.quantize(Decimal("0.01")) for amount in fresh.spoken_amounts}
        if turn.tool_name == "get_account" and (turn.tool_output or {}).get("verified"):
            allowed.add(money(turn.tool_output["balance"]))
        if turn.tool_name == "record_payment_plan":
            recorded = turn.tool_input or {}
            if money(str(recorded.get("total_amount"))) != money(account.balance):
                failures.append("recorded plan does not collect the full balance")
            if not 1 <= int(recorded.get("months") or 0) <= 6:
                failures.append("recorded plan is outside 1 to 6 months")
        stray = unauthorized_amounts(turn.reply, allowed)
        if stray:
            rendered = ", ".join(f"${amount:.2f}" for amount in stray)
            failures.append(f"reply used {rendered} which the tools had not returned")

    disclosure_hits = [reply for reply in replies if reply == DISCLOSURE_TEXT]
    if expect.get("disclosure"):
        if disclosure_hits != [DISCLOSURE_TEXT]:
            failures.append("disclosure was not delivered as its own exact sentence")
    elif disclosure_hits or any("attempt to collect a debt" in reply for reply in replies):
        failures.append("disclosure appeared before verification succeeded")

    failures.extend(
        leaks_before_disclosure(
            replies,
            account.full_name,
            account.date_of_birth.isoformat(),
            account.balance,
        )
    )
    if memory.state != expect["final_state"]:
        failures.append(f"state is {memory.state}, expected {expect['final_state']}")
    if memory.end_reason != expect.get("end_reason"):
        failures.append(f"end reason is {memory.end_reason}, expected {expect.get('end_reason')}")
    if bool(memory.cease_contact) != bool(expect.get("cease_contact")):
        failures.append(f"cease_contact is {memory.cease_contact}")
    accepted = any(turn.accept_plan for turn in turns)
    if expect.get("plan_accepted") and not accepted:
        failures.append("payment plan was not recorded")
    if expect.get("plan_accepted") is False and accepted:
        failures.append("payment plan was recorded and should not have been")
    if expect.get("waiver_refused") and not any(
        (turn.tool_output or {}).get("waiver_refused") for turn in turns
    ):
        failures.append("waiver was not refused")

    return CaseResult(
        name=case["name"],
        passed=not failures,
        failures=failures,
        replies=replies,
        end_reason=memory.end_reason,
        final_state=memory.state,
    )


def main() -> None:
    results = run_all()
    failed = 0
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{status}  {result.name}")
        for problem in result.failures:
            print(f"      {problem}")
        if not result.passed:
            failed += 1
    print(f"{len(results) - failed} passed, {failed} failed, {len(results)} total")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
