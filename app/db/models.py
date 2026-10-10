"""Tables for accounts, calls, traces, plans, and eval runs.

Money is Numeric so balances stay exact. The model never writes these rows
directly; tools and the release gate do.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.policy import CREDITOR_NAME, ConversationState


class InstructionVersion(Base):
    """One reviewed copy of the agent instructions, treated like code."""

    __tablename__ = "instruction_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    version_name: Mapped[str] = mapped_column(String(64), unique=True)
    body: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Account(Base):
    """A fictional Northwind Credit account. Seed data only; no real people."""

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_accounts_balance_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    date_of_birth: Mapped[date] = mapped_column(Date)
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    creditor_name: Mapped[str] = mapped_column(String(200), default=CREDITOR_NAME)
    cease_contact: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="account")
    payment_plans: Mapped[list["PaymentPlan"]] = relationship(back_populates="account")
    escalations: Mapped[list["Escalation"]] = relationship(back_populates="account")


class Conversation(Base):
    """One call. `state` is owned by the Python state machine."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    state: Mapped[str] = mapped_column(
        String(32), default=ConversationState.GREETING, server_default="GREETING"
    )
    instruction_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("instruction_versions.id")
    )
    verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    disclosure_given: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    verification_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    end_reason: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    account: Mapped[Account] = relationship(back_populates="conversations")
    turns: Mapped[list["Turn"]] = relationship(back_populates="conversation")
    traces: Mapped[list["Trace"]] = relationship(back_populates="conversation")


class Turn(Base):
    """Caller and agent messages, in order."""

    __tablename__ = "turns"
    __table_args__ = (
        UniqueConstraint("conversation_id", "turn_number", "role", name="uq_turns_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    turn_number: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="turns")


class Trace(Base):
    """Everything that happened on one agent turn. This is the audit record."""

    __tablename__ = "traces"
    __table_args__ = (
        UniqueConstraint("conversation_id", "turn_number", name="uq_traces_turn"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    turn_number: Mapped[int] = mapped_column(Integer)
    caller_text: Mapped[str] = mapped_column(Text)
    classified_intent: Mapped[str | None] = mapped_column(String(32))
    extracted_fields: Mapped[dict | None] = mapped_column(JSONB)
    state_before: Mapped[str] = mapped_column(String(32))
    state_after: Mapped[str] = mapped_column(String(32))
    instruction_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("instruction_versions.id")
    )
    prompt_text: Mapped[str | None] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(String(64))
    tool_input: Mapped[dict | None] = mapped_column(JSONB)
    tool_output: Mapped[dict | None] = mapped_column(JSONB)
    guardrail_pass: Mapped[bool | None] = mapped_column(Boolean)
    guardrail_rule: Mapped[str | None] = mapped_column(String(64))
    final_reply: Mapped[str] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="traces")


class PaymentPlan(Base):
    """A plan produced by offer_plan(). `total_amount` must equal the balance."""

    __tablename__ = "payment_plans"
    __table_args__ = (
        CheckConstraint(
            "months >= 1 AND months <= 6", name="ck_payment_plans_months"
        ),
        CheckConstraint("monthly_amount > 0", name="ck_payment_plans_monthly_positive"),
        CheckConstraint("total_amount > 0", name="ck_payment_plans_total_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"))
    monthly_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    months: Mapped[int] = mapped_column(Integer)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    schedule: Mapped[list] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="offered", server_default="offered")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    account: Mapped[Account] = relationship(back_populates="payment_plans")


class Escalation(Base):
    """A handoff to a human, or a recorded cease-contact / wrong-party event."""

    __tablename__ = "escalations"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"))
    reason_code: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    account: Mapped[Account] = relationship(back_populates="escalations")


class EvalRun(Base):
    """One release-gate result. `passed` is false when any replay eval fails."""

    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    passed: Mapped[bool] = mapped_column(Boolean)
    summary: Mapped[dict] = mapped_column(JSONB)
    git_sha: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
