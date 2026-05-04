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
    op.create_index(
        "ix_assessment_student_subject_archived",
        "assessments",
        ["student_id", "subject", "archived"],
    )
    op.create_index(
        "ix_assessment_teacher_archived",
        "assessments",
        ["teacher_id", "archived"],
    )
    op.create_index(
        "ix_student_class_area",
        "students",
        ["class_name", "study_area"],
    )


def downgrade():
    op.drop_index("ix_assessment_student_subject_archived", table_name="assessments")
    op.drop_index("ix_assessment_teacher_archived",         table_name="assessments")
    op.drop_index("ix_student_class_area",                  table_name="students")
