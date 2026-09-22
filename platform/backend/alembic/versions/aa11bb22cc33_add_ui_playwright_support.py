"""add ui playwright support

UI 自动化集成（承接 autotest-playwright）：
- environments.browser_config      UI 执行浏览器配置（headless/viewport/超时/截图策略/token 注入）
- case_node_configs.step_type      节点类型 api/ui（server_default='api'，历史行自动归为 api）
- case_node_configs.ui_params      UI 节点参数（action/element/value/timeout_ms/...）
- step_records.step_kind           步骤类型 api/ui（历史行 NULL，读取侧视为 api）
- step_records.screenshot_file_id  UI 步骤截图的文件中心 test_files.id
- ui_elements 新表                 项目级页面元素定位器（承接 locator JSON，多策略字段）

Revision ID: aa11bb22cc33
Revises: e9f0a1b2c3d4
Create Date: 2026-09-10 10:00:00
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'aa11bb22cc33'
down_revision = 'e9f0a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('environments', sa.Column('browser_config', sa.JSON(), nullable=True,
                  comment='UI 执行浏览器配置：{headless, viewport:{width,height}, slow_mo_ms, timeout_ms, screenshot, inject_token_cookie, launch_args}'))
    op.add_column('case_node_configs', sa.Column('step_type', sa.String(length=20), nullable=False,
                  server_default='api', comment='节点类型：api 接口调用 / ui 浏览器操作'))
    op.add_column('case_node_configs', sa.Column('ui_params', sa.JSON(), nullable=True,
                  comment='UI 节点参数：{action, url, element, value, values, timeout_ms, wait_for, files}'))
    op.add_column('step_records', sa.Column('step_kind', sa.String(length=20), nullable=True,
                  comment='步骤类型：api 接口调用 / ui 浏览器操作（历史行 NULL 视为 api）'))
    op.add_column('step_records', sa.Column('screenshot_file_id', sa.Integer(), nullable=True,
                  comment='UI 步骤截图的文件中心 test_files.id，NULL 表示无截图'))
    op.create_table(
        'ui_elements',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id'), nullable=False, comment='所属项目ID'),
        sa.Column('page_scope', sa.String(length=200), nullable=False, comment='页面域：模块/页面标识，如 ordermanage/business_order_add'),
        sa.Column('element_key', sa.String(length=200), nullable=False, comment='元素键名：如 bl_no_input / save_draft_button'),
        sa.Column('strategies', sa.JSON(), nullable=True, comment='定位策略字典：{full_xpath, text, label, for, placeholder, button, checkbox, toast, css, xpath, ...}'),
        sa.Column('description', sa.String(length=200), nullable=True, comment='元素中文说明（日志/报告用）'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.UniqueConstraint('project_id', 'page_scope', 'element_key', name='uq_ui_element_scope_key'),
        comment='UI 元素库：项目级页面元素定位器',
    )
    op.create_index('ix_ui_elements_project_id', 'ui_elements', ['project_id'])
    op.create_index('ix_ui_elements_page_scope', 'ui_elements', ['page_scope'])


def downgrade() -> None:
    op.drop_index('ix_ui_elements_page_scope', table_name='ui_elements')
    op.drop_index('ix_ui_elements_project_id', table_name='ui_elements')
    op.drop_table('ui_elements')
    op.drop_column('step_records', 'screenshot_file_id')
    op.drop_column('step_records', 'step_kind')
    op.drop_column('case_node_configs', 'ui_params')
    op.drop_column('case_node_configs', 'step_type')
    op.drop_column('environments', 'browser_config')
