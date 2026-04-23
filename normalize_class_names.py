#!/usr/bin/env python3
"""
One-off script to normalize class_name values in the database.
This ensures all Student.class_name values match the canonical keys.
"""

from app import app, db, Student, canonical_class_key

def normalize_class_names():
    with app.app_context():
        students = Student.query.all()
        updated_count = 0

        for s in students:
            canonical = canonical_class_key(s.class_name)
            if canonical and canonical != s.class_name:
                print(f"Updating {s.class_name} -> {canonical} for student {s.id}")
                s.class_name = canonical
                updated_count += 1

        if updated_count > 0:
            db.session.commit()
            print(f"Normalized {updated_count} student class names.")
        else:
            print("No class names needed normalization.")

if __name__ == '__main__':
    normalize_class_names()