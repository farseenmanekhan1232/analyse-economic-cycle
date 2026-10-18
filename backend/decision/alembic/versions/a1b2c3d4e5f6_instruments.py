"""Add instruments table and holdings.instrument_id

Revision ID: a1b2c3d4e5f6
Revises: ff8f551c959f
Create Date: 2026-07-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "ff8f551c959f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("asset_class", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("sector", sa.String(length=64), nullable=False),
        sa.Column("isin", sa.String(length=16), nullable=True),
        sa.Column("amfi_code", sa.String(length=32), nullable=True),
        sa.Column("nse_symbol", sa.String(length=32), nullable=True),
        sa.Column("kite_tradingsymbol", sa.String(length=64), nullable=True),
        sa.Column("needs_id_review", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("holdings") as batch:
        batch.add_column(sa.Column("instrument_id", sa.String(length=32), nullable=True))
        batch.create_foreign_key(
            "fk_holdings_instrument_id", "instruments", ["instrument_id"], ["id"]
        )
        batch.create_index("ix_holdings_instrument_id", ["instrument_id"])


def downgrade() -> None:
    with op.batch_alter_table("holdings") as batch:
        batch.drop_constraint("fk_holdings_instrument_id", type_="foreignkey")
        batch.drop_index("ix_holdings_instrument_id")
        batch.drop_column("instrument_id")
    op.drop_table("instruments")
