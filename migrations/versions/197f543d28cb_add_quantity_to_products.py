"""add quantity to products

Revision ID: 197f543d28cb
Revises: fd7f4f254dcd
Create Date: 2026-11-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '197f543d28cb'
down_revision = 'fd7f4f254dcd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('products', sa.Column('quantity', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('products', 'quantity')
