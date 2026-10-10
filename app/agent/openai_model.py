"""OpenAI structured-output classifier and a phraser that may only use the code script."""

from openai import AsyncOpenAI

from app.agent.classify import build_classifier_prompt
from app.agent.types import Classification
from app.config import Settings


async def classify_with_openai(
    caller_text: str, instruction: str, settings: Settings
) -> tuple[Classification, str]:
    prompt = build_classifier_prompt(instruction, caller_text)
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    completion = await client.chat.completions.parse(
        model=settings.openai_model,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "Return only the structured classification. "
                    "Do not calculate money. Leave requested_amount null when the caller "
                    "did not state one."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        response_format=Classification,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError("classifier returned no structured result")
    if parsed.intent not in (
        "verify",
        "balance",
        "pay",
        "plan_request",
        "dispute",
        "stop_contact",
        "wrong_person",
        "other",
    ):
        parsed.intent = "other"
    return parsed, prompt


async def phrase_with_openai(script: str, settings: Settings) -> tuple[str, str]:
    """Ask the model to phrase `script`. The prompt contains no extra dollar amounts."""
    prompt = (
        "Phrase the following lines as one short, calm reply. "
        "Do not add a sentence. Do not add a dollar amount that is not already in the lines.\n\n"
        f"{script}"
    )
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    completion = await client.chat.completions.create(
        model=settings.openai_model,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "You phrase a reply that was already decided. You do not decide policy.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    text = completion.choices[0].message.content or script
    return text.strip(), prompt
