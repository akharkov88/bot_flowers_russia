"""add_user_blocked_bot_to_users

Revision ID: bb3a7d59a4ca
Revises: ff72fb6888a0
Create Date: 2026-11-17 12:17:39.919509

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bb3a7d59a4ca'
down_revision: Union[str, Sequence[str], None] = 'ff72fb6888a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('user_blocked_bot', sa.Boolean(), nullable=True, server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'user_blocked_bot')
