"""Release gate. Exits non-zero when any replay fails, and stores the run when Postgres is up."""

import argparse
import asyncio
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.exc import SQLAlchemyError

from evals.deepeval_tone import tone_check
from evals.run_replay import run_all


def summary(results, tone: dict) -> dict:
    return {
        "conversations": [
            {"name": result.name, "passed": result.passed, "failures": result.failures}
            for result in results
        ],
        "passed": sum(1 for result in results if result.passed),
        "failed": sum(1 for result in results if not result.passed),
        "total": len(results),
        "deepeval": tone,
    }


def git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


async def save(passed: bool, payload: dict, started: datetime) -> str:
    from app.db.models import EvalRun
    from app.db.session import SessionLocal

    try:
        async with SessionLocal() as session:
            session.add(
                EvalRun(
                    started_at=started,
                    finished_at=datetime.now(timezone.utc),
                    passed=passed,
                    summary=payload,
                    git_sha=git_sha(),
                )
            )
            await session.commit()
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        return f"eval_runs not saved ({type(exc).__name__})"
    return "eval_runs saved"


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay evals. Non-zero if any fail.")
    parser.add_argument(
        "--require-db",
        action="store_true",
        help="Exit non-zero when the result cannot be written to eval_runs.",
    )
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    results = run_all()
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"{status}  {result.name}")
        for problem in result.failures:
            print(f"      {problem}")
    tone = tone_check(results)
    payload = summary(results, tone)
    passed = payload["failed"] == 0 and tone.get("passed", True)
    print(
        f"replay {payload['passed']} passed, {payload['failed']} failed, "
        f"{payload['total']} total"
    )
    print(f"deepeval {tone}")
    saved = asyncio.run(save(passed, payload, started))
    print(saved)
    if not passed:
        sys.exit(1)
    if args.require_db and saved != "eval_runs saved":
        sys.exit(1)


if __name__ == "__main__":
    main()
