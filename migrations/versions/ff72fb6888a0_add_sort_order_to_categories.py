"""add_sort_order_to_categories

Revision ID: ff72fb6888a0
Revises: fe50921fc161
Create Date: 2026-11-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ff72fb6888a0'
down_revision = '8e66326d820e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('categories', sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('categories', 'sort_order')
