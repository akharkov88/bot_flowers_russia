"""alter_telegram_id_to_bigint

Revision ID: 1eda882a0364
Revises: f81aeec06798
Create Date: 2026-11-21 14:00:09.019033

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1eda882a0364'
down_revision: Union[str, Sequence[str], None] = 'f81aeec06798'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Alter carts.telegram_id from INTEGER to BIGINT
    op.alter_column('carts', 'telegram_id',
                    existing_type=sa.Integer(),
                    type_=sa.BigInteger(),
                    existing_nullable=False)
    # Alter post_recipients.telegram_id from INTEGER to BIGINT
    op.alter_column('post_recipients', 'telegram_id',
                    existing_type=sa.Integer(),
                    type_=sa.BigInteger(),
                    existing_nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('post_recipients', 'telegram_id',
                    existing_type=sa.BigInteger(),
                    type_=sa.Integer(),
                    existing_nullable=False)
    op.alter_column('carts', 'telegram_id',
                    existing_type=sa.BigInteger(),
                    type_=sa.Integer(),
                    existing_nullable=False)
