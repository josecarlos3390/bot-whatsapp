"""tabla de embudo de venta

Revision ID: b3f7a1c9d204
Revises: 9c21d4e77a01
Create Date: 2026-10-23

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b3f7a1c9d204"
down_revision = "9c21d4e77a01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "funnel_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("step", sa.String(length=32), nullable=False),
        sa.Column("contact_id", sa.String(length=36), nullable=True),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("sku", sa.String(length=64), nullable=True),
        sa.Column("query", sa.String(length=160), nullable=True),
        sa.Column("value", sa.Numeric(14, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_funnel_events_step", "funnel_events", ["step"])
    op.create_index(
        "ix_funnel_events_contact_id", "funnel_events", ["contact_id"]
    )
    op.create_index(
        "ix_funnel_events_conversation_id",
        "funnel_events",
        ["conversation_id"],
    )
    op.create_index(
        "ix_funnel_events_created_at", "funnel_events", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_funnel_events_created_at", table_name="funnel_events")
    op.drop_index(
        "ix_funnel_events_conversation_id", table_name="funnel_events"
    )
    op.drop_index("ix_funnel_events_contact_id", table_name="funnel_events")
    op.drop_index("ix_funnel_events_step", table_name="funnel_events")
    op.drop_table("funnel_events")
