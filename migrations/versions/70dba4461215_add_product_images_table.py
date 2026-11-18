"""add_product_images_table

Revision ID: 70dba4461215
Revises: 
Create Date: 2026-11-11 09:11:07.512166

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '70dba4461215'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'product_images',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('image_url', sa.String(500), nullable=False),
        sa.Column('order', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    
    # Миграция существующих image_url из products в product_images
    conn = op.get_bind()
    products = conn.execute(sa.text("SELECT id, image_url FROM products WHERE image_url IS NOT NULL AND image_url != ''")).fetchall()
    for product in products:
        conn.execute(
            sa.text("INSERT INTO product_images (product_id, image_url, `order`) VALUES (:product_id, :image_url, 0)"),
            {"product_id": product[0], "image_url": product[1]}
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('product_images')
