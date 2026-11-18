"""add_custom_bouquet_fields

Revision ID: fe50921fc161
Revises: ebb9d565fd20
Create Date: 2026-11-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'fe50921fc161'
down_revision: Union[str, Sequence[str], None] = 'ebb9d565fd20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('is_custom', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('orders', sa.Column('custom_description', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'custom_description')
    op.drop_column('orders', 'is_custom')
