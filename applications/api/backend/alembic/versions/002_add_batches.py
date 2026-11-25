"""002_add_batches

Revision ID: 002_add_batches
Revises: 001_initial_schema
Create Date: 2026-11-11 15:10:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from backend.app.models.base import GUID

# revision identifiers, used by Alembic.
revision: str = '002_add_batches'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create audit_batches table
    op.create_table(
        'audit_batches',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('project_id', GUID(), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('total_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('completed_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('hallucination_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='PROCESSING'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_batches_project_id', 'audit_batches', ['project_id'], unique=False)

    # 2. Add batch_id to audit_runs table
    with op.batch_alter_table('audit_runs') as batch_op:
        batch_op.add_column(sa.Column('batch_id', GUID(), nullable=True))
        batch_op.create_foreign_key(
            'fk_audit_runs_batch_id',
            'audit_batches',
            ['batch_id'],
            ['id'],
            ondelete='SET NULL'
        )
        batch_op.create_index('ix_audit_runs_batch_id', ['batch_id'])


def downgrade() -> None:
    with op.batch_alter_table('audit_runs') as batch_op:
        batch_op.drop_index('ix_audit_runs_batch_id')
        batch_op.drop_constraint('fk_audit_runs_batch_id', type_='foreignkey')
        batch_op.drop_column('batch_id')

    op.drop_index('ix_audit_batches_project_id', table_name='audit_batches')
    op.drop_table('audit_batches')
