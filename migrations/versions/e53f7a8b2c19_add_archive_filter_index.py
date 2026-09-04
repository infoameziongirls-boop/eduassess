"""add archive filter index

Revision ID: e53f7a8b2c19
Revises: d42e6a7b9c11
Create Date: 2026-09-04 19:00:00.000000

"""
from alembic import op


revision = 'e53f7a8b2c19'
down_revision = 'd42e6a7b9c11'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'ix_assessments_category_archived',
        'assessments',
        ['category', 'archived'],
        if_not_exists=True,
    )


def downgrade():
    op.drop_index(
        'ix_assessments_category_archived',
        table_name='assessments',
        if_exists=True,
    )