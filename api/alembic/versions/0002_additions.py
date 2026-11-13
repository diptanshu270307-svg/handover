"""additions: stale claims, clarifications, rehearsal timing & responsibility decisions

Revision ID: 0002_additions
Revises: 0001_initial_schema
Create Date: 2026-11-13 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_additions"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("claims", sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("claims", sa.Column("stale_reason", sa.Text(), nullable=True))
    op.add_column("claims", sa.Column("source_diff", sa.Text(), nullable=True))

    op.add_column("rehearsal_results", sa.Column("duration_seconds", sa.Integer(), nullable=True))
    op.add_column(
        "rehearsal_results",
        sa.Column(
            "responsibility_decisions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    op.create_table(
        "clarifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column(
            "claim_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("claims.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "conflict_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conflicts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("asked_to_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answered_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_clarifications_project_id", "clarifications", ["project_id"])


def downgrade() -> None:
    op.drop_table("clarifications")
    op.drop_column("rehearsal_results", "responsibility_decisions")
    op.drop_column("rehearsal_results", "duration_seconds")
    op.drop_column("claims", "source_diff")
    op.drop_column("claims", "stale_reason")
    op.drop_column("claims", "is_stale")
