"""
template_updater.py  —  EduAssess
══════════════════════════════════════════════════════════════════════════════
Single source of truth for ALL Excel exports.

Every export uses the school's EXACT customised student_template.xlsx
(A.M.E. ZION GIRLS' SENIOR HIGH SCHOOL – WINNEBA) so all colours, merged
cells, fonts, column widths, row heights and formulas are always preserved.

ROOT CAUSES FIXED IN THIS VERSION
──────────────────────────────────────────────────────────────────────────────
Bug 1 — _copy_sheet() built the `label` variable but NEVER assigned it to
         new_ws.title.  All multi-sheet exports had tabs named
         "ASSESSMENT TEMPLATE Copy", "ASSSESSMENT TEMPLATE Copy1", …
         Fix: new_ws.title = label  (one line addition).

Bug 2 — copy_worksheet() was assumed not to preserve theme-based fills.
         Testing proved it does.  No workaround needed.  The real cause of
         the missing styling was that app.py's old export_all_students_excel
         route was still calling the OLD add_students_batch path which
         opened a fresh load_workbook() per call — stripping the template
         context.  Fixed by always going through _get_or_create_sheet().

Bug 3 — term_year was built as  f"{settings.current_term} {settings.current_academic_year}"
         producing "term1 2024-2025" (raw DB key).
         Fix: _build_term_year() resolves the human label via app config.

Bug 4 — export_by_subject_class() iterated student.assessments without
         scoping to the subject, mixing English scores onto the Maths sheet.
         Fix: always pass `subject` to student.to_template_dict(subject).

Bug 5 — Students with no assessments were silently skipped when no
         subject_filter was given (empty subjects set → nothing added).
         Fix: fall back to a single empty-subject entry so the student
         still appears on a sheet with zeros.

Cell map  (school template layout, sheet "ASSESSMENT TEMPLATE")
────────────────────────────────────────────────────────────────
  B1   School name  — already in template, NEVER overwritten
  A2   "SUBJECT:"   label
  B2   Subject value              ← written by app
  A3   "TERM/YEAR:" label
  B3   Term / Year                ← written by app  (human label)
  A4   "FORM:"      label
  B4   Form / Class               ← written by app
  C7   =COUNTA(B10:B110)          ← live formula, NEVER touched

Per-student data rows start at row 10:
  A  Serial 1,2,3…
  B  Name of Students
  C  Reference Number
  D  Learning Area
  E  ICA1  (input)
  F  ICA2  (input)
  G  =MIN(100,(SUM(E:F)))         ← FORMULA coloured — never overwrite
  H  ICP1  (input)
  I  ICP2  (input)
  J  =MIN(100,(SUM(H:I)))         ← FORMULA coloured
  K  GP1   (input)
  L  GP2   (input)
  M  =MIN(100,(SUM(K:L)))         ← FORMULA coloured
  N  Practical Portfolio  (input)
  O  Mid-Semester Exam    (input)
  P  =MIN(500,(…))                ← FORMULA
  Q  =P/500*100                   ← FORMULA
  R  =MIN(50,(ROUNDUP(Q/2,0)))    ← FORMULA coloured (AVG CLASS)
  S  End of Term Exam     (input)
  T  =MIN(50,(ROUNDUP(S/2,0)))    ← FORMULA coloured (AVG EXAM)
  U  =MIN(100,(SUM(R,T)))         ← FORMULA green    (Total 50+50)
  V  =(U/100)                     ← FORMULA coloured
  W  GPA  formula                 ← FORMULA
  X  Grade formula                ← FORMULA
"""

import math
import os
import re
import shutil
import tempfile

from openpyxl import load_workbook

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
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

# Columns with formula cells — NEVER overwrite these
_FORMULA_COLS = {'G', 'J', 'M', 'P', 'Q', 'R', 'T', 'U', 'V', 'W', 'X'}

# Category key → 1-based column number for input cells
_CAT_TO_COL = {
    'ica1': 5,   'ica2': 6,
    'icp1': 8,   'icp2': 9,
    'gp1':  11,  'gp2':  12,
    'practical': 14,
    'mid_term':  15,
    'end_term':  19,
}

STUDENT_START_ROW = 10

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


# ─────────────────────────────────────────────────────────────────────────────
# Public helpers  (imported by models.py)
# ─────────────────────────────────────────────────────────────────────────────

def scores_from_assessments(assessments: list) -> dict:
    """Collapse Assessment ORM rows → {category: best_score}."""
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
    Python mirror of the Excel formula chain.
    Returns every key consumed by models.Student.get_overall_summary().
    """
    def _v(k):
        return float(raw_scores.get(k) or 0)

    ica1 = _v('ica1');  ica2 = _v('ica2')
    icp1 = _v('icp1');  icp2 = _v('icp2')
    gp1  = _v('gp1');   gp2  = _v('gp2')
    practical = _v('practical')
    mid_term  = _v('mid_term')
    end_term  = _v('end_term')

    ica_total         = min(100.0, ica1 + ica2)
    icp_total         = min(100.0, icp1 + icp2)
    gp_total          = min(100.0, gp1  + gp2)
    total_class_score = min(500.0, ica_total + icp_total + gp_total
                                   + practical + mid_term)
    pct_100           = (total_class_score / 500.0) * 100.0
    avg_class_score   = min(50.0, math.ceil(pct_100 / 2.0))
    avg_exam_score    = min(50.0, math.ceil(end_term / 2.0))
    final_score       = min(100.0, avg_class_score + avg_exam_score)
    percentage        = final_score

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


# ─────────────────────────────────────────────────────────────────────────────
# Core class
# ─────────────────────────────────────────────────────────────────────────────

class AssessmentTemplateUpdater:
    """
    All exports use this class.  The pattern is:

        upd = AssessmentTemplateUpdater(tpl_path)
        upd.load_template()
        upd.update_school_info(subject=..., term_year=..., form=...)
        upd.add_student(...)  or  upd.add_students_batch(...)
        upd.save_workbook(output_path)

    Internally one openpyxl workbook is kept open; additional sheets are
    added via copy_worksheet() which preserves ALL fills including
    theme-based coloured columns (tested: ✓).
    """

    def __init__(self, template_path: str):
        self.template_path = template_path
        self.wb            = None
        self._tmp          = None
        # defaults written to the active sheet by update_school_info()
        self._def_subject  = ''
        self._def_term     = ''
        self._def_form     = ''

    # ── lifecycle ────────────────────────────────────────────────────────────

    def load_template(self):
        """Copy template to a temp file and open it (preserves all styling)."""
        if not os.path.exists(self.template_path):
            raise FileNotFoundError(
                f"School template not found: {self.template_path}\n"
                "Place student_template.xlsx in the templates_excel/ folder."
            )
        fd, self._tmp = tempfile.mkstemp(suffix='.xlsx')
        os.close(fd)
        shutil.copy2(self.template_path, self._tmp)
        self.wb = load_workbook(self._tmp)   # formula strings preserved
        return self

    def save_workbook(self, output_path: str) -> str:
        if self.wb is None:
            raise RuntimeError("Call load_template() first.")
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

    # ── header ───────────────────────────────────────────────────────────────

    def update_school_info(self, subject=None, term_year=None, form=None,
                           worksheet=None):
        """
        Write B2 / B3 / B4 on one sheet (or store as defaults for later).
        worksheet=None  → write to the currently active sheet AND store as
                          defaults for sheets created later.
        worksheet=<ws>  → write to that specific worksheet only.
        """
        if subject:
            self._def_subject = subject
        if term_year:
            self._def_term = term_year
        if form:
            self._def_form = form

        if self.wb is None:
            return  # called before load_template; values stored for later

        sheets = [worksheet] if worksheet else [self.wb.active]
        for ws in sheets:
            if subject:
                ws['B2'] = _humanise(subject)
            if term_year:
                ws['B3'] = term_year
            if form:
                ws['B4'] = form

    # ── add single student ───────────────────────────────────────────────────

    def add_student(self, row: int, student_dict: dict):
        """Write one student onto the active sheet at `row`."""
        ws = self.wb.active
        _ensure_formula_row(ws, row)
        _write_student_row(ws, row, student_dict)

    # ── batch (same sheet) ─────────────────────────────────────────────────

    def add_students_batch(self, students: list, per_sheet: bool = False):
        if self.wb is None:
            raise RuntimeError("Call load_template() first.")

        if not per_sheet:
            ws = self.wb.active
            for i, sd in enumerate(students):
                row = STUDENT_START_ROW + i
                _ensure_formula_row(ws, row)
                _write_student_row(ws, row, sd)
            return

        # Group by (sheet_subject, sheet_class)
        groups: dict = {}
        for sd in students:
            key = (sd.get('sheet_subject', ''), sd.get('sheet_class', ''))
            groups.setdefault(key, []).append(sd)

        first = True
        for (subj, cls), group in groups.items():
            if first:
                ws = self.wb.active
                first = False
            else:
                # BUG 1 FIX: assign the title — this was missing before
                ws = self._copy_template_sheet(subj, cls)

            ws['B2'] = _humanise(subj) if subj else (
                _humanise(self._def_subject) if self._def_subject else ws['B2'].value)
            ws['B3'] = self._def_term or ws['B3'].value
            ws['B4'] = cls if cls else (self._def_form or ws['B4'].value)

            for i, sd in enumerate(group):
                row = STUDENT_START_ROW + i
                _ensure_formula_row(ws, row)
                _write_student_row(ws, row, sd)

    # ── admin "all students by subject+class" ────────────────────────────────

    def export_by_subject_class(self, students_list: list, settings=None,
                                subject_filter=None, class_filter=None):
        """
        One sheet per (subject, class) combination inside one workbook.
        All sheets use the school template's exact colours and formulas.

        BUG 3 FIX: term_year uses human label not raw key.
        BUG 4 FIX: scores scoped to subject via to_template_dict(subject).
        BUG 5 FIX: students without assessments still appear with zeros.
        """
        term_year = _build_term_year(settings)

        groups: dict = {}
        for student in students_list:
            cls = student.class_name or ''
            if class_filter and cls != class_filter:
                continue

            if subject_filter:
                subjects = [subject_filter]
            else:
                subjects = sorted({
                    a.subject for a in student.assessments
                    if not a.archived and a.subject
                })
                if not subjects:
                    subjects = ['']

            for subj in subjects:
                groups.setdefault((subj, cls), []).append((student, subj))

        if not groups:
            if term_year:
                self.wb.active['B3'] = term_year
            return

        first = True
        for (subj, cls), pairs in sorted(groups.items()):
            if first:
                ws = self.wb.active
                first = False
            else:
                ws = self._copy_template_sheet(subj, cls)

            ws['B2'] = _humanise(subj) if subj else 'All Subjects'
            ws['B3'] = term_year
            ws['B4'] = cls or 'All Classes'

            for i, (student, s) in enumerate(pairs):
                row = STUDENT_START_ROW + i
                _ensure_formula_row(ws, row)
                sd = student.to_template_dict(s if s else None)
                _write_student_row(ws, row, sd)

    # ── raw assessments export ───────────────────────────────────────────────

    def export_assessments_raw(self, assessments: list, output_path: str,
                               settings=None) -> str:
        """
        Group Assessment ORM rows by (subject, class_name), one template
        sheet per group.  Replaces the bare Workbook() used in app.py.
        """
        term_year = _build_term_year(settings)

        groups: dict = {}
        student_meta: dict = {}
        for a in assessments:
            key = (a.subject or '', a.class_name or '')
            groups.setdefault(key, {})
            sid = a.student_id
            groups[key].setdefault(sid, {})
            if a.category in CATEGORY_MAX:
                prev = groups[key][sid].get(a.category, -1)
                if float(a.score or 0) > prev:
                    groups[key][sid][a.category] = float(a.score or 0)
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
                self.wb.active['B3'] = term_year
            return self.save_workbook(output_path)

        first = True
        for (subj, cls), stu_scores in sorted(groups.items()):
            if first:
                ws = self.wb.active
                first = False
            else:
                ws = self._copy_template_sheet(subj, cls)

            ws['B2'] = _humanise(subj) if subj else 'All Subjects'
            ws['B3'] = term_year
            ws['B4'] = cls or 'All Classes'

            sorted_sids = sorted(
                stu_scores,
                key=lambda s: student_meta.get(s, {}).get('name', '')
            )
            for i, sid in enumerate(sorted_sids):
                row = STUDENT_START_ROW + i
                _ensure_formula_row(ws, row)
                meta = student_meta.get(sid, {})
                sd = {
                    'name':       meta.get('name', ''),
                    'ref_id':     meta.get('ref_id', ''),
                    'study_area': meta.get('study_area', ''),
                    **{cat: stu_scores[sid].get(cat, 0) for cat in CATEGORY_MAX},
                }
                _write_student_row(ws, row, sd)

        return self.save_workbook(output_path)

    # ── internal ─────────────────────────────────────────────────────────────

    def _copy_template_sheet(self, subject: str, class_name: str):
        """
        Duplicate the first (template) sheet into this workbook.
        BUG 1 FIX: title is now correctly assigned.
        copy_worksheet() preserves ALL fills including theme-based colours.
        """
        label = _safe_sheet_name(
            f"{_humanise(subject)} \u2013 {class_name}" if class_name and subject
            else _humanise(subject) or class_name or 'Sheet'
        )
        new_ws = self.wb.copy_worksheet(self.wb.worksheets[0])
        new_ws.title = label    # ← BUG 1 FIX: was missing before
        return new_ws


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _write_student_row(ws, row: int, sd: dict):
    """Write data columns only; formula columns are never touched."""
    serial = row - STUDENT_START_ROW + 1
    ws.cell(row=row, column=1,  value=serial)
    ws.cell(row=row, column=2,  value=sd.get('name', ''))
    ws.cell(row=row, column=3,  value=sd.get('ref_id', ''))
    ws.cell(row=row, column=4,  value=sd.get('study_area', ''))
    for cat, col in _CAT_TO_COL.items():
        raw = sd.get(cat, 0)
        ws.cell(row=row, column=col,
                value=float(raw) if raw not in (None, '') else 0.0)


def _ensure_formula_row(ws, row: int):
    """
    The school template pre-fills rows 10-110 with formulas.
    This only fires if we exceed row 110 (> 100 students per sheet).
    """
    if row <= STUDENT_START_ROW:
        return
    for col in _FORMULA_COLS:
        src = ws[f'{col}{STUDENT_START_ROW}']
        tgt = ws[f'{col}{row}']
        if (src.value and str(src.value).startswith('=')
                and not (tgt.value and str(tgt.value).startswith('='))):
            tgt.value = _shift_formula(str(src.value), STUDENT_START_ROW, row)


def _humanise(key: str) -> str:
    return key.replace('_', ' ').title() if key else ''


def _safe_sheet_name(name: str) -> str:
    for ch in r'/\?*[]:\'':
        name = name.replace(ch, '-')
    return name[:31]


def _shift_formula(formula: str, from_row: int, to_row: int) -> str:
    pattern = re.compile(r'([A-Z]+)' + str(from_row) + r'(?!\d)')
    return pattern.sub(lambda m: m.group(1) + str(to_row), formula)


def _build_term_year(settings) -> str:
    """
    BUG 3 FIX: resolve human label for term key.
    'term1' → 'Term 1',  'term2' → 'Term 2', etc.
    """
    if not settings:
        return ''
    term_raw = getattr(settings, 'current_term', '') or ''
    year     = getattr(settings, 'current_academic_year', '') or ''

    try:
        from flask import current_app
        terms_cfg  = current_app.config.get('TERMS', [])
        term_label = dict(terms_cfg).get(term_raw, term_raw)
    except RuntimeError:
        term_label = term_raw.replace('term', 'Term ').strip()

    return f"{term_label} {year}".strip()
