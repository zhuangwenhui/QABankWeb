"""内容发现:Question hints + solution_structured 列

Revision ID: 8ee0ed2463da
Revises: 3c36511153bc
Create Date: 2026-07-23 19:30:17.207953

additive/nullable:渐进提示(JSON 数组)与采点结构化题解(JSON 对象)两列,
旧行保持 NULL,to_dict 分别降级为 [] / {},零破坏。SQLite 改表走 batch 模式。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8ee0ed2463da'
down_revision = '3c36511153bc'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('hints', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('solution_structured', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.drop_column('solution_structured')
        batch_op.drop_column('hints')
