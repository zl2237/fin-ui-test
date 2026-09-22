"""add custom ui actions

自定义 UI 动作：
- custom_actions 新表            项目级 JS 动作模板（编排时像预设动作一样选用）

Revision ID: bb22cc33dd44
Revises: aa11bb22cc33
Create Date: 2026-09-11 14:00:00
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bb22cc33dd44'
down_revision = 'aa11bb22cc33'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'custom_actions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False, comment='所属项目ID'),
        sa.Column('name', sa.String(length=100), nullable=False, comment='动作名（编排下拉显示）'),
        sa.Column('description', sa.String(length=200), nullable=True, comment='用途说明（帮助编排选择）'),
        sa.Column('script', sa.Text(), nullable=False,
                  comment='JS 函数体：入参 args（步骤 value），return 值进 facts.result'),
        sa.Column('created_at', sa.DateTime(), nullable=True, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=True, comment='最近更新'),
        sa.Column('created_by', sa.Integer(), nullable=True, comment='创建人 user_id'),
        sa.Column('updated_by', sa.Integer(), nullable=True, comment='更新人 user_id'),
        sa.UniqueConstraint('project_id', 'name', name='uq_custom_action_name'),
    )
    op.create_index('ix_custom_actions_id', 'custom_actions', ['id'])
    op.create_index('ix_custom_actions_project_id', 'custom_actions', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_custom_actions_project_id', table_name='custom_actions')
    op.drop_index('ix_custom_actions_id', table_name='custom_actions')
    op.drop_table('custom_actions')
