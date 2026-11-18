"""merge quantity and messages_nullable

Revision ID: ebb9d565fd20
Revises: 197f543d28cb, c3a954a6debe
Create Date: 2026-11-16 08:51:40.796714

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ebb9d565fd20'
down_revision: Union[str, Sequence[str], None] = ('197f543d28cb', 'c3a954a6debe')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
