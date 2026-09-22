"""add ui_action_docs（非原生动作项目级用法文档）

Revision ID: cc33dd44ee55
Revises: bb22cc33dd44
Create Date: 2026-09-11
"""
from alembic import op
import sqlalchemy as sa

revision = "cc33dd44ee55"
down_revision = "bb22cc33dd44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ui_action_docs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False, index=True),
        sa.Column("action_key", sa.String(80), nullable=False, comment="动作标识：预设动作名 / custom:{custom_action_id}"),
        sa.Column("usage_text", sa.Text(), nullable=False, comment="项目级用法文本（多行）"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.UniqueConstraint("project_id", "action_key", name="uq_ui_action_doc_key"),
    )


def downgrade() -> None:
    op.drop_table("ui_action_docs")
