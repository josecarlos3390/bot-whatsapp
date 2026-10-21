"""atributos ampliados del catalogo

Revision ID: 9c21d4e77a01
Revises: 7f3c1a9b2d10
Create Date: 2026-10-21

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "9c21d4e77a01"
down_revision = "7f3c1a9b2d10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "catalog_items",
        sa.Column("attributes", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("catalog_items", "attributes")
