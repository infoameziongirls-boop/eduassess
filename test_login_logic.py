#!/usr/bin/env python3
"""Test student login logic"""
from app import app, db
from models import Student

with app.app_context():
    # Test with a real student from the database
    test_students = [
        ("AYITEY", "STU250030606104", "STU892048"),  # First student
        ("EHUN", "STU250030606100", "STU860326"),    # Second student
    ]
    
    for first_name, student_num, ref_num in test_students:
        print(f"\n{'='*60}")
        print(f"Testing: {first_name}")
        print(f"{'='*60}")
        
        # Test case-insensitive lookup
        for test_input in [first_name, first_name.lower(), first_name.title()]:
            student = Student.query.filter(db.func.lower(Student.first_name) == test_input.lower()).first()
            print(f"Input: '{test_input}' -> Found: {student is not None}")
            
            if student:
                print(f"  ✅ Student found: {student.full_name()}")
                print(f"     Student Number: {student.student_number}")
                print(f"     Reference Number: {student.reference_number}")
                
                # Test password matching
                print(f"\n  Testing password matching:")
                for pwd in [student_num, ref_num, "wrongpassword"]:
                    match = (pwd == student.student_number or pwd == student.reference_number)
                    print(f"    Password '{pwd}' -> {'✅ MATCH' if match else '❌ NO MATCH'}")
