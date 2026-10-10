"""Initial Harborline tables.

Revision ID: 001_initial
Revises:
Create Date: 2026-10-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "instruction_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_name", sa.String(length=64), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("version_name"),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_ref", sa.String(length=32), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("balance", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "creditor_name",
            sa.String(length=200),
            server_default="Northwind Credit",
            nullable=False,
        ),
        sa.Column("cease_contact", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("balance >= 0", name="ck_accounts_balance_nonnegative"),
        sa.UniqueConstraint("external_ref"),
    )
    op.create_index("ix_accounts_external_ref", "accounts", ["external_ref"])
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="GREETING", nullable=False),
        sa.Column("instruction_version_id", sa.Integer(), nullable=True),
        sa.Column("verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("disclosure_given", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("verification_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("end_reason", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["instruction_version_id"], ["instruction_versions.id"]),
    )
    op.create_index("ix_conversations_account_id", "conversations", ["account_id"])
    op.create_table(
        "turns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("conversation_id", "turn_number", "role", name="uq_turns_role"),
    )
    op.create_index("ix_turns_conversation_id", "turns", ["conversation_id"])
    op.create_table(
        "traces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("caller_text", sa.Text(), nullable=False),
        sa.Column("classified_intent", sa.String(length=32), nullable=True),
        sa.Column("extracted_fields", postgresql.JSONB(), nullable=True),
        sa.Column("state_before", sa.String(length=32), nullable=False),
        sa.Column("state_after", sa.String(length=32), nullable=False),
        sa.Column("instruction_version_id", sa.Integer(), nullable=True),
        sa.Column("prompt_text", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.String(length=64), nullable=True),
        sa.Column("tool_input", postgresql.JSONB(), nullable=True),
        sa.Column("tool_output", postgresql.JSONB(), nullable=True),
        sa.Column("guardrail_pass", sa.Boolean(), nullable=True),
        sa.Column("guardrail_rule", sa.String(length=64), nullable=True),
        sa.Column("final_reply", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["instruction_version_id"], ["instruction_versions.id"]),
        sa.UniqueConstraint("conversation_id", "turn_number", name="uq_traces_turn"),
    )
    op.create_index("ix_traces_conversation_id", "traces", ["conversation_id"])
    op.create_table(
        "payment_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("monthly_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("months", sa.Integer(), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("schedule", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="offered", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("months >= 1 AND months <= 6", name="ck_payment_plans_months"),
        sa.CheckConstraint("monthly_amount > 0", name="ck_payment_plans_monthly_positive"),
        sa.CheckConstraint("total_amount > 0", name="ck_payment_plans_total_positive"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
    )
    op.create_index("ix_payment_plans_account_id", "payment_plans", ["account_id"])
    op.create_table(
        "escalations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("reason_code", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
    )
    op.create_index("ix_escalations_account_id", "escalations", ["account_id"])
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column("git_sha", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("eval_runs")
    op.drop_table("escalations")
    op.drop_table("payment_plans")
    op.drop_table("traces")
    op.drop_table("turns")
    op.drop_table("conversations")
    op.drop_table("accounts")
    op.drop_table("instruction_versions")
