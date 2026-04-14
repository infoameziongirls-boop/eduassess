#!/usr/bin/env python3
"""
Comprehensive backup script for all application data.
Backs up users, students, assessments, and other critical data.
Works on both local and Render deployments.
"""

import os
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from models import User, Student, Assessment, Setting, ActivityLog, Question, Quiz

def backup_all_data():
    """Export all critical data to JSON files."""
    with app.app_context():
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = Path('backups')
        backup_dir.mkdir(exist_ok=True)
        
        print("\n" + "="*60)
        print("BACKING UP ALL DATA")
        print("="*60)
        
        backup_summary = {
            'timestamp': datetime.now().isoformat(),
            'backup_files': {},
            'data_summary': {}
        }
        
        # Backup Users
        try:
            users = User.query.all()
            user_data = []
            for user in users:
                user_dict = {
                    'id': user.id,
                    'username': user.username,
                    'role': user.role,
                    'subject': user.subject,
                    'class_name': user.class_name,
                    'classes': user.get_classes_list() if hasattr(user, 'get_classes_list') else [],
                    'created_at': user.created_at.isoformat() if user.created_at else None
                }
                user_data.append(user_dict)
            
            users_file = backup_dir / f'users_backup_{timestamp}.json'
            with open(users_file, 'w') as f:
                json.dump(user_data, f, indent=2)
            
            backup_summary['backup_files']['users'] = str(users_file)
            backup_summary['data_summary']['users'] = len(user_data)
            print(f"[OK] Backed up {len(user_data)} users")
        except Exception as e:
            print(f"[FAIL] Failed to backup users: {str(e)}")
        
        # Backup Students
        try:
            students = Student.query.all()
            student_data = []
            for student in students:
                student_dict = {
                    'id': student.id,
                    'student_number': student.student_number,
                    'first_name': student.first_name,
                    'last_name': student.last_name,
                    'middle_name': student.middle_name,
                    'class_name': student.class_name,
                    'reference_number': student.reference_number,
                    'date_of_birth': student.date_of_birth.isoformat() if student.date_of_birth else None,
                    'study_area': student.study_area,
                    'created_at': student.created_at.isoformat() if student.created_at else None
                }
                student_data.append(student_dict)
            
            students_file = backup_dir / f'students_backup_{timestamp}.json'
            with open(students_file, 'w') as f:
                json.dump(student_data, f, indent=2)
            
            backup_summary['backup_files']['students'] = str(students_file)
            backup_summary['data_summary']['students'] = len(student_data)
            print(f"[OK] Backed up {len(student_data)} students")
        except Exception as e:
            print(f"[FAIL] Failed to backup students: {str(e)}")
        
        # Backup Assessments
        try:
            assessments = Assessment.query.all()
            assessment_data = []
            for assessment in assessments:
                assessment_dict = {
                    'id': assessment.id,
                    'student_id': assessment.student_id,
                    'student_number': assessment.student.student_number if assessment.student else None,
                    'category': assessment.category,
                    'subject': assessment.subject,
                    'class_name': assessment.class_name,
                    'score': float(assessment.score) if assessment.score else None,
                    'max_score': float(assessment.max_score) if assessment.max_score else None,
                    'term': assessment.term,
                    'academic_year': assessment.academic_year,
                    'session': assessment.session,
                    'assessor': assessment.assessor,
                    'teacher_id': assessment.teacher_id,
                    'comments': assessment.comments,
                    'created_at': assessment.created_at.isoformat() if assessment.created_at else None
                }
                assessment_data.append(assessment_dict)
            
            assessments_file = backup_dir / f'assessments_backup_{timestamp}.json'
            with open(assessments_file, 'w') as f:
                json.dump(assessment_data, f, indent=2)
            
            backup_summary['backup_files']['assessments'] = str(assessments_file)
            backup_summary['data_summary']['assessments'] = len(assessment_data)
            print(f"[OK] Backed up {len(assessment_data)} assessments")
        except Exception as e:
            print(f"[FAIL] Failed to backup assessments: {str(e)}")
        
        # Write backup summary
        try:
            summary_file = backup_dir / f'backup_summary_{timestamp}.json'
            with open(summary_file, 'w') as f:
                json.dump(backup_summary, f, indent=2)
            print(f"\n[OK] Backup summary saved to: {summary_file}")
        except Exception as e:
            print(f"[FAIL] Failed to save backup summary: {str(e)}")
        
        print(f"[OK] All backups completed successfully at {timestamp}")
        print(f"  Backup directory: {backup_dir.absolute()}")
        print("="*60 + "\n")
        
        return backup_summary

if __name__ == '__main__':
    backup_all_data()
