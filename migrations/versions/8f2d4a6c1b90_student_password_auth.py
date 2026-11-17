"""add student credential controls

Revision ID: 8f2d4a6c1b90
Revises: 5c8d11f23a40
Create Date: 2026-11-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '8f2d4a6c1b90'
down_revision = '5c8d11f23a40'
branch_labels = None
depends_on = None


def upgrade():
    columns = {
        column['name']
        for column in sa.inspect(op.get_bind()).get_columns('users')
    }
    additions = (
        sa.Column(
            'must_change_password',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            'credentials_enabled',
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            'temporary_password_used',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            'auth_version',
            sa.Integer(),
            nullable=False,
            server_default='1',
        ),
    )
    missing = [column for column in additions if column.name not in columns]
    if missing:
        with op.batch_alter_table('users') as batch_op:
            for column in missing:
                batch_op.add_column(column)

    users = sa.table(
        'users',
        sa.column('role', sa.String()),
        sa.column('must_change_password', sa.Boolean()),
        sa.column('credentials_enabled', sa.Boolean()),
        sa.column('temporary_password_used', sa.Boolean()),
        sa.column('auth_version', sa.Integer()),
    )
    op.execute(
        users.update()
        .where(users.c.role == 'student')
        .values(
            must_change_password=sa.true(),
            credentials_enabled=sa.false(),
            auth_version=users.c.auth_version + 1,
        )
    )


def downgrade():
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('auth_version')
        batch_op.drop_column('temporary_password_used')
        batch_op.drop_column('credentials_enabled')
        batch_op.drop_column('must_change_password')
