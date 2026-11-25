"""001_initial_schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-11-11 14:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from backend.app.models.base import GUID, JSONType

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create projects table
    op.create_table(
        'projects',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_projects_slug', 'projects', ['slug'], unique=True)

    # 2. Create audit_runs table
    op.create_table(
        'audit_runs',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('project_id', GUID(), nullable=False),
        sa.Column('context', sa.Text(), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('response', sa.Text(), nullable=False),
        sa.Column('label', sa.String(length=20), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='PROCESSING'),
        sa.Column('breakdown', JSONType, nullable=True),
        sa.Column('model_version', sa.String(length=50), nullable=False, server_default='vihallu-v2-hybrid'),
        sa.Column('error_code', sa.String(length=50), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('latency_ms', sa.Float(), nullable=True),
        sa.Column('trace_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_runs_project_id', 'audit_runs', ['project_id'], unique=False)
    op.create_index('ix_audit_runs_project_created', 'audit_runs', ['project_id', 'created_at'], unique=False)
    op.create_index('ix_audit_runs_label', 'audit_runs', ['label'], unique=False)
    op.create_index('ix_audit_runs_status', 'audit_runs', ['status'], unique=False)

    # 3. Create audit_feedback table
    op.create_table(
        'audit_feedback',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('audit_run_id', GUID(), nullable=False),
        sa.Column('feedback_label', sa.String(length=30), nullable=False),
        sa.Column('corrected_label', sa.String(length=20), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['audit_run_id'], ['audit_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('audit_run_id')
    )
    op.create_index('ix_audit_feedback_audit_run_id', 'audit_feedback', ['audit_run_id'], unique=True)

    # 4. Create api_keys table
    op.create_table(
        'api_keys',
        sa.Column('id', GUID(), nullable=False),
        sa.Column('project_id', GUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('key_prefix', sa.String(length=16), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_api_keys_project_id', 'api_keys', ['project_id'], unique=False)
    op.create_index('ix_api_keys_key_hash', 'api_keys', ['key_hash'], unique=True)


def downgrade() -> None:
    op.drop_table('api_keys')
    op.drop_table('audit_feedback')
    op.drop_table('audit_runs')
    op.drop_table('projects')
