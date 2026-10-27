"""dataset_sheet_model

数据集行 Excel sheet 化：data_set_rows 加 label / field_desc / field_order 三列，
历史行 label 回填 Sheet{row_index}（与运行时读取回退一致，${Sheet1.字段} 引用稳定）。

Revision ID: c3f8a92d5e17
Revises: b1e5c2f7a310
Create Date: 2026-10-27 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3f8a92d5e17'
down_revision: Union[str, Sequence[str], None] = 'b1e5c2f7a310'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('data_set_rows', sa.Column('label', sa.String(length=100), nullable=True,
                   comment='sheet 名称（数据集内唯一，服务层校验；NULL=历史行，读取回退 Sheet{row_index}）'))
    op.add_column('data_set_rows', sa.Column('field_desc', sa.JSON(), nullable=True,
                   comment='{字段名: 描述}——编辑器备注列，运行时不参与解析'))
    op.add_column('data_set_rows', sa.Column('field_order', sa.JSON(), nullable=True,
                   comment='[字段名] 显式字段顺序（MySQL JSON 列不保 key 序，网格行序以此为准）'))
    # 历史行回填：与 dataset_service 读取回退（label or f"Sheet{row_index}"）完全一致
    op.execute("UPDATE data_set_rows SET label = CONCAT('Sheet', row_index) WHERE label IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('data_set_rows', 'field_order')
    op.drop_column('data_set_rows', 'field_desc')
    op.drop_column('data_set_rows', 'label')
