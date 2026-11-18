"""add_image_url_to_notifications

Revision ID: f8196956e78e
Revises: 505aa53400cf
Create Date: 2026-11-17 16:39:18.310502

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8196956e78e'
down_revision: Union[str, Sequence[str], None] = '505aa53400cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('notifications', sa.Column('image_url', sa.String(500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('notifications', 'image_url')
