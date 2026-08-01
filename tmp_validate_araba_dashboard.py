import os
import sys
sys.path.insert(0, os.getcwd())
from app import app, calculate_gpa_and_grade, calculate_total_grade_points, get_grade_class_division
from models import Student, Assessment
from template_updater import scores_from_assessments, calculate_scores_from_template

with app.app_context():
    student = Student.query.filter_by(student_number='ARABA001').first()
    if not student:
        raise SystemExit('Student ARABA001 not found')

    print('Student:', student.full_name())
    print('student_number:', student.student_number)
    print('reference_number:', student.reference_number)
    print('class_name:', student.class_name)
    print('study_area:', student.study_area)

    all_assessments = Assessment.query.filter_by(student_id=student.id, archived=False).all()
    print('assessment count:', len(all_assessments))

    summary = student.calculate_subject_final_grades()
    print('\nSubject final results:')
    for key, data in sorted(summary.items()):
        print(f"  {key}: {data}")

    final_pct = student.calculate_final_grade()
    overall = student.get_gpa_and_grade()
    total_points = calculate_total_grade_points(student)
    division = get_grade_class_division(overall['gpa'])
    print('\nOverall aggregation:')
    print('  calculate_final_grade():', final_pct)
    print('  get_gpa_and_grade():', overall)
    print('  calculate_total_grade_points():', total_points)
    print('  get_grade_class_division():', division)

    filtered = calculate_scores_from_template(scores_from_assessments(all_assessments))
    print('\nFull-list template verification:')
    print('  template final_score:', filtered['final_score'])
    print('  template grade:', filtered['grade'])
    print('  template gpa:', filtered['gpa'])
