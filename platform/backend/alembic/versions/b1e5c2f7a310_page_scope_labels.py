"""page_scope_labels

Revision ID: b1e5c2f7a310
Revises: ad0900074d40
Create Date: 2026-10-23 18:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b1e5c2f7a310'
down_revision: Union[str, Sequence[str], None] = 'ad0900074d40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'page_scope_labels',
        sa.Column('id', sa.Integer(), nullable=False, comment='主键ID'),
        sa.Column('project_id', sa.Integer(), nullable=False, comment='所属项目ID'),
        sa.Column('page_scope', sa.String(length=200), nullable=False,
                  comment='页面域英文标识：如 ordermanage/business_order_add'),
        sa.Column('label', sa.String(length=100), nullable=False,
                  comment='中文语义：如 新建委托订单'),
        sa.Column('created_at', sa.DateTime(), nullable=True, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=True, comment='最近更新时间'),
        sa.Column('created_by', sa.Integer(), nullable=True, comment='创建人 user_id'),
        sa.Column('updated_by', sa.Integer(), nullable=True, comment='更新人 user_id'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'page_scope', name='uq_page_scope_label_scope'),
    )
    op.create_index('ix_page_scope_labels_id', 'page_scope_labels', ['id'])
    op.create_index('ix_page_scope_labels_project_id', 'page_scope_labels', ['project_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_page_scope_labels_project_id', table_name='page_scope_labels')
    op.drop_index('ix_page_scope_labels_id', table_name='page_scope_labels')
    op.drop_table('page_scope_labels')
