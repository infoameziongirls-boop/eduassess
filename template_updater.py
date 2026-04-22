"""
template_updater.py  –  EduAssess Excel Template Engine
========================================================
Provides score-calculation helpers used by the Student model and the
Excel-export routes.

Formula chain (mirrors the school's Excel template):
  ICA total  = ica1 + ica2              (max 100 raw -> normalised to 50)
  ICP total  = icp1 + icp2              (max 100 raw -> normalised to 50)
  GP  total  = gp1  + gp2               (max 100 raw -> normalised to 50)
  Total class score = ICA_t + ICP_t + GP_t + practical + mid_term
                    (contributions are scaled so the sum is /500)
  avg_class_score  = ROUNDUP(total_class / 500 * 100 / 2, 0)   -> max 50
  avg_exam_score   = ROUNDUP(end_term / 2, 0)                   -> max 50
  final_score      = MIN(100, avg_class_score + avg_exam_score)

GPA / Grade thresholds (WAEC SHS Ghana):
  >=80 -> A1 / 4.0
  >=70 -> B2 / 3.5
  >=65 -> B3 / 3.0
  >=60 -> C4 / 2.5
  >=55 -> C5 / 2.0
  >=50 -> C6 / 1.5
  >=45 -> D7 / 1.0
  >=40 -> E8 / 0.5
    <40 -> F9 / 0.0
"""

import math
from openpyxl import load_workbook, Workbook
from openpyxl.styles import PatternFill, Border, Side, Alignment, Font
from openpyxl.utils import get_column_letter

# Maximum raw score for each assessment category
CATEGORY_MAX = {
    "ica1":      50,
    "ica2":      50,
    "icp1":      50,
    "icp2":      50,
    "gp1":       50,
    "gp2":       50,
    "practical": 100,
    "mid_term":  100,
    "end_term":  100,
}


def _roundup(value, decimals=0):
    """ROUNDUP equivalent (always rounds away from zero)."""
    factor = 10 ** decimals
    return math.ceil(value * factor) / factor


def scores_from_assessments(assessments):
    """
    Collapse a list of Assessment objects into a single dict of raw scores.
    If the same category appears more than once, the most recently recorded
    score wins.
    """
    raw: dict = {}
    for a in sorted(assessments, key=lambda x: x.date_recorded):
        cat = a.category
        if cat in CATEGORY_MAX:
            raw[cat] = min(float(a.score), float(CATEGORY_MAX[cat]))
    return raw


def calculate_scores_from_template(raw_scores: dict) -> dict:
    """
    Apply the Excel formula chain and return a dict containing every
    intermediate and final value.
    """
    g = raw_scores.get

    ica1      = min(float(g("ica1",      0)), 50)
    ica2      = min(float(g("ica2",      0)), 50)
    icp1      = min(float(g("icp1",      0)), 50)
    icp2      = min(float(g("icp2",      0)), 50)
    gp1       = min(float(g("gp1",       0)), 50)
    gp2       = min(float(g("gp2",       0)), 50)
    practical = min(float(g("practical", 0)), 100)
    mid_term  = min(float(g("mid_term",  0)), 100)
    end_term  = min(float(g("end_term",  0)), 100)

    ica_total  = ica1  + ica2
    icp_total  = icp1  + icp2
    gp_total   = gp1   + gp2

    total_class_score = ica_total + icp_total + gp_total + practical + mid_term

    pct_100         = (total_class_score / 500.0) * 100.0
    avg_class_score = min(50.0, _roundup(pct_100 / 2.0, 0))
    avg_exam_score  = min(50.0, _roundup(end_term / 2.0, 0))

    final_score = min(100.0, avg_class_score + avg_exam_score)
    percentage  = final_score

    gpa, grade = _grade(final_score)

    return {
        "ica_total":         ica_total,
        "icp_total":         icp_total,
        "gp_total":          gp_total,
        "total_class_score": total_class_score,
        "pct_100":           round(pct_100, 2),
        "avg_class_score":   avg_class_score,
        "avg_exam_score":    avg_exam_score,
        "final_score":       round(final_score, 2),
        "percentage":        round(percentage, 2),
        "gpa":               gpa,
        "grade":             grade,
    }


def _grade(score: float):
    """Return (gpa, grade_letter) for a given final score."""
    if score >= 80:  return 4.0, "A1"
    if score >= 70:  return 3.5, "B2"
    if score >= 65:  return 3.0, "B3"
    if score >= 60:  return 2.5, "C4"
    if score >= 55:  return 2.0, "C5"
    if score >= 50:  return 1.5, "C6"
    if score >= 45:  return 1.0, "D7"
    if score >= 40:  return 0.5, "E8"
    return 0.0, "F9"


class AssessmentTemplateUpdater:
    """Fills in an openpyxl workbook from student assessment data."""

    COL_NAME      = 2
    COL_REF       = 3
    COL_AREA      = 4
    COL_ICA1      = 5
    COL_ICA2      = 6
    COL_ICP1      = 7
    COL_ICP2      = 8
    COL_GP1       = 9
    COL_GP2       = 10
    COL_PRACTICAL = 11
    COL_MID_TERM  = 12
    COL_END_TERM  = 13

    def __init__(self, template_path: str):
        self.template_path = template_path
        self.wb = None
        self.ws = None

    def load_template(self):
        if not self.template_path:
            raise FileNotFoundError("Template path not specified.")
        self.wb = load_workbook(self.template_path)
        self.ws = self.wb.active

    def update_school_info(self, subject="", term_year="", form=""):
        if not self.ws:
            raise RuntimeError("Call load_template() first.")
        try:
            self.ws["B2"] = subject
            self.ws["B3"] = form
            self.ws["B4"] = term_year
        except Exception:
            pass

    def add_student(self, start_row: int, student_data: dict):
        if not self.ws:
            raise RuntimeError("Call load_template() first.")
        self._write_student_row(start_row, student_data)

    def add_students_batch(self, students_data: list, start_row: int = 10):
        if not self.ws:
            raise RuntimeError("Call load_template() first.")
        for i, data in enumerate(students_data):
            self._write_student_row(start_row + i, data)

    def _write_student_row(self, row: int, data: dict):
        ws = self.ws
        ws.cell(row=row, column=self.COL_NAME,      value=data.get("name",      ""))
        ws.cell(row=row, column=self.COL_REF,       value=data.get("ref_id",    ""))
        ws.cell(row=row, column=self.COL_AREA,      value=data.get("study_area",""))
        ws.cell(row=row, column=self.COL_ICA1,      value=data.get("ica1",       0))
        ws.cell(row=row, column=self.COL_ICA2,      value=data.get("ica2",       0))
        ws.cell(row=row, column=self.COL_ICP1,      value=data.get("icp1",       0))
        ws.cell(row=row, column=self.COL_ICP2,      value=data.get("icp2",       0))
        ws.cell(row=row, column=self.COL_GP1,       value=data.get("gp1",        0))
        ws.cell(row=row, column=self.COL_GP2,       value=data.get("gp2",        0))
        ws.cell(row=row, column=self.COL_PRACTICAL, value=data.get("practical",  0))
        ws.cell(row=row, column=self.COL_MID_TERM,  value=data.get("mid_term",   0))
        ws.cell(row=row, column=self.COL_END_TERM,  value=data.get("end_term",   0))

    def save_workbook(self, output_path: str):
        if not self.wb:
            raise RuntimeError("No workbook loaded.")
        self.wb.save(output_path)
