"""remove_button_columns_from_posts

Revision ID: 200b8733082e
Revises: a1b2c3d4e5f6
Create Date: 2026-11-17 15:10:19.457054

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '200b8733082e'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove button_text and button_url columns from posts table."""
    op.drop_column('posts', 'button_url')
    op.drop_column('posts', 'button_text')


def downgrade() -> None:
    """Re-add button_text and button_url columns to posts table."""
    op.add_column('posts', sa.Column('button_url', sa.String(500), nullable=True))
    op.add_column('posts', sa.Column('button_text', sa.String(100), nullable=False, server_default='Подробнее'))
