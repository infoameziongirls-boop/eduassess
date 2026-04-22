"""
Excel utility classes for EduAssess
"""
import os
import tempfile
import shutil
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill
from datetime import datetime


class ExcelTemplateHandler:
    def __init__(self, template_path):
        self.template_path = template_path

    def load_template(self):
        if not os.path.exists(self.template_path):
            raise FileNotFoundError(f"Template not found: {self.template_path}")
        temp_fd, temp_path = tempfile.mkstemp(suffix='.xlsx')
        os.close(temp_fd)
        shutil.copy2(self.template_path, temp_path)
        self.temp_path = temp_path
        return load_workbook(temp_path)

    def export_student_to_template(self, student, assessments, output_path, config):
        wb = self.load_template()
        ws = wb.active
        self._write_student_info(ws, student)
        self._write_assessments(ws, assessments, config)
        self._write_summary(ws, assessments, config)
        wb.save(output_path)
        return output_path

    def _write_student_info(self, ws, student):
        ws['B2'] = student.student_number
        ws['B3'] = student.full_name()
        ws['B4'] = student.study_area if student.study_area else ""
        ws['B5'] = datetime.now().strftime('%Y-%m-%d')

    def _write_assessments(self, ws, assessments, config):
        by_category = {}
        for assessment in assessments:
            if assessment.category not in by_category:
                by_category[assessment.category] = []
            by_category[assessment.category].append(assessment)

        category_rows = {
            "IA": 8, "IPA": 13, "PP": 18, "MSE": 23, "ETE": 28
        }
        for category, start_row in category_rows.items():
            if category in by_category:
                for idx, assessment in enumerate(by_category[category]):
                    row = start_row + idx
                    ws.cell(row=row, column=1, value=assessment.subject or "")
                    ws.cell(row=row, column=2, value=assessment.score)
                    ws.cell(row=row, column=3, value=assessment.max_score)
                    ws.cell(row=row, column=4, value=assessment.get_percentage())
                    ws.cell(row=row, column=5, value=assessment.term or "")

    def _write_summary(self, ws, assessments, config):
        from collections import defaultdict
        summary = defaultdict(lambda: {"total_score": 0, "total_max": 0, "count": 0})
        for assessment in assessments:
            cat = assessment.category
            summary[cat]["total_score"] += assessment.score
            summary[cat]["total_max"] += assessment.max_score
            summary[cat]["count"] += 1

        summary_row = 35
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


class ExcelBulkImporter:
    def __init__(self, file_path):
        self.file_path = file_path

    def import_assessments(self, start_row=2):
        wb = load_workbook(self.file_path, data_only=True)
        ws = wb.active
        assessments = []
        for row in ws.iter_rows(min_row=start_row, values_only=True):
            if not any(row):
                continue
            assessment_data = {
                'student_number': row[0],
                'category': row[1],
                'subject': row[2],
                'score': row[3],
                'max_score': row[4],
                'term': row[5],
                'session': row[6],
                'assessor': row[7],
                'comments': row[8] if len(row) > 8 else ""
            }
            if assessment_data['student_number'] and assessment_data['score'] is not None:
                assessments.append(assessment_data)
        wb.close()
        return assessments


class StudentBulkImporter:
    def __init__(self, file_path):
        self.file_path = file_path

    def import_students(self, start_row=2):
        wb = load_workbook(self.file_path, data_only=True)
        ws = wb.active
        students = []

        def normalize(value):
            if value is None:
                return None
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            return str(value).strip()

        for row in ws.iter_rows(min_row=start_row, values_only=True):
            if not any(row):
                continue
            student_data = {
                'student_number': normalize(row[0]) if len(row) > 0 else None,
                'first_name':     normalize(row[1]) if len(row) > 1 else None,
                'last_name':      normalize(row[2]) if len(row) > 2 else None,
                'middle_name':    normalize(row[3]) if len(row) > 3 else None,
                'class_name':     normalize(row[4]) if len(row) > 4 else None,
                'study_area':     normalize(row[5]) if len(row) > 5 else None,
            }
            if student_data['student_number'] and student_data['first_name'] and student_data['last_name']:
                students.append(student_data)
        wb.close()
        return students


class TeacherBulkImporter:
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
                'role':     normalize(row[2]) if len(row) > 2 else None,
                'subject':  normalize(row[3]) if len(row) > 3 else None,
                'classes':  normalize(row[4]) if len(row) > 4 else None,
            }
            if teacher_data['username']:
                teachers.append(teacher_data)
        wb.close()
        return teachers


class QuestionBulkImporter:
    def __init__(self, file_path):
        self.file_path = file_path

    def import_questions(self, start_row=2):
        wb = load_workbook(self.file_path, data_only=True)
        ws = wb.active
        questions = []
        for row in ws.iter_rows(min_row=start_row, values_only=True):
            if not any(row):
                continue
            question_data = {
                'question_text':  row[0],
                'question_type':  row[1],
                'option_a':       row[2] if len(row) > 2 else None,
                'option_b':       row[3] if len(row) > 3 else None,
                'option_c':       row[4] if len(row) > 4 else None,
                'option_d':       row[5] if len(row) > 5 else None,
                'correct_answer': row[6],
                'difficulty':     row[7] if len(row) > 7 else 'medium',
                'explanation':    row[8] if len(row) > 8 else None,
            }
            if question_data['question_text'] and question_data['question_type'] and question_data['correct_answer']:
                if question_data['question_type'].lower() == 'mcq':
                    question_data['options'] = [
                        question_data['option_a'], question_data['option_b'],
                        question_data['option_c'], question_data['option_d']
                    ]
                else:
                    question_data['options'] = None
                questions.append(question_data)
        wb.close()
        return questions


def create_default_template(output_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "ASSESSMENT TEMPLATE"

    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=12)

    ws['A1'] = "SCHOOL:"
    ws['A2'] = "SUBJECT:"
    ws['A3'] = "TERM/YEAR:"
    ws['A4'] = "FORM:"

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

    row = 10
    ws[f"G{row}"] = f"=MIN(100,(SUM(E{row}:F{row})))"
    ws[f"J{row}"] = f"=MIN(100,(SUM(H{row}:I{row})))"
    ws[f"M{row}"] = f"=MIN(100,(SUM(K{row}:L{row})))"
    ws[f"P{row}"] = f"=MIN(500,(SUM(G{row},J{row},M{row},N{row},O{row})))"
    ws[f"Q{row}"] = f"=P{row}/500*100"
    ws[f"R{row}"] = f"=MIN(50,(ROUNDUP(SUM(Q{row})/2,0)))"
    ws[f"T{row}"] = f"=MIN(50,(ROUNDUP(SUM(S{row})/2,0)))"
    ws[f"U{row}"] = f"=MIN(100,(SUM(R{row},T{row})))"
    ws[f"V{row}"] = f"=U{row}"
    ws[f"W{row}"] = (
        f'=IF(U{row}>=80,"4.0",IF(U{row}>=70,"3.5",IF(U{row}>=65,"3.0",'
        f'IF(U{row}>=60,"2.5",IF(U{row}>=55,"2.0",IF(U{row}>=50,"1.5",'
        f'IF(U{row}>=45,"1.0",IF(U{row}>=40,"0.5","0.0"))))))))'
    )
    ws[f"X{row}"] = (
        f'=IF(U{row}>=80,"A1",IF(U{row}>=70,"B2",IF(U{row}>=65,"B3",'
        f'IF(U{row}>=60,"C4",IF(U{row}>=55,"C5",IF(U{row}>=50,"C6",'
        f'IF(U{row}>=45,"D7",IF(U{row}>=40,"E8","F9"))))))))'
    )

    for col, width in zip(
        'ABCDEFGHIJKLMNOPQRSTUVWX',
        [10, 25, 15, 15, 8, 8, 15, 8, 8, 15, 8, 8, 15, 12, 12, 15, 10, 12, 12, 15, 10, 10, 12, 20]
    ):
        ws.column_dimensions[col].width = width

    os.makedirs(os.path.dirname(output_path), exist_ok=True) if os.path.dirname(output_path) else None
    wb.save(output_path)
    return output_path


def create_student_import_template(output_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Student Import"
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=12)
    headers = ["Student Number", "First Name", "Last Name", "Middle Name", "Class", "Study Area"]
    for idx, header in enumerate(headers):
        cell = ws.cell(row=1, column=idx+1, value=header)
        cell.font = header_font
        cell.fill = header_fill
    sample_data = [
        ["STU001", "John", "Doe", "Michael", "Form 1", "Home Economics A"],
        ["STU002", "Jane", "Smith", "", "Form 2", "General Arts 4B"],
        ["STU003", "Bob", "Johnson", "William", "Form 3", "Business A"]
    ]
    for row_idx, row_data in enumerate(sample_data, start=2):
        for col_idx, value in enumerate(row_data):
            ws.cell(row=row_idx, column=col_idx+1, value=value)
    for idx, width in enumerate([15, 15, 15, 15, 10, 20]):
        ws.column_dimensions[chr(65+idx)].width = width
    wb.save(output_path)
    return output_path


def create_teacher_import_template(output_path):
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
        ["admin1",   "Admin@123",   "admin",   "",               ""]
    ]
    for row_idx, row_data in enumerate(sample_data, start=2):
        for col_idx, value in enumerate(row_data, start=1):
            ws.cell(row=row_idx, column=col_idx, value=value)
    for idx, width in enumerate([20, 20, 15, 20, 25], start=1):
        ws.column_dimensions[chr(64+idx)].width = width
    wb.save(output_path)
    return output_path


def create_question_import_template(output_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Question Import"
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=12)
    headers = ["Question Text", "Question Type", "Option A", "Option B",
               "Option C", "Option D", "Correct Answer", "Difficulty", "Explanation"]
    for idx, header in enumerate(headers):
        cell = ws.cell(row=1, column=idx+1, value=header)
        cell.font = header_font
        cell.fill = header_fill
    sample_data = [
        ["What is the capital of France?", "mcq", "Paris", "London", "Berlin", "Madrid", "A", "easy", "Paris is the capital of France."],
        ["The Earth is round.", "true_false", "", "", "", "", "True", "easy", "Scientific fact."],
        ["What is 2 + 2?", "short_answer", "", "", "", "", "4", "easy", "Basic arithmetic."]
    ]
    for row_idx, row_data in enumerate(sample_data, start=2):
        for col_idx, value in enumerate(row_data):
            ws.cell(row=row_idx, column=col_idx+1, value=value)
    for idx, width in enumerate([40, 15, 15, 15, 15, 15, 15, 10, 30]):
        ws.column_dimensions[chr(65+idx)].width = width
    wb.save(output_path)
    return output_path
