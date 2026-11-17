"""add_composite_indexes

Revision ID: ba914e3191a7
Revises: 
Create Date: 2026-05-04 19:50:59.363192

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ba914e3191a7'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    existing = {
        index["name"]
        for table in ("assessments", "students")
        for index in sa.inspect(op.get_bind()).get_indexes(table)
    }
    indexes = (
        (
            "ix_assessment_student_subject_archived",
            "assessments",
            ["student_id", "subject", "archived"],
        ),
        ("ix_assessment_teacher_archived", "assessments", ["teacher_id", "archived"]),
        ("ix_student_class_area", "students", ["class_name", "study_area"]),
    )
    for name, table, columns in indexes:
        if name not in existing:
            op.create_index(name, table, columns)


def downgrade():
    op.drop_index(
        "ix_assessment_student_subject_archived",
        table_name="assessments",
        if_exists=True,
    )
    op.drop_index(
        "ix_assessment_teacher_archived",
        table_name="assessments",
        if_exists=True,
    )
    op.drop_index("ix_student_class_area", table_name="students", if_exists=True)
