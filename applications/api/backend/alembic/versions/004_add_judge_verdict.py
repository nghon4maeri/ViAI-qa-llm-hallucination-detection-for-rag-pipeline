"""004_add_judge_verdict

Revision ID: 004_add_judge_verdict
Revises: 003_add_rag_fields
Create Date: 2026-11-25 17:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from backend.app.models.base import JSONType

# revision identifiers, used by Alembic.
revision: str = '004_add_judge_verdict'
down_revision: Union[str, None] = '003_add_rag_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('audit_runs') as batch_op:
        batch_op.add_column(sa.Column('judge', JSONType, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('audit_runs') as batch_op:
        batch_op.drop_column('judge')
