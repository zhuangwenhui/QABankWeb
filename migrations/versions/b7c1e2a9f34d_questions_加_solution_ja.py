"""questions 加 solution_ja(日本語·詳解轨,可空)

Revision ID: b7c1e2a9f34d
Revises: fe4c7bb13a6c
Create Date: 2026-07-11 17:00:00.000000

additive/nullable:旧行 solution_ja 保持 NULL,零破坏。SQLite 改表需 batch 模式。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c1e2a9f34d'
down_revision = 'fe4c7bb13a6c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('solution_ja', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.drop_column('solution_ja')
