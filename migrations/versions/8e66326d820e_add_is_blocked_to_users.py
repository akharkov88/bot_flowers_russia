"""add_is_blocked_to_users

Revision ID: 8e66326d820e
Revises: fe50921fc161
Create Date: 2026-11-16 17:22:02.473210

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e66326d820e'
down_revision: Union[str, Sequence[str], None] = 'fe50921fc161'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('is_blocked', sa.Boolean(), nullable=True, server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'is_blocked')
