#!/usr/bin/env python3
"""
seed_test_data.py

Creates two test students with complete assessment records, plus one
teacher account per subject, so the dashboards, teacher_results grouping,
and template-based grade calculations can be exercised end-to-end.

ASSUMPTIONS MADE (verify these before trusting the output):
  - Araba Mensah is assigned to study area 'science_b' (confirmed by user;
    Science B's elective set uses French in place of Science A's Economics).
  - Daniella's surname was not provided; placeholder 'Boateng' is used.
  - Both students are placed in class 'Form 2' (unspecified in the request).
  - Teacher password for ALL seeded teachers: 'Teacher@123'
  - Every teacher is scoped to class 'Form 2' only.

This script is idempotent for students: if a student_number already has
assessments, it will NOT create duplicates on re-run. Delete the relevant
rows manually (or drop the DB) if you want a clean re-seed.

Run from the same directory as app.py, with the same venv/dependencies
used to run the Flask app itself:

    python seed_test_data.py
"""

import os
import sys
import random
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from app import app, db, bcrypt
from models import User, Student, Assessment, Setting, SystemConfig

random.seed(42)  # reproducible dummy scores across runs

CATEGORIES = ['ica1', 'ica2', 'icp1', 'icp2', 'gp1', 'gp2',
              'practical', 'mid_term', 'end_term']

CATEGORY_MAX_SCORES = {
    'ica1': 50, 'ica2': 50, 'icp1': 50, 'icp2': 50,
    'gp1': 50, 'gp2': 50, 'practical': 100, 'mid_term': 100, 'end_term': 100,
}

TEACHER_PASSWORD = 'Teacher@123'
TEST_CLASS = 'Form 2'

# Mirrors the official curriculum mapping applied by
# /admin/apply-default-study-area-subjects in app.py, restricted to the
# two study areas needed here. If your SystemConfig already has a full
# STUDY_AREA_SUBJECTS map, this script will NOT overwrite it — it only
# fills in these two keys if they are missing.
COMMON_CORE = ['mathematics', 'general_science', 'social_studies',
               'english_language', 'physical_education_health', 'ict']
SCIENCE_CORE = ['mathematics', 'social_studies', 'english_language',
                 'physical_education_health', 'ict']

STUDY_AREA_CURRICULUM = {
    'science_b': {
        'core': SCIENCE_CORE,
        'electives': ['biology', 'chemistry', 'physics',
                      'additional_mathematics', 'geography', 'french'],
    },
    'home_economics_c': {
        'core': COMMON_CORE,
        'electives': ['management_in_living', 'food_nutrition', 'biology',
                      'arts_design_studio', 'music'],
    },
}

# Two distinct score profiles so the two students don't look identical
# in the dashboard — Araba trending high, Daniella trending mid-range.
SCORE_PROFILES = {
    'high': (78, 96),
    'mid':  (55, 82),
}


def ensure_study_area_subjects():
    """Fill in only the two study areas we need, without clobbering an
    existing full curriculum config if one is already present."""
    sas = SystemConfig.get_config('STUDY_AREA_SUBJECTS', {}) or {}
    changed = False
    for area, mapping in STUDY_AREA_CURRICULUM.items():
        if area not in sas:
            sas[area] = mapping
            changed = True
    if changed:
        SystemConfig.set_config('STUDY_AREA_SUBJECTS', sas)
        app.config['STUDY_AREA_SUBJECTS'] = sas
        print(f"[OK] STUDY_AREA_SUBJECTS updated with: {list(STUDY_AREA_CURRICULUM.keys())}")
    else:
        print("[OK] STUDY_AREA_SUBJECTS already covers the needed study areas — left untouched")


def get_or_create_teacher(subject_key):
    username = f"teacher_{subject_key}"
    teacher = User.query.filter_by(username=username).first()
    if teacher:
        return teacher, False
    pw_hash = bcrypt.generate_password_hash(TEACHER_PASSWORD).decode('utf-8')
    teacher = User(
        username=username,
        password_hash=pw_hash,
        role='teacher',
        subject=subject_key,
        class_name=TEST_CLASS,
    )
    teacher.set_classes_list([TEST_CLASS])
    db.session.add(teacher)
    db.session.flush()  # get teacher.id without a full commit
    return teacher, True


def get_or_create_student(student_number, reference_number, first_name, last_name,
                           class_name, study_area, dob):
    student = Student.query.filter_by(student_number=student_number).first()
    if student:
        return student, False
    student = Student(
        student_number=student_number,
        reference_number=reference_number,
        first_name=first_name,
        last_name=last_name,
        class_name=class_name,
        study_area=study_area,
        date_of_birth=dob,
    )
    db.session.add(student)
    db.session.flush()
    return student, True


def seed_assessments_for_student(student, subjects, teachers_by_subject,
                                  term, academic_year, session_name, profile):
    lo, hi = SCORE_PROFILES[profile]
    created = 0
    base_date = date.today() - timedelta(days=60)
    for subject_key in subjects:
        teacher = teachers_by_subject[subject_key]
        for i, category in enumerate(CATEGORIES):
            max_score = CATEGORY_MAX_SCORES[category]
            pct = random.uniform(lo, hi)
            score = round(max_score * pct / 100, 1)
            assessment = Assessment(
                student_id=student.id,
                category=category,
                subject=subject_key,
                class_name=student.class_name,
                score=score,
                max_score=max_score,
                term=term,
                academic_year=academic_year,
                session=session_name,
                assessor=teacher.username,
                teacher_id=teacher.id,
                comments=None,
                date_recorded=base_date + timedelta(days=i * 3),
                archived=False,
            )
            db.session.add(assessment)
            created += 1
    return created


def seed():
    with app.app_context():
        print("=" * 60)
        print("SEEDING TEST DATA")
        print("=" * 60)

        ensure_study_area_subjects()

        setting = Setting.query.first()
        if not setting:
            setting = Setting(current_term='term1',
                               current_academic_year='2024-2025',
                               current_session='First Term')
            db.session.add(setting)
            db.session.flush()
        term, academic_year, session_name = (
            setting.current_term, setting.current_academic_year, setting.current_session
        )

        # ---- Teachers: one per unique subject across both study areas ----
        all_subjects = set()
        for mapping in STUDY_AREA_CURRICULUM.values():
            all_subjects.update(mapping['core'])
            all_subjects.update(mapping['electives'])

        teachers_by_subject = {}
        created_teachers = 0
        for subject_key in sorted(all_subjects):
            teacher, was_created = get_or_create_teacher(subject_key)
            teachers_by_subject[subject_key] = teacher
            created_teachers += was_created
        db.session.commit()
        print(f"[OK] Teachers ready: {len(teachers_by_subject)} total "
              f"({created_teachers} newly created)")

        # ---- Students ----
        araba, araba_new = get_or_create_student(
            student_number='STU-ARABA-001',
            reference_number='REF-ARABA-001',
            first_name='Araba', last_name='Mensah',
            class_name=TEST_CLASS, study_area='science_b',
            dob=date(2009, 3, 14),
        )
        daniella, daniella_new = get_or_create_student(
            student_number='STU-DANIELLA-001',
            reference_number='REF-DANIELLA-001',
            first_name='Daniella', last_name='Boateng',
            class_name=TEST_CLASS, study_area='home_economics_c',
            dob=date(2009, 7, 22),
        )
        db.session.commit()
        print(f"[OK] Araba Mensah    -> student_id={araba.id}    (new={araba_new})")
        print(f"[OK] Daniella Boateng -> student_id={daniella.id} (new={daniella_new})")

        # ---- Assessments (skip if student already has some, to stay idempotent) ----
        total_created = 0

        if Assessment.query.filter_by(student_id=araba.id).count() == 0:
            science_subjects = (STUDY_AREA_CURRICULUM['science_b']['core']
                                 + STUDY_AREA_CURRICULUM['science_b']['electives'])
            n = seed_assessments_for_student(
                araba, science_subjects, teachers_by_subject,
                term, academic_year, session_name, profile='high'
            )
            total_created += n
            print(f"[OK] Created {n} assessments for Araba across {len(science_subjects)} subjects")
        else:
            print("[SKIP] Araba already has assessment records — not duplicating")

        if Assessment.query.filter_by(student_id=daniella.id).count() == 0:
            home_ec_subjects = (STUDY_AREA_CURRICULUM['home_economics_c']['core']
                                 + STUDY_AREA_CURRICULUM['home_economics_c']['electives'])
            n = seed_assessments_for_student(
                daniella, home_ec_subjects, teachers_by_subject,
                term, academic_year, session_name, profile='mid'
            )
            total_created += n
            print(f"[OK] Created {n} assessments for Daniella across {len(home_ec_subjects)} subjects")
        else:
            print("[SKIP] Daniella already has assessment records — not duplicating")

        db.session.commit()

        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Total assessment rows created this run: {total_created}")
        print("\nTeacher logins (role=teacher), password for all: "
              f"{TEACHER_PASSWORD}")
        for subj in sorted(teachers_by_subject):
            print(f"  - teacher_{subj}")
        print("\nStudent identifiers (use at /student/login — NOTE: the current")
        print("StudentLoginForm has no password field; the identifier alone logs")
        print("the student in, and a matching User row is auto-created on first")
        print("login using the student number as its own password hash):")
        print(f"  - Araba Mensah:    {araba.student_number}  (or ref: {araba.reference_number})")
        print(f"  - Daniella Boateng: {daniella.student_number}  (or ref: {daniella.reference_number})")
        print("=" * 60)


if __name__ == '__main__':
    seed()
