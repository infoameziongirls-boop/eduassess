"""add offline submission receipts

Revision ID: 5c8d11f23a40
Revises: e53f7a8b2c19
Create Date: 2026-11-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '5c8d11f23a40'
down_revision = 'e53f7a8b2c19'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table('offline_submissions'):
        op.create_table(
            'offline_submissions',
            sa.Column('submission_id', sa.String(length=80), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('kind', sa.String(length=20), nullable=False),
            sa.Column('payload_hash', sa.String(length=64), nullable=False),
            sa.Column('result_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('submission_id'),
        )
    op.create_index(
        'ix_offline_submissions_user_id',
        'offline_submissions',
        ['user_id'],
        if_not_exists=True,
    )
    op.create_index(
        'ix_offline_submissions_kind',
        'offline_submissions',
        ['kind'],
        if_not_exists=True,
    )


def downgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table('offline_submissions'):
        op.drop_index(
            'ix_offline_submissions_kind',
            table_name='offline_submissions',
            if_exists=True,
        )
        op.drop_index(
            'ix_offline_submissions_user_id',
            table_name='offline_submissions',
            if_exists=True,
        )
        op.drop_table('offline_submissions')
