"""add_student_id_code

Revision ID: d42e6a7b9c11
Revises: c31f4c2e8d10
Create Date: 2026-09-04 18:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd42e6a7b9c11'
down_revision = 'c31f4c2e8d10'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'] for column in inspector.get_columns('students')}
    if 'student_id_code' not in columns:
        op.add_column('students', sa.Column('student_id_code', sa.String(length=50), nullable=True))
    op.create_index(
        'ix_students_student_id_code',
        'students',
        ['student_id_code'],
        unique=True,
        if_not_exists=True,
    )


def downgrade():
    op.drop_index('ix_students_student_id_code', table_name='students', if_exists=True)
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'student_id_code' in {
        column['name'] for column in inspector.get_columns('students')
    }:
        op.drop_column('students', 'student_id_code')