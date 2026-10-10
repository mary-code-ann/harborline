"""The dollar amount that used to be copied out of the prompt.

Run: python -m evals.incident
"""

import re
from datetime import date

from app.agent.turn import begin_call, take_turn
from app.agent.types import AccountFacts, ConversationMemory
from app.guardrails.output import AMOUNT_NOT_FROM_TOOL, check_reply
from app.instructions import load_instruction
from app.policy import CREDITOR_NAME
from app.tools.payments import offer_plan
from evals.checks import unauthorized_amounts


def reply_copying_prompt_amount(prompt: str) -> str:
    """The bug: speak the first dollar amount written in the instructions."""
    match = re.search(r"\$\d+(?:\.\d{2})?", prompt)
    amount = match.group(0) if match else "$25"
    return f"We can set this up for {amount} a month."


def main() -> None:
    prompt = load_instruction("agent_v1")
    buggy = reply_copying_prompt_amount(prompt)
    legal = offer_plan("1000.00", requested_monthly="5", requested_months=24)
    stray = unauthorized_amounts(buggy, set(legal.spoken_amounts))
    blocked = check_reply(
        buggy,
        action="offer_plan",
        verified=True,
        disclosure_given=True,
        authorized_amounts=set(legal.spoken_amounts),
        account=None,
        fallback=legal.describe(),
    )

    print("BEFORE  reply copied a dollar amount out of prompts/agent_v1.md")
    print(f"        prompt amount spoken: {buggy}")
    print(f"        offer_plan schedule: {', '.join(f'${part:.2f}' for part in legal.schedule)}")
    print(f"        unauthorized amounts: {', '.join(f'${amount:.2f}' for amount in stray) or '(none)'}")
    print(f"        guardrail rule: {blocked.rule}")
    print(f"        result: {'FAIL' if stray or blocked.rule == AMOUNT_NOT_FROM_TOOL else 'PASS'}")
    print()

    account = AccountFacts(
        external_ref="NW-1001",
        full_name="Ava Ellison",
        date_of_birth=date(1986, 3, 14),
        balance=legal.balance,
        creditor_name=CREDITOR_NAME,
    )
    memory = ConversationMemory()
    text = load_instruction("agent_v2")
    begin_call(memory, account, text)
    take_turn(
        memory,
        account,
        "My name is Ava Ellison and my date of birth is March 14, 1986.",
        text,
    )
    fixed = take_turn(memory, account, "I can only pay $5 a month for 24 months.", text)
    fixed_stray = unauthorized_amounts(fixed.reply, set(fixed.authorized_amounts))
    print("AFTER   reply is offer_plan().describe(), instructions are prompts/agent_v2.md")
    print(f"        reply: {fixed.reply}")
    print(f"        guardrail: {'pass' if fixed.guardrail_pass else 'fail ' + str(fixed.guardrail_rule)}")
    print(f"        unauthorized amounts: {', '.join(f'${amount:.2f}' for amount in fixed_stray) or '(none)'}")
    print(f"        result: {'PASS' if fixed.guardrail_pass and not fixed_stray else 'FAIL'}")


if __name__ == "__main__":
    main()
