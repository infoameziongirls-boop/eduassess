#!/usr/bin/env python3
"""
Diagnose why a teacher's dashboard roster is missing students after a
class promotion. Run this the same way you run check_students.py:

    python diagnose_teacher_visibility.py <teacher_username>

It shows:
  1. The teacher's stored subject + assigned classes (raw DB values).
  2. How many students actually exist per class (proves promotion moved
     the data, it didn't delete it).
  3. The study_area breakdown of students in the teacher's classes.
  4. Whether STUDY_AREA_SUBJECTS maps the teacher's subject into each of
     those study areas — this is the filter most likely to be silently
     dropping students.
"""
import sys
from app import app
from models import User, Student, SystemConfig

def main(username):
    with app.app_context():
        teacher = User.query.filter_by(username=username).first()
        if not teacher:
            print(f"No user found with username '{username}'")
            return

        print(f"=== Teacher: {teacher.username} ===")
        print(f"role: {teacher.role}")
        print(f"subject (raw): {teacher.subject!r}")
        print(f"class_name (legacy single field): {teacher.class_name!r}")
        print(f"classes (raw JSON): {teacher.classes!r}")
        teacher_classes = teacher.get_classes_list()
        print(f"classes (parsed): {teacher_classes}")
        print()

        print("=== Student counts per class (proves data is/isn't there) ===")
        rows = (Student.query
                .with_entities(Student.class_name)
                .all())
        from collections import Counter
        counts = Counter(r[0] for r in rows)
        for cls, cnt in sorted(counts.items(), key=lambda x: (x[0] or '')):
            print(f"  {cls!r}: {cnt}")
        print()

        if not teacher_classes:
            print("Teacher has NO classes assigned (get_classes_list() is empty) "
                  "-> get_teacher_students_query() will return an empty/None result "
                  "for the class-based branch. This alone would explain missing rosters.")
            print()

        sas = SystemConfig.get_config('STUDY_AREA_SUBJECTS', {}) or {}
        configured = any(v.get('core') or v.get('electives') for v in sas.values())
        print(f"=== STUDY_AREA_SUBJECTS configured: {configured} ===")

        teacher_subject = (teacher.subject or '').strip()
        eligible_areas = [
            area_key for area_key, subjects in sas.items()
            if teacher_subject in subjects.get('core', []) or
               teacher_subject in subjects.get('electives', [])
        ]
        print(f"Teacher subject '{teacher_subject}' is core/elective in these areas: {eligible_areas}")
        print()

        for cls in (teacher_classes or []):
            print(f"--- Study areas present among students in {cls!r} ---")
            students = Student.query.filter_by(class_name=cls).all()
            area_counts = Counter(s.study_area for s in students)
            for area, cnt in sorted(area_counts.items(), key=lambda x: (x[0] or '')):
                flag = "OK - subject mapped here" if area in eligible_areas else \
                       "NOT MAPPED -> these students will be invisible to this teacher" \
                       if configured else "N/A (area rules not enforced, class-only fallback applies)"
                print(f"  study_area={area!r}: {cnt} students -> {flag}")
            print()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python diagnose_teacher_visibility.py <teacher_username>")
        sys.exit(1)
    main(sys.argv[1])
