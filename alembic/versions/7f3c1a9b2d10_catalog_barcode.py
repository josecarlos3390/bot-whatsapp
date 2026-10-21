"""agrega codigo de barra al catalogo

Revision ID: 7f3c1a9b2d10
Revises: 50165ab3fbfd
Create Date: 2026-10-21

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "7f3c1a9b2d10"
down_revision = "50165ab3fbfd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "catalog_items",
        sa.Column("barcode", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_catalog_items_barcode", "catalog_items", ["barcode"]
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_items_barcode", table_name="catalog_items")
    op.drop_column("catalog_items", "barcode")
