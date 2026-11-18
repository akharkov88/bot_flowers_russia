"""add order_date to orders

Revision ID: a1b2c3d4e5f6
Revises: bb3a7d59a4ca
Create Date: 2026-11-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'bb3a7d59a4ca'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('order_date', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'order_date')
