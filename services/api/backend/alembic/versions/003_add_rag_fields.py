"""003_add_rag_fields

Revision ID: 003_add_rag_fields
Revises: 002_add_batches
Create Date: 2026-11-25 15:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from backend.app.models.base import JSONType

# revision identifiers, used by Alembic.
revision: str = '003_add_rag_fields'
down_revision: Union[str, None] = '002_add_batches'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('audit_runs') as batch_op:
        batch_op.add_column(sa.Column('contexts', JSONType, nullable=True))
        batch_op.add_column(sa.Column('claims', JSONType, nullable=True))
        batch_op.add_column(sa.Column('faithfulness', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('ground_truth', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('rag_metrics', JSONType, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('audit_runs') as batch_op:
        batch_op.drop_column('rag_metrics')
        batch_op.drop_column('ground_truth')
        batch_op.drop_column('faithfulness')
        batch_op.drop_column('claims')
        batch_op.drop_column('contexts')
