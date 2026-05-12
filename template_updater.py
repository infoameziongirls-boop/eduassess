"""
template_updater.py
────────────────────────────────────────────────────────────────────────
Single source of truth for ALL Excel exports in EduAssess.
Every export — single student, class list, full school, raw assessments
— uses the school's customised student_template.xlsx so the live Excel
formulas in the coloured cells are always preserved.

Cell map (A.M.E. ZION layout)
──────────────────────────────
Header block
  B2  Subject
  B3  Term / Year
  B4  Form (class name)
  C7  =COUNTA(B10:B110)  ← live formula, never touched

Per-student rows starting at row 10
  A   Serial number (1, 2, 3 …)
  B   Name of Students
  C   Reference Number
  D   Learning Area
  E   ICA1   ← input
  F   ICA2   ← input
  G   =MIN(100,(SUM(E:F)))          ← FORMULA – never overwritten
  H   ICP1   ← input
  I   ICP2   ← input
  J   =MIN(100,(SUM(H:I)))          ← FORMULA
  K   GP1    ← input
  L   GP2    ← input
  M   =MIN(100,(SUM(K:L)))          ← FORMULA
  N   Practical Portfolio  ← input
  O   Mid-Semester Exam    ← input
  P   =MIN(500,(SUM(G,J,M,N,O)))    ← FORMULA
  Q   =P/500*100                    ← FORMULA
  R   =MIN(50,(ROUNDUP(Q/2,0)))     ← FORMULA
  S   End of Term Exam     ← input
  T   =MIN(50,(ROUNDUP(S/2,0)))     ← FORMULA
  U   =MIN(100,(SUM(R,T)))          ← FORMULA  (Total 50+50)
  V   =(U/100)                      ← FORMULA  (%)
  W   GPA formula                   ← FORMULA
  X   Grade formula                 ← FORMULA

Export types supported
──────────────────────
  add_student(row, dict)
      Single student on the active sheet.

  add_students_batch(list, per_sheet=False)
      per_sheet=False → all students on active sheet (one class/subject).
      per_sheet=True  → auto-groups by (sheet_subject, sheet_class) and
                        creates one worksheet per group inside the same
                        workbook, each a copy of the template sheet.

  export_by_subject_class(students_list, settings, ...)
      Preferred admin export: one sheet per (subject, class) combination,
      each student's scores scoped to that subject.

  export_assessments_raw(assessments, output_path, settings)
      Replaces the bare Workbook() call in export_assessments_excel().
      Groups Assessment rows by (subject, class_name), one sheet each.
"""

import math
import os
import re
import shutil
import tempfile

from openpyxl import load_workbook

# ─────────────────────────────────────────────────────────────────────
# Constants  (mirror config.py — single source of truth)
# ─────────────────────────────────────────────────────────────────────
CATEGORY_MAX = {
    'ica1': 50,  'ica2': 50,
    'icp1': 50,  'icp2': 50,
    'gp1':  50,  'gp2':  50,
    'practical': 100,
    'mid_term':  100,
    'end_term':  100,
}

CATEGORY_LABELS = {
    'ica1':      'Individual Assessment 1',
    'ica2':      'Individual Assessment 2',
    'icp1':      'Individual Class Project 1',
    'icp2':      'Individual Class Project 2',
    'gp1':       'Group Project/Research 1',
    'gp2':       'Group Project/Research 2',
    'practical': 'Practical Portfolio',
    'mid_term':  'Mid-Semester Exam',
    'end_term':  'End of Term Exam',
}

# Columns that hold FORMULA results — must NEVER be overwritten
_FORMULA_COLS = {'G', 'J', 'M', 'P', 'Q', 'R', 'T', 'U', 'V', 'W', 'X'}

# Category → column number (1-based) for input cells
_CAT_TO_COL = {
    'ica1': 5,   'ica2': 6,
    'icp1': 8,   'icp2': 9,
    'gp1':  11,  'gp2':  12,
    'practical': 14,
    'mid_term':  15,
    'end_term':  19,
}

STUDENT_START_ROW = 10


# ─────────────────────────────────────────────────────────────────────
# GPA / grade lookup  (mirrors the W / X formula in the template)
# ─────────────────────────────────────────────────────────────────────
_GPA_TABLE = [
    (80, '4.0', 'A1'),
    (70, '3.5', 'B2'),
    (65, '3.0', 'B3'),
    (60, '2.5', 'C4'),
    (55, '2.0', 'C5'),
    (50, '1.5', 'C6'),
    (45, '1.0', 'D7'),
    (40, '0.5', 'E8'),
    (0,  '0.0', 'F9'),
]


# ─────────────────────────────────────────────────────────────────────
# Public helpers  (imported by models.py and app.py)
# ─────────────────────────────────────────────────────────────────────

def scores_from_assessments(assessments: list) -> dict:
    """
    Collapse Assessment ORM rows → {category_key: best_score}.
    One value per category; highest score wins when duplicates exist.
    """
    result: dict = {}
    for a in assessments:
        cat = a.category
        if cat not in CATEGORY_MAX:
            continue
        score = float(a.score) if a.score is not None else 0.0
        if cat not in result or score > result[cat]:
            result[cat] = score
    return result


def calculate_scores_from_template(raw_scores: dict) -> dict:
    """
    Python mirror of the Excel formula chain.  Returns every key that
    models.Student.get_overall_summary() needs:

        ica_total, icp_total, gp_total,
        total_class_score, pct_100, avg_class_score,
        avg_exam_score, final_score, percentage, gpa, grade
    """
    def _v(k):
        return float(raw_scores.get(k) or 0)

    ica1 = _v('ica1');  ica2 = _v('ica2')
    icp1 = _v('icp1');  icp2 = _v('icp2')
    gp1  = _v('gp1');   gp2  = _v('gp2')
    practical = _v('practical')
    mid_term  = _v('mid_term')
    end_term  = _v('end_term')

    ica_total         = min(100.0, ica1 + ica2)            # col G
    icp_total         = min(100.0, icp1 + icp2)            # col J
    gp_total          = min(100.0, gp1  + gp2)             # col M
    total_class_score = min(500.0, ica_total + icp_total   # col P
                                   + gp_total + practical + mid_term)
    pct_100           = (total_class_score / 500.0) * 100  # col Q
    avg_class_score   = float(min(50.0, math.ceil(pct_100 / 2)))  # col R
    avg_exam_score    = float(min(50.0, math.ceil(end_term / 2))) # col T
    final_score       = float(min(100.0, avg_class_score + avg_exam_score))  # col U
    percentage        = float(final_score)                        # col V (×100)

    gpa = 0.0;  grade = 'F9'
    for threshold, gpa_val, grade_val in _GPA_TABLE:
        if final_score >= threshold:
            gpa   = float(gpa_val)
            grade = grade_val
            break

    return {
        'ica_total':         ica_total,
        'icp_total':         icp_total,
        'gp_total':          gp_total,
        'total_class_score': total_class_score,
        'pct_100':           pct_100,
        'avg_class_score':   avg_class_score,
        'avg_exam_score':    avg_exam_score,
        'final_score':       final_score,
        'percentage':        percentage,
        'gpa':               gpa,
        'grade':             grade,
    }


def _grade(final_score: float):
    """Return the GPA and grade label for a final score."""
    for threshold, gpa_val, grade_val in _GPA_TABLE:
        if final_score >= threshold:
            return {'gpa': float(gpa_val), 'grade': grade_val}
    return {'gpa': 0.0, 'grade': 'F9'}


# ─────────────────────────────────────────────────────────────────────
# Core exporter
# ─────────────────────────────────────────────────────────────────────

class AssessmentTemplateUpdater:
    """
    Loads the school's student_template.xlsx and populates it with data,
    preserving ALL live Excel formulas in the coloured columns.
    """

    def __init__(self, template_path: str):
        self.template_path = template_path
        self.wb   = None
        self._tmp = None

    # ── lifecycle ────────────────────────────────────────────────────

    def load_template(self):
        if not os.path.exists(self.template_path):
            raise FileNotFoundError(
                f"School template not found: {self.template_path}\n"
                "Place student_template.xlsx inside the templates_excel folder."
            )
        fd, self._tmp = tempfile.mkstemp(suffix='.xlsx')
        os.close(fd)
        shutil.copy2(self.template_path, self._tmp)
        self.wb = load_workbook(self._tmp)   # formulas kept as strings
        return self.wb

    def save_workbook(self, output_path: str) -> str:
        if self.wb is None:
            raise RuntimeError("Call load_template() before save_workbook().")
        dirpart = os.path.dirname(output_path)
        if dirpart:
            os.makedirs(dirpart, exist_ok=True)
        self.wb.save(output_path)
        self._cleanup()
        return output_path

    def _cleanup(self):
        if self._tmp and os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except OSError:
                pass

    # ── header ───────────────────────────────────────────────────────

    def update_school_info(self, subject=None, term_year=None, form=None,
                           worksheet=None):
        """Write B2/B3/B4 on one or all sheets."""
        sheets = [worksheet] if worksheet else self.wb.worksheets
        for ws in sheets:
            if subject:
                ws['B2'] = _humanise(subject)
            if term_year:
                ws['B3'] = term_year
            if form:
                ws['B4'] = form

    # ── single student ───────────────────────────────────────────────

    def add_student(self, row: int, student_dict: dict):
        """Write one student dict into `row` on the active sheet."""
        ws = self.wb.active
        self._ensure_formulas(ws, row)
        self._write_row(ws, row, student_dict)

    # ── batch (same sheet) ───────────────────────────────────────────

    def add_students_batch(self, students: list, per_sheet: bool = False):
        """
        Write a list of student dicts.

        per_sheet=False  All students on the active sheet (row 10 onwards).
        per_sheet=True   Group by (sheet_subject, sheet_class); one sheet each.
        """
        if self.wb is None:
            raise RuntimeError("Call load_template() first.")

        if not per_sheet:
            ws = self.wb.active
            for i, sd in enumerate(students):
                row = STUDENT_START_ROW + i
                self._ensure_formulas(ws, row)
                self._write_row(ws, row, sd)
            return

        groups: dict = {}
        for sd in students:
            key = (sd.get('sheet_subject', ''), sd.get('sheet_class', ''))
            groups.setdefault(key, []).append(sd)

        first = True
        for (subj, cls), group in groups.items():
            ws = self.wb.active if first else self._copy_sheet(subj, cls)
            first = False
            if subj:
                ws['B2'] = _humanise(subj)
            if cls:
                ws['B4'] = cls
            for i, sd in enumerate(group):
                row = STUDENT_START_ROW + i
                self._ensure_formulas(ws, row)
                self._write_row(ws, row, sd)

    # ── admin "all students" export  ──────────────────────────────────

    def export_by_subject_class(self, students_list: list, settings=None,
                                subject_filter=None, class_filter=None):
        """
        Best export for admin: one sheet per (subject, class) combination.
        Each student's scores are fetched via Student.to_template_dict(subject)
        so they are correctly scoped.

        Called like:
            upd = AssessmentTemplateUpdater(tpl_path)
            upd.load_template()
            upd.export_by_subject_class(students_list, settings=settings,
                                        subject_filter=subject,
                                        class_filter=class_name)
            upd.save_workbook(out_path)
        """
        if self.wb is None:
            raise RuntimeError("Call load_template() first.")

        term_year = (f"{settings.current_term} {settings.current_academic_year}"
                     if settings else '')

        # Build groups: (subject, class) → [(student, subject)]
        groups: dict = {}
        for student in students_list:
            cls = student.class_name or ''
            if class_filter and cls != class_filter:
                continue

            if subject_filter:
                subjects = [subject_filter]
            else:
                subjects = sorted({a.subject for a in student.assessments
                                   if not a.archived} or [''])

            for subj in subjects:
                groups.setdefault((subj, cls), []).append((student, subj))

        if not groups:
            self.update_school_info(
                subject=subject_filter or 'All Subjects',
                term_year=term_year,
                form=class_filter or 'All Classes')
            return

        first = True
        for (subj, cls), pairs in sorted(groups.items()):
            ws = self.wb.active if first else self._copy_sheet(subj, cls)
            first = False
            ws['B2'] = _humanise(subj) if subj else 'All Subjects'
            if term_year:
                ws['B3'] = term_year
            ws['B4'] = cls or 'All Classes'

            for i, (student, s) in enumerate(pairs):
                row = STUDENT_START_ROW + i
                self._ensure_formulas(ws, row)
                sd = student.to_template_dict(s or None)
                self._write_row(ws, row, sd)

    # ── raw assessments export  ───────────────────────────────────────

    def export_assessments_raw(self, assessments: list, output_path: str,
                               settings=None) -> str:
        """
        Replaces the bare Workbook() used in export_assessments_excel().
        Groups Assessment ORM rows by (subject, class_name), one template
        sheet per group, student scores in the correct input columns.
        """
        if self.wb is None:
            raise RuntimeError("Call load_template() first.")

        term_year = (f"{settings.current_term} {settings.current_academic_year}"
                     if settings else '')

        groups: dict = {}
        student_meta: dict = {}
        for a in assessments:
            key = (a.subject or '', a.class_name or '')
            groups.setdefault(key, {})
            sid = a.student_id
            groups[key].setdefault(sid, {})
            if a.category in CATEGORY_MAX:
                prev = groups[key][sid].get(a.category, -1)
                if float(a.score) > prev:
                    groups[key][sid][a.category] = float(a.score)
            if sid not in student_meta and a.student:
                st = a.student
                student_meta[sid] = {
                    'name':       st.full_name(),
                    'ref_id':     st.reference_number or '',
                    'study_area': (st.get_study_area_display()
                                   if hasattr(st, 'get_study_area_display')
                                   else (st.study_area or '')),
                }

        if not groups:
            if term_year:
                self.update_school_info(term_year=term_year)
            return self.save_workbook(output_path)

        first = True
        for (subj, cls), stu_scores in sorted(groups.items()):
            ws = self.wb.active if first else self._copy_sheet(subj, cls)
            first = False
            ws['B2'] = _humanise(subj) if subj else 'All Subjects'
            if term_year:
                ws['B3'] = term_year
            ws['B4'] = cls or 'All Classes'

            sorted_sids = sorted(stu_scores,
                                 key=lambda s: student_meta.get(s, {}).get('name', ''))
            for i, sid in enumerate(sorted_sids):
                row = STUDENT_START_ROW + i
                self._ensure_formulas(ws, row)
                meta = student_meta.get(sid, {})
                sd = {
                    'name':       meta.get('name', ''),
                    'ref_id':     meta.get('ref_id', ''),
                    'study_area': meta.get('study_area', ''),
                    **{cat: stu_scores[sid].get(cat, 0) for cat in CATEGORY_MAX},
                }
                self._write_row(ws, row, sd)

        return self.save_workbook(output_path)

    # ── internals ────────────────────────────────────────────────────

    def _write_row(self, ws, row: int, sd: dict):
        """
        Write one student dict to `row`.
        Formula columns are NEVER touched.
        """
        serial = row - STUDENT_START_ROW + 1
        ws.cell(row=row, column=1, value=serial)
        ws.cell(row=row, column=2, value=sd.get('name', ''))
        ws.cell(row=row, column=3, value=sd.get('ref_id', ''))
        ws.cell(row=row, column=4, value=sd.get('study_area', ''))
        for cat, col in _CAT_TO_COL.items():
            raw = sd.get(cat, 0)
            ws.cell(row=row, column=col,
                    value=float(raw) if raw not in (None, '') else 0.0)

    def _ensure_formulas(self, ws, row: int):
        """
        Copy the row-10 formula pattern down to `row`, adjusting references,
        if the target cells are still blank.
        """
        if row <= STUDENT_START_ROW:
            return
        for col in _FORMULA_COLS:
            src = ws[f'{col}{STUDENT_START_ROW}']
            tgt = ws[f'{col}{row}']
            if (src.value and str(src.value).startswith('=')
                    and not (tgt.value and str(tgt.value).startswith('='))):
                tgt.value = _shift_formula(str(src.value),
                                           STUDENT_START_ROW, row)

    def _copy_sheet(self, subject: str, class_name: str):
        """Duplicate the first (template) sheet and return the copy."""
        label = _safe_sheet_name(
            f"{_humanise(subject)} – {class_name}" if class_name
            else _humanise(subject) or 'Sheet'
        )
        return self.wb.copy_worksheet(self.wb.worksheets[0])


# ─────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────

def _humanise(key: str) -> str:
    return key.replace('_', ' ').title() if key else ''


def _safe_sheet_name(name: str) -> str:
    for ch in r'/\?*[]:\'':
        name = name.replace(ch, '-')
    return name[:31]


def _shift_formula(formula: str, from_row: int, to_row: int) -> str:
    """Replace A1-style row references: =SUM(E10:F10) → =SUM(E15:F15)."""
    pattern = re.compile(r'([A-Z]+)' + str(from_row) + r'(?!\d)')
    return pattern.sub(lambda m: m.group(1) + str(to_row), formula)
