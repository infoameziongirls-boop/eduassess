"""
Excel Template Handler
Handles reading from and writing to Excel templates while preserving formatting
"""
import os
import tempfile
import shutil
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Border, Alignment
from datetime import datetime


class ExcelTemplateHandler:
    """Handle Excel template operations"""
    
    def __init__(self, template_path):
        """
        Initialize with path to Excel template
        
        Args:
            template_path: Path to the Excel template file
        """
        self.template_path = template_path
        
    def load_template(self):
        """Load the Excel template workbook"""
        if not os.path.exists(self.template_path):
            raise FileNotFoundError(f"Template not found: {self.template_path}")
        
        # Copy template to temp file to avoid lock issues
        temp_fd, temp_path = tempfile.mkstemp(suffix='.xlsx')
        os.close(temp_fd)
        shutil.copy2(self.template_path, temp_path)
        self.temp_path = temp_path
        return load_workbook(temp_path)
    
    def export_student_to_template(self, student, assessments, output_path, config):
        """
        Export student data to Excel template
        
        Args:
            student: Student object
            assessments: List of Assessment objects
            output_path: Where to save the filled template
            config: App config with category labels and weights
        """
        # Load template
        wb = self.load_template()
        ws = wb.active  # Use the first sheet
        
        # Fill in student information (adjust cell references based on your template)
        self._write_student_info(ws, student)
        
        # Fill in assessments by category
        self._write_assessments(ws, assessments, config)
        
        # Calculate and write summary statistics
        self._write_summary(ws, assessments, config)
        
        # Save the filled template
        wb.save(output_path)
        return output_path
    
    def export_all_students_to_template(self, students, output_path, config):
        """
        Export all students to a summary Excel template
        
        Args:
            students: List of Student objects
            output_path: Where to save the filled template
            config: App config
        """
        wb = self.load_template()
        ws = wb.active
        
        # Starting row for data (adjust based on your template)
        start_row = 5  # Assumes rows 1-4 are headers
        
        for idx, student in enumerate(students):
            row = start_row + idx
            
            # Write student data (adjust column indices based on your template)
            ws.cell(row=row, column=1, value=student.student_number)
            ws.cell(row=row, column=2, value=student.full_name())
            ws.cell(row=row, column=3, value=student.study_area if student.study_area else "")
            
            # Calculate summary for each category
            summary = student.get_assessment_summary()
            
            # Write category averages (adjust columns as needed)
            col = 4
            for cat in ["IA", "IPA", "PP", "MSE", "ETE"]:
                if cat in summary:
                    ws.cell(row=row, column=col, value=summary[cat]["avg_percent"])
                else:
                    ws.cell(row=row, column=col, value="")
                col += 1
            
            # Write final grade
            final = student.calculate_final_grade()
            ws.cell(row=row, column=col, value=final if final else "")
        
        wb.save(output_path)
        return output_path
    
    def _write_student_info(self, ws, student):
        """Write student information to specific cells"""
        # Adjust these cell references based on your template
        ws['B2'] = student.student_number
        ws['B3'] = student.full_name()
        ws['B4'] = student.study_area if student.study_area else ""
        ws['B5'] = datetime.now().strftime('%Y-%m-%d')
    
    def _write_assessments(self, ws, assessments, config):
        """Write assessment data to the template"""
        # Group assessments by category
        by_category = {}
        for assessment in assessments:
            if assessment.category not in by_category:
                by_category[assessment.category] = []
            by_category[assessment.category].append(assessment)
        
        # Define starting rows for each category (adjust based on your template)
        category_rows = {
            "IA": 8,    # Individual Assessments start at row 8
            "IPA": 13,  # Individual Projects start at row 13
            "PP": 18,   # Practical Portfolio start at row 18
            "MSE": 23,  # Mid-Semester Exams start at row 23
            "ETE": 28   # End-of-Term Exams start at row 28
        }
        
        # Write each category's assessments
        for category, start_row in category_rows.items():
            if category in by_category:
                assessments_list = by_category[category]
                
                for idx, assessment in enumerate(assessments_list):
                    row = start_row + idx
                    
                    # Write assessment data (adjust columns based on template)
                    ws.cell(row=row, column=1, value=assessment.subject or "")
                    ws.cell(row=row, column=2, value=assessment.score)
                    ws.cell(row=row, column=3, value=assessment.max_score)
                    ws.cell(row=row, column=4, value=assessment.get_percentage())
                    ws.cell(row=row, column=5, value=assessment.term or "")
                    ws.cell(row=row, column=6, value=assessment.session or "")
                    ws.cell(row=row, column=7, value=assessment.assessor or "")
                    ws.cell(row=row, column=8, value=assessment.comments or "")
    
    def _write_summary(self, ws, assessments, config):
        """Write summary statistics"""
        from collections import defaultdict
        
        # Calculate summary by category
        summary = defaultdict(lambda: {"total_score": 0, "total_max": 0, "count": 0})
        
        for assessment in assessments:
            cat = assessment.category
            summary[cat]["total_score"] += assessment.score
            summary[cat]["total_max"] += assessment.max_score
            summary[cat]["count"] += 1
        
        # Write summary to specific cells (adjust based on your template)
        summary_row = 35  # Starting row for summary section
        
        for idx, (cat, label) in enumerate(config['CATEGORY_LABELS'].items()):
            row = summary_row + idx
            
            if cat in summary and summary[cat]["total_max"] > 0:
                avg = (summary[cat]["total_score"] / summary[cat]["total_max"]) * 100
                ws.cell(row=row, column=1, value=label)
                ws.cell(row=row, column=2, value=summary[cat]["count"])
                ws.cell(row=row, column=3, value=f"{avg:.2f}%")
            else:
                ws.cell(row=row, column=1, value=label)
                ws.cell(row=row, column=2, value=0)
                ws.cell(row=row, column=3, value="N/A")
        
        # Calculate and write final weighted grade
        final = 0.0
        weight_used = 0.0
        
        for cat, weight in config['ASSESSMENT_WEIGHTS'].items():
            if cat in summary and summary[cat]["total_max"] > 0:
                avg = (summary[cat]["total_score"] / summary[cat]["total_max"]) * 100
                final += avg * weight
                weight_used += weight
        
        if weight_used > 0:
            ws.cell(row=summary_row + 6, column=1, value="Final Weighted Grade:")
            ws.cell(row=summary_row + 6, column=3, value=f"{final:.2f}%")


class ExcelBulkImporter:
    """Handle bulk import of assessments from Excel"""
    
    def __init__(self, file_path):
        """
        Initialize with path to Excel file
        
        Args:
            file_path: Path to the Excel file to import
        """
        self.file_path = file_path
    
    def import_assessments(self, start_row=2):
        """
        Import assessments from Excel file
        
        Args:
            start_row: Row number where data starts (default 2, assumes row 1 is header)
            
        Returns:
            List of dictionaries containing assessment data
        """
        wb = load_workbook(self.file_path, data_only=True)
        ws = wb.active
        
        assessments = []
        
        # Read data starting from start_row
        for row in ws.iter_rows(min_row=start_row, values_only=True):
            # Skip empty rows
            if not any(row):
                continue
            
            # Map columns to fields (adjust indices based on your template)
            assessment_data = {
                'student_number': row[0],      # Column A
                'category': row[1],            # Column B
                'subject': row[2],             # Column C
                'score': row[3],               # Column D
                'max_score': row[4],           # Column E
                'term': row[5],                # Column F
                'session': row[6],             # Column G
                'assessor': row[7],            # Column H
                'comments': row[8] if len(row) > 8 else ""  # Column I
            }
            
            # Validate required fields
            if assessment_data['student_number'] and assessment_data['score'] is not None:
                assessments.append(assessment_data)
        
        wb.close()
        return assessments


class StudentBulkImporter:
    """Handle bulk import of students from Excel"""
    
    def __init__(self, file_path):
        """
        Initialize with path to Excel file
        
        Args:
            file_path: Path to the Excel file to import
        """
        self.file_path = file_path
    
    def import_students(self, start_row=2):
        """
        Import students from Excel file
        
        Args:
            start_row: Row number where data starts (default 2, assumes row 1 is header)
            
        Returns:
            List of dictionaries containing student data
        """
        wb = load_workbook(self.file_path, data_only=True)
        ws = wb.active
        
        students = []
        
        # Read data starting from start_row
        def normalize(value):
            if value is None:
                return None
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            return str(value).strip()

        for row in ws.iter_rows(min_row=start_row, values_only=True):
            # Skip empty rows
            if not any(row):
                continue

            # Map columns to fields (adjust indices based on your template)
            student_data = {
                'student_number': normalize(row[0]) if len(row) > 0 else None,
                'first_name': normalize(row[1]) if len(row) > 1 else None,
                'last_name': normalize(row[2]) if len(row) > 2 else None,
                'middle_name': normalize(row[3]) if len(row) > 3 else None,
                'class_name': normalize(row[4]) if len(row) > 4 else None,
                'study_area': normalize(row[5]) if len(row) > 5 else None
            }

            # Validate required fields
            if student_data['student_number'] and student_data['first_name'] and student_data['last_name']:
                students.append(student_data)
        
        wb.close()
        return students


class TeacherBulkImporter:
    """Handle bulk import of teachers and admin users from Excel"""

    def __init__(self, file_path):
        self.file_path = file_path

    def import_teachers(self, start_row=2):
        wb = load_workbook(self.file_path, data_only=True)
        ws = wb.active

        teachers = []

        def normalize(value):
            if value is None:
                return None
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            return str(value).strip()

        for row in ws.iter_rows(min_row=start_row, values_only=True):
            if not any(row):
                continue

            teacher_data = {
                'username': normalize(row[0]) if len(row) > 0 else None,
                'password': normalize(row[1]) if len(row) > 1 else None,
                'role': normalize(row[2]) if len(row) > 2 else None,
                'subject': normalize(row[3]) if len(row) > 3 else None,
                'classes': normalize(row[4]) if len(row) > 4 else None
            }

            if teacher_data['username']:
                teachers.append(teacher_data)

        wb.close()
        return teachers


class QuestionBulkImporter:
    """Handle bulk import of questions from Excel"""
    
    def __init__(self, file_path):
        """
        Initialize with path to Excel file
        
        Args:
            file_path: Path to the Excel file to import
        """
        self.file_path = file_path
    
    def import_questions(self, start_row=2):
        """
        Import questions from Excel file
        
        Args:
            start_row: Row number where data starts (default 2, assumes row 1 is header)
            
        Returns:
            List of dictionaries containing question data
        """
        wb = load_workbook(self.file_path, data_only=True)
        ws = wb.active
        
        questions = []
        
        # Read data starting from start_row
        for row in ws.iter_rows(min_row=start_row, values_only=True):
            # Skip empty rows
            if not any(row):
                continue
            
            # Map columns to fields
            question_data = {
                'question_text': row[0],       # Column A
                'question_type': row[1],       # Column B: mcq, true_false, short_answer
                'option_a': row[2] if len(row) > 2 else None,      # Column C
                'option_b': row[3] if len(row) > 3 else None,      # Column D
                'option_c': row[4] if len(row) > 4 else None,      # Column E
                'option_d': row[5] if len(row) > 5 else None,      # Column F
                'correct_answer': row[6],     # Column G
                'difficulty': row[7] if len(row) > 7 else 'medium', # Column H
                'explanation': row[8] if len(row) > 8 else None    # Column I
            }
            
            # Validate required fields
            if question_data['question_text'] and question_data['question_type'] and question_data['correct_answer']:
                # Process options based on type
                if question_data['question_type'].lower() == 'mcq':
                    question_data['options'] = [question_data['option_a'], question_data['option_b'], 
                                              question_data['option_c'], question_data['option_d']]
                else:
                    question_data['options'] = None
                
                questions.append(question_data)
        
        wb.close()
        return questions


def create_default_template(output_path):
    """
    Create a default Excel template if none exists.
    This template matches the layout expected by template_updater.AssessmentTemplateUpdater.

    Args:
        output_path: Where to save the template
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "ASSESSMENT TEMPLATE"

    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=12)

    # Top-level information
    ws['A1'] = "SCHOOL:"
    ws['A2'] = "SUBJECT:"
    ws['A3'] = "TERM/YEAR:"
    ws['A4'] = "FORM:"

    ws['E5'] = "CONTINUOUS ASSESSMENT SHEET - 2025"
    ws['E5'].font = Font(bold=True)

    ws['B7'] = "TOTAL STUDENTS"
    ws['C7'] = "=COUNTA(B10:B110)"
    ws['D7'] = "Points/Weighting:"
    ws['E7'] = 50
    ws['F7'] = 50
    ws['G7'] = 100
    ws['H7'] = 50
    ws['I7'] = 50
    ws['J7'] = 100

    ws['E6'] = "INDIVIDUAL CLASS ASSESSMENT"
    ws['G6'] = "SUB TOTAL (I.C.A.)"
    ws['H6'] = "INDIVIDUAL CLASS PROJECT"
    ws['J6'] = "SUB TOTAL TEST(C.P)"

    # Row 9 headers for the student table
    headers = [
        "Serial Number", "Name of Students", "Ref. Id", "Study Area",
        "ICA1", "ICA2", "SUB TOTAL (I.C.A.)", "ICP1", "ICP2", "SUB TOTAL TEST(C.P)",
        "GP1", "GP2", "SUB TOTAL (G.P)", "Practical", "Mid Term", "Total Class",
        "%", "AVG. CLASS", "End Term", "AVG. EXAMS SC.", "Total 50 + 50",
        "GPA", "Grade", None, "INSTRUCTIONS"
    ]

    for idx, header in enumerate(headers, start=1):
        ws.cell(row=9, column=idx, value=header)
        if header:
            ws.cell(row=9, column=idx).font = header_font
            ws.cell(row=9, column=idx).fill = header_fill

    # Set up the first data row formulas so the template is usable without a custom file
    row = 10
    ws[f"G{row}"] = f"=MIN(100, (SUM(E{row}:F{row})))"
    ws[f"J{row}"] = f"=MIN(100,(SUM(H{row}:I{row})))"
    ws[f"M{row}"] = f"=MIN(100,(SUM(K{row}:L{row})))"
    ws[f"P{row}"] = f"=MIN(500, (SUM(G{row},J{row},M{row},N{row},O{row})))"
    ws[f"Q{row}"] = f"=P{row}/500*100"
    ws[f"R{row}"] = f"=MIN(50, (ROUNDUP(SUM(Q{row})/2,0)))"
    ws[f"T{row}"] = f"=MIN(50, (ROUNDUP(SUM(S{row})/2,0)))"
    ws[f"U{row}"] = f"=MIN(100, (SUM(R{row},T{row})))"
    ws[f"V{row}"] = f"=U{row}"
    ws[f"W{row}"] = (
        f"=IF(U{row}>=80,\"4.0\",IF(U{row}>=70,\"3.5\",IF(U{row}>=65,\"3.0\","
        f"IF(U{row}>=60,\"2.5\",IF(U{row}>=55,\"2.0\",IF(U{row}>=50,\"1.5\","
        f"IF(U{row}>=45,\"1.0\",IF(U{row}>=40,\"0.5\",IF(U{row}<40,\"0.0\"))))))))))"
    )
    ws[f"X{row}"] = (
        f"=IF(U{row}>=80,\"A1\",IF(U{row}>=70,\"B2\",IF(U{row}>=65,\"B3\","
        f"IF(U{row}>=60,\"C4\",IF(U{row}>=55,\"C5\",IF(U{row}>=50,\"C6\","
        f"IF(U{row}>=45,\"D7\",IF(U{row}>=40,\"E8\",IF(U{row}<40,\"F9\"))))))))))"
    )

    # Set column widths for readability
    for col, width in zip('ABCDEFGHIJKLMNOPQRSTUVWX', [10, 25, 15, 15, 8, 8, 15, 8, 8, 15, 8, 8, 15, 12, 12, 15, 10, 12, 12, 15, 10, 10, 12, 20]):
        ws.column_dimensions[col].width = width

    wb.save(output_path)
    return output_path


def create_student_import_template(output_path):
    """
    Create a student bulk import Excel template
    
    Args:
        output_path: Where to save the template
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Student Import"
    
    # Header styling
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=12)
    
    # Headers
    headers = ["Student Number", "First Name", "Last Name", "Middle Name", "Class", "Study Area"]
    
    for idx, header in enumerate(headers):
        cell = ws.cell(row=1, column=idx+1, value=header)
        cell.font = header_font
        cell.fill = header_fill
    
    # Sample data
    sample_data = [
        ["STU001", "John", "Doe", "Michael", "Form 1", "Home Economics A"],
        ["STU002", "Jane", "Smith", "", "Form 2", "General Arts 4B"],
        ["STU003", "Bob", "Johnson", "William", "Form 3", "Business A"]
    ]
    
    for row_idx, row_data in enumerate(sample_data, start=2):
        for col_idx, value in enumerate(row_data):
            ws.cell(row=row_idx, column=col_idx+1, value=value)
    
    # Set column widths
    column_widths = [15, 15, 15, 15, 10, 15]
    for idx, width in enumerate(column_widths):
        ws.column_dimensions[chr(65 + idx)].width = width
    
    wb.save(output_path)
    return output_path


def create_teacher_import_template(output_path):
    """
    Create a teacher bulk import Excel template
    
    Args:
        output_path: Where to save the template
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Teacher Import"

    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=12)

    headers = ["Username", "Password", "Role", "Subject", "Classes"]
    for idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=idx, value=header)
        cell.font = header_font
        cell.fill = header_fill

    sample_data = [
        ["teacher1", "Teacher@123", "teacher", "Mathematics", "Form 1"],
        ["teacher2", "Teacher@123", "teacher", "English Language", "Form 2"],
        ["admin1", "Admin@123", "admin", "", ""]
    ]

    for row_idx, row_data in enumerate(sample_data, start=2):
        for col_idx, value in enumerate(row_data, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)

    for idx, width in enumerate([20, 20, 15, 20, 25], start=1):
        ws.column_dimensions[chr(64 + idx)].width = width

    wb.save(output_path)
    return output_path


def create_question_import_template(output_path):
    """
    Create Excel template for bulk question import
    
    Args:
        output_path: Where to save the template
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Question Import"
    
    # Header styling
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=12)
    
    # Headers
    headers = ["Question Text", "Question Type", "Option A", "Option B", "Option C", "Option D", "Correct Answer", "Difficulty", "Explanation"]
    
    for idx, header in enumerate(headers):
        cell = ws.cell(row=1, column=idx+1, value=header)
        cell.font = header_font
        cell.fill = header_fill
    
    # Sample data
    sample_data = [
        ["What is the capital of France?", "mcq", "Paris", "London", "Berlin", "Madrid", "A", "easy", "Paris is the capital and largest city of France."],
        ["The Earth is round.", "true_false", "", "", "", "", "True", "easy", "Scientific evidence confirms the Earth is an oblate spheroid."],
        ["What is 2 + 2?", "short_answer", "", "", "", "", "4", "easy", "Basic arithmetic: 2 + 2 = 4."]
    ]
    
    for row_idx, row_data in enumerate(sample_data, start=2):
        for col_idx, value in enumerate(row_data):
            ws.cell(row=row_idx, column=col_idx+1, value=value)
    
    # Set column widths
    column_widths = [40, 15, 15, 15, 15, 15, 15, 10, 30]
    for idx, width in enumerate(column_widths):
        ws.column_dimensions[chr(65 + idx)].width = width
    
    wb.save(output_path)
    return output_path