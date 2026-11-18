"""make messages_text_nullable

Revision ID: c3a954a6debe
Revises: 78b53e91a93d
Create Date: 2026-11-16 08:36:04.245599

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone


# revision identifiers, used by Alembic.
revision: str = 'c3a954a6debe'
down_revision: Union[str, Sequence[str], None] = '78b53e91a93d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite doesn't support ALTER COLUMN, so we recreate the table
    op.execute("ALTER TABLE messages RENAME TO messages_old")
    op.create_table(
        'messages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=True),
        sa.Column('direction', sa.String(20), nullable=False),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('callback_data', sa.Text(), nullable=True),
        sa.Column('sent', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), default=lambda: datetime.now(timezone.utc)),
    )
    op.execute("""
        INSERT INTO messages (id, user_id, admin_id, direction, text, callback_data, sent, created_at)
        SELECT id, user_id, admin_id, direction, text, callback_data, sent, created_at
        FROM messages_old
    """)
    op.drop_table('messages_old')


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE messages RENAME TO messages_old")
    op.create_table(
        'messages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=True),
        sa.Column('direction', sa.String(20), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('callback_data', sa.Text(), nullable=True),
        sa.Column('sent', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), default=lambda: datetime.now(timezone.utc)),
    )
    op.execute("""
        INSERT INTO messages (id, user_id, admin_id, direction, text, callback_data, sent, created_at)
        SELECT id, user_id, admin_id, direction, text, callback_data, sent, created_at
        FROM messages_old
    """)
    op.drop_table('messages_old')
