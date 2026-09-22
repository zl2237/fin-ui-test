"""widen custom_actions.description 200→500（用法说明升级多行文本）

Revision ID: dd44ee55ff66
Revises: cc33dd44ee55
Create Date: 2026-09-11
"""
from alembic import op
import sqlalchemy as sa

revision = "dd44ee55ff66"
down_revision = "cc33dd44ee55"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "custom_actions", "description",
        existing_type=sa.String(200), type_=sa.String(500),
        existing_nullable=True,
        comment="用法说明（多行，帮助中心与编排下拉展示）",
    )


def downgrade() -> None:
    op.alter_column(
        "custom_actions", "description",
        existing_type=sa.String(500), type_=sa.String(200),
        existing_nullable=True,
        comment="用途说明（帮助编排选择）",
    )
