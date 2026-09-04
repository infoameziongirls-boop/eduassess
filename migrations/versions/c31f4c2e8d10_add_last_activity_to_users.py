"""add_last_activity_to_users

Revision ID: c31f4c2e8d10
Revises: 7a3f5e0c9b21
Create Date: 2026-09-04 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c31f4c2e8d10'
down_revision = '7a3f5e0c9b21'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'last_activity' not in {
        column['name'] for column in inspector.get_columns('users')
    }:
        op.add_column('users', sa.Column('last_activity', sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'last_activity' in {
        column['name'] for column in inspector.get_columns('users')
    }:
        op.drop_column('users', 'last_activity')
