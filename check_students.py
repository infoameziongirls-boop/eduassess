#!/usr/bin/env python3
"""Check student records to debug login issues"""
from app import app, db
from models import Student

with app.app_context():
    students = Student.query.all()
    if not students:
        print("❌ No students found in database!")
    else:
        print(f"✅ Found {len(students)} students:\n")
        print(f"{'First Name':<20} {'Last Name':<20} {'Student #':<15} {'Reference #':<15} {'Class':<10}")
        print("=" * 80)
        for student in students:
            print(f"{student.first_name:<20} {student.last_name:<20} {student.student_number:<15} {str(student.reference_number or 'N/A'):<15} {str(student.class_name or 'N/A'):<10}")
