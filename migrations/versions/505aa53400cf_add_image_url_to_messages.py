"""add_image_url_to_messages

Revision ID: 505aa53400cf
Revises: 200b8733082e
Create Date: 2026-11-17 16:11:59.249631

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '505aa53400cf'
down_revision: Union[str, Sequence[str], None] = '200b8733082e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('messages', sa.Column('image_url', sa.String(500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('messages', 'image_url')
