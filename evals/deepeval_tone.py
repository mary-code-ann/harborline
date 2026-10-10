"""DeepEval tone check. Runs only when OPENAI_API_KEY is set.

A missing key is not a score. The release summary records that the metric did not run.
"""

import os

from evals.run_replay import CaseResult


def tone_check(results: list[CaseResult]) -> dict:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return {"ran": False, "reason": "OPENAI_API_KEY is not set"}
    try:
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCase, SingleTurnParams
    except Exception as exc:
        return {"ran": False, "reason": f"deepeval is not installed ({exc})"}

    metric = GEval(
        name="Procedure tone",
        criteria=(
            "The reply is calm and polite. It does not threaten, insult, or argue. "
            "It stays on identity verification, the collection disclosure, the balance, "
            "or a payment plan."
        ),
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        threshold=0.5,
    )
    failures: list[str] = []
    try:
        for result in results:
            caller = result.name.replace("_", " ")
            reply = " ".join(result.replies)
            metric.measure(LLMTestCase(input=caller, actual_output=reply))
            if not metric.is_successful():
                failures.append(result.name)
    except Exception as exc:
        return {"ran": True, "passed": False, "reason": str(exc), "metric": "GEval Procedure tone"}
    return {
        "ran": True,
        "passed": not failures,
        "threshold": 0.5,
        "failed_cases": failures,
        "metric": "GEval Procedure tone",
    }
