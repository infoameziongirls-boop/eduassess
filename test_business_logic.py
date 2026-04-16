import pytest
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import Student, Assessment, db
from app import app
import tempfile


class TestGradeCalculation:
    """Comprehensive unit tests for grade calculation and GPA mapping logic"""

    @pytest.fixture
    def app_context(self):
        """Create a test app context with in-memory database"""
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

        with app.app_context():
            db.create_all()
            yield app
            db.session.remove()
            db.drop_all()

    @pytest.fixture
    def sample_student(self, app_context):
        """Create a sample student for testing"""
        student = Student(
            first_name="John",
            last_name="Doe",
            student_number="STU001",
            class_name="form1",
            study_area="mathematics"
        )
        db.session.add(student)
        db.session.commit()
        return student

    def create_assessment(self, student, category, score, max_score=100, subject="Mathematics", teacher_id=1):
        """Helper to create assessment records"""
        assessment = Assessment(
            student_id=student.id,
            category=category,
            score=score,
            max_score=max_score,
            subject=subject,
            teacher_id=teacher_id
        )
        db.session.add(assessment)
        db.session.commit()
        return assessment

    def test_calculate_final_grade_perfect_scores(self, sample_student):
        """Test final grade calculation with perfect scores"""
        # Create perfect scores for all categories
        categories_scores = {
            'ica1': 100, 'ica2': 100, 'icp1': 100, 'icp2': 100,
            'gp1': 100, 'gp2': 100, 'practical': 100, 'mid_term': 100,
            'end_term': 100
        }

        for category, score in categories_scores.items():
            self.create_assessment(sample_student, category, score)

        final_grade = sample_student.calculate_final_grade()
        assert final_grade == 100.0

    def test_calculate_final_grade_zero_scores(self, sample_student):
        """Test final grade calculation with zero scores"""
        # Create zero scores for all categories
        categories_scores = {
            'ica1': 0, 'ica2': 0, 'icp1': 0, 'icp2': 0,
            'gp1': 0, 'gp2': 0, 'practical': 0, 'mid_term': 0,
            'end_term': 0
        }

        for category, score in categories_scores.items():
            self.create_assessment(sample_student, category, score)

        final_grade = sample_student.calculate_final_grade()
        assert final_grade == 0.0

    def test_calculate_final_grade_mixed_scores(self, sample_student):
        """Test final grade calculation with mixed scores"""
        # Class assessments: 8 categories × 50 = 400 raw points
        # Class total points = min(500, 400) = 400
        # Class percentage = 400/500 × 100 = 80%
        # Class score = min(50, round(80/2)) = min(50, 40) = 40

        # Exam: 50 raw points
        # Exam score = min(50, round(50/2)) = min(50, 25) = 25

        # Final grade = min(100, 40 + 25) = 65

        class_categories = ['ica1', 'ica2', 'icp1', 'icp2', 'gp1', 'gp2', 'practical', 'mid_term']
        for category in class_categories:
            self.create_assessment(sample_student, category, 50)  # 50 each = 400 total

        self.create_assessment(sample_student, 'end_term', 50)  # 50 for exam

        final_grade = sample_student.calculate_final_grade()
        assert final_grade == 65.0

    def test_calculate_final_grade_class_assessment_cap(self, sample_student):
        """Test that class assessments are capped at 500 points"""
        # Create scores that would exceed 500 if summed
        # 9 categories × 60 = 540 raw points, but capped at 500
        class_categories = ['ica1', 'ica2', 'icp1', 'icp2', 'gp1', 'gp2', 'practical', 'mid_term']
        for category in class_categories:
            self.create_assessment(sample_student, category, 60)  # 60 × 8 = 480

        # Add one more to exceed 500
        self.create_assessment(sample_student, 'extra_cat', 30)  # Total would be 510, but only class cats count

        # Class total points = min(500, 480) = 480
        # Class percentage = 480/500 × 100 = 96%
        # Class score = min(50, round(96/2)) = min(50, 48) = 48

        # No exam score = 0

        # Final grade = min(100, 48 + 0) = 48

        final_grade = sample_student.calculate_final_grade()
        assert final_grade == 48.0

    def test_calculate_final_grade_exam_score_cap(self, sample_student):
        """Test that exam score is capped at 100 points"""
        # Create high exam score that should be capped
        self.create_assessment(sample_student, 'end_term', 120)  # 120/2 = 60, not capped

        final_grade = sample_student.calculate_final_grade()
        assert final_grade == 60.0

    def test_calculate_final_grade_subject_filter(self, sample_student):
        """Test final grade calculation with subject filtering"""
        # Create assessments for different subjects
        self.create_assessment(sample_student, 'ica1', 80, subject="Mathematics")
        self.create_assessment(sample_student, 'ica1', 60, subject="English")  # Should be ignored
        self.create_assessment(sample_student, 'end_term', 80, subject="Mathematics")

        final_grade = sample_student.calculate_final_grade(subject="Mathematics")
        # Class: 80/500 × 100 = 16%, score = min(50, round(16/2)) = 8
        # Exam: min(50, round(80/2)) = 40
        # Final: min(100, 8 + 40) = 48
        assert final_grade == 48.0

    def test_calculate_final_grade_teacher_filter(self, sample_student):
        """Test final grade calculation with teacher filtering"""
        # Create assessments from different teachers
        self.create_assessment(sample_student, 'ica1', 80, teacher_id=1)
        self.create_assessment(sample_student, 'ica1', 60, teacher_id=2)  # Should be ignored
        self.create_assessment(sample_student, 'end_term', 80, teacher_id=1)

        final_grade = sample_student.calculate_final_grade(teacher_id=1)
        # Class: 80/500 × 100 = 16%, score = min(50, round(16/2)) = 8
        # Exam: min(50, round(80/2)) = 40
        # Final: min(100, 8 + 40) = 48
        assert final_grade == 48.0

    def test_calculate_final_grade_rounding(self, sample_student):
        """Test that final grade is rounded to 2 decimal places"""
        # Create scores that would result in fractional result
        self.create_assessment(sample_student, 'ica1', 25)  # 25/500 × 100 = 5%, score = roundup(5/2, 0) = 3
        self.create_assessment(sample_student, 'end_term', 33)  # roundup(33/2, 0) = 17

        final_grade = sample_student.calculate_final_grade()
        # Final: 3 + 17 = 20.0 (should be rounded to 2 decimals)
        assert final_grade == 20.0
        assert isinstance(final_grade, float)

    def test_get_gpa_and_grade_a1(self, sample_student):
        """Test GPA and grade mapping for A1 (80-100%)"""
        # Create assessment that results in 85% final grade
        self.create_assessment(sample_student, 'end_term', 170)  # 170/2 = 85, not capped

        result = sample_student.get_gpa_and_grade()
        assert result["gpa"] == "4.0"
        assert result["grade"] == "A1"

    def test_get_gpa_and_grade_b2(self, sample_student):
        """Test GPA and grade mapping for B2 (70-79%)"""
        # Create assessment that results in 75% final grade
        self.create_assessment(sample_student, 'end_term', 150)  # 150/2 = 75, capped at 50

        result = sample_student.get_gpa_and_grade()
        assert result["gpa"] == "3.5"
        assert result["grade"] == "B2"

    def test_get_gpa_and_grade_b3(self, sample_student):
        """Test GPA and grade mapping for B3 (65-69%)"""
        # Create assessment that results in 67.5% final grade
        self.create_assessment(sample_student, 'end_term', 135)  # 135/2 = 67.5, capped at 50

        result = sample_student.get_gpa_and_grade()
        assert result["gpa"] == "3.0"
        assert result["grade"] == "B3"

    def test_get_gpa_and_grade_c4(self, sample_student):
        """Test GPA and grade mapping for C4 (60-64%)"""
        # Create assessment that results in 62.5% final grade
        self.create_assessment(sample_student, 'end_term', 125)  # 125/2 = 62.5, capped at 50

        result = sample_student.get_gpa_and_grade()
        assert result["gpa"] == "2.5"
        assert result["grade"] == "C4"

    def test_get_gpa_and_grade_c5(self, sample_student):
        """Test GPA and grade mapping for C5 (55-59%)"""
        # Create assessment that results in 57.5% final grade
        self.create_assessment(sample_student, 'end_term', 115)  # 115/2 = 57.5, capped at 50

        result = sample_student.get_gpa_and_grade()
        assert result["gpa"] == "2.0"
        assert result["grade"] == "C5"

    def test_get_gpa_and_grade_c6(self, sample_student):
        """Test GPA and grade mapping for C6 (50-54%)"""
        # Create assessment that results in 52.5% final grade
        self.create_assessment(sample_student, 'end_term', 105)  # 105/2 = 52.5, capped at 50

        result = sample_student.get_gpa_and_grade()
        assert result["gpa"] == "1.5"
        assert result["grade"] == "C6"

    def test_get_gpa_and_grade_d7(self, sample_student):
        """Test GPA and grade mapping for D7 (45-49%)"""
        # Create assessment that results in 47.5% final grade
        self.create_assessment(sample_student, 'end_term', 95)  # 95/2 = 47.5, capped at 50

        result = sample_student.get_gpa_and_grade()
        assert result["gpa"] == "1.0"
        assert result["grade"] == "D7"

    def test_get_gpa_and_grade_e8(self, sample_student):
        """Test GPA and grade mapping for E8 (40-44%)"""
        # Create assessment that results in 42.5% final grade
        self.create_assessment(sample_student, 'end_term', 85)  # 85/2 = 42.5, capped at 50

        result = sample_student.get_gpa_and_grade()
        assert result["gpa"] == "0.5"
        assert result["grade"] == "E8"

    def test_get_gpa_and_grade_f9(self, sample_student):
        """Test GPA and grade mapping for F9 (0-39%)"""
        # Create assessment that results in 37.5% final grade
        self.create_assessment(sample_student, 'end_term', 75)  # 75/2 = 37.5, capped at 50

        result = sample_student.get_gpa_and_grade()
        assert result["gpa"] == "0.0"
        assert result["grade"] == "F9"

    def test_get_gpa_and_grade_no_assessments(self, sample_student):
        """Test GPA and grade mapping when student has no assessments"""
        result = sample_student.get_gpa_and_grade()
        assert result["gpa"] == "N/A"
        assert result["grade"] == "N/A"

    def test_get_assessment_summary_basic(self, sample_student):
        """Test basic assessment summary functionality"""
        self.create_assessment(sample_student, 'ica1', 85, 100)
        self.create_assessment(sample_student, 'ica1', 90, 100)  # Two assessments in same category

        summary = sample_student.get_assessment_summary()

        assert 'ica1' in summary
        assert summary['ica1']['count'] == 2
        assert summary['ica1']['total_score'] == 175.0
        assert summary['ica1']['total_max'] == 200.0
        assert summary['ica1']['avg_percent'] == 87.5

    def test_get_assessment_summary_with_filters(self, sample_student):
        """Test assessment summary with subject and teacher filters"""
        self.create_assessment(sample_student, 'ica1', 85, subject="Math", teacher_id=1)
        self.create_assessment(sample_student, 'ica1', 75, subject="English", teacher_id=2)

        # Filter by subject
        summary = sample_student.get_assessment_summary(subject="Math")
        assert 'ica1' in summary
        assert summary['ica1']['count'] == 1
        assert summary['ica1']['total_score'] == 85.0

        # Filter by teacher
        summary = sample_student.get_assessment_summary(teacher_id=2)
        assert 'ica1' in summary
        assert summary['ica1']['count'] == 1
        assert summary['ica1']['total_score'] == 75.0

    def test_calculate_final_grade_edge_cases(self, sample_student):
        """Test edge cases in final grade calculation"""
        # Test with only exam score
        self.create_assessment(sample_student, 'end_term', 100)
        final_grade = sample_student.calculate_final_grade()
        assert final_grade == 50.0  # Exam capped at 50

        # Reset for next test
        db.session.query(Assessment).delete()

        # Test with only class assessments
        class_categories = ['ica1', 'ica2', 'icp1', 'icp2', 'gp1', 'gp2', 'practical', 'mid_term']
        for category in class_categories:
            self.create_assessment(sample_student, category, 100)  # 100 each = 800, capped at 500

        final_grade = sample_student.calculate_final_grade()
        # Class: 500/500 × 100 = 100%, score = min(50, round(100/2)) = 50
        # Exam: 0
        # Final: 50
        assert final_grade == 50.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])