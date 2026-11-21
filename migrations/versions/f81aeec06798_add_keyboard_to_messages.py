"""add keyboard to messages

Revision ID: f81aeec06798
Revises: ff72fb6888a0
Create Date: 2026-11-20

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f81aeec06798'
down_revision = 'd0b15aef0e23'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('keyboard', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'keyboard')
