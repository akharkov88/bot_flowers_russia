"""add_callback_data_to_messages

Revision ID: 78b53e91a93d
Revises: fd7f4f254dcd
Create Date: 2026-11-13 16:11:58.777348

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '78b53e91a93d'
down_revision: Union[str, Sequence[str], None] = 'fd7f4f254dcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('messages', sa.Column('callback_data', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('messages', 'callback_data')
