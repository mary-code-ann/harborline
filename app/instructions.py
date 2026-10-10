"""Load the versioned instruction file. The file is reviewed like code."""

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import InstructionVersion

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "prompts"


def instruction_path(version: str | None = None) -> Path:
    name = version or get_settings().instruction_version
    return PROMPTS / f"{name}.md"


def load_instruction(version: str | None = None) -> str:
    path = instruction_path(version)
    if not path.is_file():
        raise FileNotFoundError(f"No instruction file at {path}")
    return path.read_text(encoding="utf-8")


def content_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


async def ensure_instruction(session: AsyncSession, version: str | None = None) -> InstructionVersion:
    """Insert the current file, or update that version's row when the file changed."""
    name = version or get_settings().instruction_version
    body = load_instruction(name)
    digest = content_hash(body)
    row = await session.scalar(
        select(InstructionVersion).where(InstructionVersion.version_name == name)
    )
    if row is None:
        row = InstructionVersion(version_name=name, body=body, content_sha256=digest)
        session.add(row)
        await session.flush()
        return row
    if row.content_sha256 != digest or row.body != body:
        row.body = body
        row.content_sha256 = digest
        await session.flush()
    return row
