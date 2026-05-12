"""
template_updater.py  —  EduAssess
══════════════════════════════════════════════════════════════════════════════
Single source of truth for ALL Excel exports.

Every export uses the school's EXACT customised student_template.xlsx
(A.M.E. ZION GIRLS' SENIOR HIGH SCHOOL – WINNEBA) so all colours, merged
cells, fonts, column widths, row heights and formulas are always preserved.

═══════════════════════════════════════════════════════════════════════════
VERIFIED TEMPLATE LAYOUT  (student_template.xlsx)
═══════════════════════════════════════════════════════════════════════════

Sheet name : student_template

Header cells:
  A1  SCHOOL: label         B1  School name (already in template)
  A2  SUBJECT: label        B2  Subject value          ← written by app
  A3  TERM/YEAR: label      B3  Term / Year             ← written by app
  A4  FORM: label           B4  Form / Class            ← written by app
  F7  =COUNTA(D10:D110)     (live student count — auto-updates when D fills)

Column headers are on row 9.  Student data rows begin at row 10.

Per-student columns (1-based):
  A (1)   Serial number
  B (2)   Student No.
  C (3)   Surname (last_name)
  D (4)   First Name
  E (5)   Other Name (middle_name)
  F (6)   Reference Number
  G (7)   Study Area / Learning Area
  H (8)   ica1  INPUT
  I (9)   ica2  INPUT
  J (10)  =MIN(100,(SUM(H:I)))                    FORMULA — never overwrite
  K (11)  icp1  INPUT
  L (12)  icp2  INPUT
  M (13)  =MIN(100,(SUM(K:L)))                    FORMULA — never overwrite
  N (14)  gp1   INPUT
  O (15)  gp2   INPUT
  P (16)  =MIN(100,(SUM(N:O)))                    FORMULA — never overwrite
  Q (17)  practical  INPUT
  R (18)  mid_term   INPUT
  S (19)  =MIN(500,(SUM(J,M,P,Q,R)))              FORMULA — never overwrite
  T (20)  =S/500*100                              FORMULA — never overwrite
  U (21)  =MIN(50,(ROUNDUP(T/2,0)))              FORMULA — never overwrite
  V (22)  end_term   INPUT
  W (23)  =MIN(50,(ROUNDUP(V/2,0)))              FORMULA — never overwrite
  X (24)  =MIN(100,(SUM(U,W)))                   FORMULA — never overwrite
  Y (25)  =(X/100)                               FORMULA — never overwrite
  Z (26)  GPA  IF-chain — returns "4.0".."0.0"  FORMULA — never overwrite
  AA (27) Grade IF-chain — returns "A1".."F9"   FORMULA — never overwrite
"""

import math
import os
import re
import shutil
import tempfile
import zipfile
import copy
from lxml import etree

from openpyxl import load_workbook

# ─────────────────────────────────────────────────────────────────────────────
# Namespaces used in the xlsx ZIP XML
# ─────────────────────────────────────────────────────────────────────────────
_NS_WB   = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_R    = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_CT   = "http://schemas.openxmlformats.org/package/2006/content-types"
_NS_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"

_REL_SHEET = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"

# ─────────────────────────────────────────────────────────────────────────────
# Constants — verified against actual student_template.xlsx
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

# ── Formula-protected columns ────────────────────────────────────────────────
# These columns contain Excel formulas that must NEVER be overwritten.
# Verified against actual template row 10.
_FORMULA_COLS = {'J', 'M', 'P', 'S', 'T', 'U', 'W', 'X', 'Y', 'Z', 'AA'}

# ── Category → 1-based column number for INPUT cells ────────────────────────
# Verified against column headers in row 9 of student_template.xlsx.
_CAT_TO_COL = {
    'ica1':      8,   # H
    'ica2':      9,   # I
    'icp1':     11,   # K
    'icp2':     12,   # L
    'gp1':      14,   # N
    'gp2':      15,   # O
    'practical': 17,  # Q
    'mid_term':  18,  # R
    'end_term':  22,  # V
}

STUDENT_START_ROW = 10   # First student data row (row 9 is the header row)

# GPA table — mirrors the Z-column IF chain in the template.
# Python consumers receive numeric floats for comparison; the template itself
# returns string "4.0", "3.5" etc. for display.
_GPA_TABLE = [
    (80, 4.0, 'A1'),
    (70, 3.5, 'B2'),
    (65, 3.0, 'B3'),
    (60, 2.5, 'C4'),
    (55, 2.0, 'C5'),
    (50, 1.5, 'C6'),
    (45, 1.0, 'D7'),
    (40, 0.5, 'E8'),
    (0,  0.0, 'F9'),
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
    Python mirror of the Excel formula chain in student_template.xlsx.
    Returns every key consumed by models.Student.get_overall_summary().

    GPA is returned as a numeric float (4.0, 3.5 …) for Python comparisons.
    The template's Z-column displays the equivalent string ("4.0", "3.5" …)
    for on-screen formatting — this is a display-only difference.
    """
    def _v(k):
        return float(raw_scores.get(k) or 0)

    ica1 = _v('ica1');  ica2 = _v('ica2')
    icp1 = _v('icp1');  icp2 = _v('icp2')
    gp1  = _v('gp1');   gp2  = _v('gp2')
    practical = _v('practical')
    mid_term  = _v('mid_term')
    end_term  = _v('end_term')

    # Mirrors J, M, P columns
    ica_total = min(100.0, ica1 + ica2)
    icp_total = min(100.0, icp1 + icp2)
    gp_total  = min(100.0, gp1  + gp2)

    # Mirrors S column: =MIN(500,(SUM(J,M,P,Q,R)))
    total_class_score = min(500.0, ica_total + icp_total + gp_total
                                   + practical + mid_term)

    # Mirrors T column: =S/500*100
    pct_100 = (total_class_score / 500.0) * 100.0

    # Mirrors U column: =MIN(50,(ROUNDUP(T/2,0)))
    avg_class_score = min(50.0, math.ceil(pct_100 / 2.0))

    # Mirrors W column: =MIN(50,(ROUNDUP(V/2,0)))
    avg_exam_score = min(50.0, math.ceil(end_term / 2.0))

    # Mirrors X column: =MIN(100,(SUM(U,W)))
    final_score = min(100.0, avg_class_score + avg_exam_score)
    percentage  = final_score

    gpa = 0.0;  grade = 'F9'
    for threshold, gpa_val, grade_val in _GPA_TABLE:
        if final_score >= threshold:
            gpa   = gpa_val
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


def _grade(percent):
    """Return GPA and grade mapping for a final percentage."""
    if percent is None:
        return {'gpa': 'N/A', 'grade': 'N/A'}
    for threshold, gpa_val, grade_val in _GPA_TABLE:
        if percent >= threshold:
            return {'gpa': gpa_val, 'grade': grade_val}
    return {'gpa': 0.0, 'grade': 'F9'}


# ─────────────────────────────────────────────────────────────────────────────
# ZIP-level sheet duplicator
# ─────────────────────────────────────────────────────────────────────────────

class _ZipSheetDuplicator:
    """
    Duplicates an xlsx at the raw ZIP level so that every feature of the
    source sheet — drawings, images, tables, theme fills, shared formulas,
    row heights, custom namespace extensions — is preserved in each copy.

    openpyxl is only used for reading and writing DATA cells (values).
    All structural duplication is done by directly editing the ZIP XML.
    """

    def __init__(self, template_path: str):
        self._tpl = template_path
        self._files: dict[str, bytes] = {}
        # FIXED: actual sheet name in student_template.xlsx
        self._source_sheet_name = "student_template"
        self._sheet_paths: list[str] = []
        self._sheet_names: list[str] = []
        self._sheet_trees: dict[str, etree._Element] = {}

    # ── preparation ─────────────────────────────────────────────────────────

    def prepare(self, extra_sheet_labels: list[str]) -> None:
        with zipfile.ZipFile(self._tpl, 'r') as z:
            for name in z.namelist():
                self._files[name] = z.read(name)

        wb_tree = etree.fromstring(self._files['xl/workbook.xml'])
        ns = {'ns': _NS_WB, 'r': _NS_R}
        src_rId = None
        for sheet_el in wb_tree.findall('.//ns:sheet', ns):
            if sheet_el.get('name') == self._source_sheet_name:
                src_rId = sheet_el.get('{%s}id' % _NS_R)
                break
        if src_rId is None:
            # Fallback to first sheet
            sheet_el = wb_tree.findall('.//ns:sheet', ns)[0]
            src_rId  = sheet_el.get('{%s}id' % _NS_R)
            self._source_sheet_name = sheet_el.get('name')

        wb_rels_tree = etree.fromstring(self._files['xl/_rels/workbook.xml.rels'])
        ns_rels = {'r': _NS_RELS}
        self._src_sheet_path = None
        self._src_rels_path  = None
        for rel in wb_rels_tree.findall('r:Relationship', ns_rels):
            if rel.get('Id') == src_rId:
                target = rel.get('Target').lstrip('/')
                if not target.startswith('xl/'):
                    target = 'xl/' + target
                self._src_sheet_path = target
                self._src_rels_path  = target.replace(
                    'worksheets/', 'worksheets/_rels/'
                ).replace('.xml', '.xml.rels')
                break

        if self._src_sheet_path is None:
            raise RuntimeError("Could not locate source sheet in template workbook.xml.rels")

        self._sheet_paths = [self._src_sheet_path]
        self._sheet_names = [self._source_sheet_name]

        for i, label in enumerate(extra_sheet_labels):
            self._clone_sheet(i + 2, label)

        if extra_sheet_labels:
            self._sheet_names[0] = extra_sheet_labels[0]
            self._rename_sheet_in_workbook(1, extra_sheet_labels[0])

    def _clone_sheet(self, sheet_index: int, display_name: str) -> None:
        new_path      = f'xl/worksheets/sheet{sheet_index}.xml'
        new_rels_path = f'xl/worksheets/_rels/sheet{sheet_index}.xml.rels'
        rId           = f'rId_sheet{sheet_index}'

        src_xml = re.sub(
            rb'xr:uid="\{[0-9A-F-]+\}"', b'', self._files[self._src_sheet_path],
            flags=re.IGNORECASE
        )
        self._files[new_path] = src_xml

        if self._src_rels_path in self._files:
            self._files[new_rels_path] = self._files[self._src_rels_path]
        else:
            self._files[new_rels_path] = (
                b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
            )

        wb_tree = etree.fromstring(self._files['xl/workbook.xml'])
        ns = {'ns': _NS_WB, 'r': _NS_R}
        sheets_el = wb_tree.find('.//ns:sheets', ns)
        new_sheet_el = etree.SubElement(sheets_el, '{%s}sheet' % _NS_WB)
        new_sheet_el.set('name', display_name)
        new_sheet_el.set('sheetId', str(sheet_index))
        new_sheet_el.set('{%s}id' % _NS_R, rId)
        self._files['xl/workbook.xml'] = etree.tostring(
            wb_tree, xml_declaration=True, encoding='UTF-8', standalone=True
        )

        wb_rels_tree = etree.fromstring(self._files['xl/_rels/workbook.xml.rels'])
        ns_rels = {'r': _NS_RELS}
        new_rel = etree.SubElement(wb_rels_tree, '{%s}Relationship' % _NS_RELS)
        new_rel.set('Id', rId)
        new_rel.set('Type', _REL_SHEET)
        new_rel.set('Target', new_path.replace('xl/', ''))
        self._files['xl/_rels/workbook.xml.rels'] = etree.tostring(
            wb_rels_tree, xml_declaration=True, encoding='UTF-8', standalone=True
        )

        ct_tree = etree.fromstring(self._files['[Content_Types].xml'])
        new_ov = etree.SubElement(ct_tree, '{%s}Override' % _NS_CT)
        new_ov.set('PartName', '/' + new_path)
        new_ov.set(
            'ContentType',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'
        )
        self._files['[Content_Types].xml'] = etree.tostring(
            ct_tree, xml_declaration=True, encoding='UTF-8', standalone=True
        )

        self._sheet_paths.append(new_path)
        self._sheet_names.append(display_name)

    def _rename_sheet_in_workbook(self, sheet_index: int, name: str) -> None:
        wb_tree = etree.fromstring(self._files['xl/workbook.xml'])
        ns = {'ns': _NS_WB}
        sheets = wb_tree.findall('.//ns:sheet', ns)
        if len(sheets) >= sheet_index:
            sheets[sheet_index - 1].set('name', name)
        self._files['xl/workbook.xml'] = etree.tostring(
            wb_tree, xml_declaration=True, encoding='UTF-8', standalone=True
        )

    # ── data writing ────────────────────────────────────────────────────────

    def _get_sheet_tree(self, sheet_idx: int) -> etree._Element:
        path = self._sheet_paths[sheet_idx]
        if path not in self._sheet_trees:
            self._sheet_trees[path] = etree.fromstring(self._files[path])
        return self._sheet_trees[path]

    def _flush_sheet_tree(self, sheet_idx: int) -> None:
        path = self._sheet_paths[sheet_idx]
        if path in self._sheet_trees:
            self._files[path] = etree.tostring(
                self._sheet_trees[path],
                xml_declaration=True,
                encoding='UTF-8',
                standalone=True,
            )

    def write_header(self, sheet_idx: int, subject: str, term_year: str, form: str) -> None:
        """Write B2/B3/B4 on the given sheet (0-based index)."""
        tree = self._get_sheet_tree(sheet_idx)
        ns   = {'ns': _NS_WB}

        def _set(cell_ref: str, value: str) -> None:
            row_num, col_num = _cell_ref_to_row_col(cell_ref)
            _set_cell_value_in_tree(tree, ns, row_num, col_num, value)

        if subject:
            _set('B2', _humanise(subject))
        if term_year:
            _set('B3', term_year)
        if form:
            _set('B4', form)

    def write_student_row(self, sheet_idx: int, row: int, student_dict: dict) -> None:
        """
        Write one student's data onto sheet `sheet_idx` (0-based) at `row`.

        Formula columns are NEVER touched — the template XML already has
        pre-filled formulas for every row.

        Expected keys in student_dict
        ──────────────────────────────
        student_number  — goes to column B (2)
        last_name       — goes to column C (3)   [Surname]
        first_name      — goes to column D (4)
        middle_name     — goes to column E (5)   [Other Name, may be empty]
        ref_id          — goes to column F (6)
        study_area      — goes to column G (7)
        ica1..end_term  — input score columns per _CAT_TO_COL
        """
        tree = self._get_sheet_tree(sheet_idx)
        ns   = {'ns': _NS_WB}
        serial = row - STUDENT_START_ROW + 1

        # Column A: serial number
        _set_cell_numeric(tree, ns, row, 1, serial)
        # Column B: Student Number
        _set_cell_string(tree, ns, row, 2, student_dict.get('student_number', ''))
        # Column C: Surname
        _set_cell_string(tree, ns, row, 3, student_dict.get('last_name', ''))
        # Column D: First Name
        _set_cell_string(tree, ns, row, 4, student_dict.get('first_name', ''))
        # Column E: Other Name
        _set_cell_string(tree, ns, row, 5, student_dict.get('middle_name', '') or '')
        # Column F: Reference Number
        _set_cell_string(tree, ns, row, 6, student_dict.get('ref_id', ''))
        # Column G: Study Area
        _set_cell_string(tree, ns, row, 7, student_dict.get('study_area', ''))

        # Score input columns (formula columns are left untouched)
        for cat, col in _CAT_TO_COL.items():
            raw = student_dict.get(cat, 0)
            val = float(raw) if raw not in (None, '') else 0.0
            _set_cell_numeric(tree, ns, row, col, val)

    def save(self, output_path: str) -> str:
        for i in range(len(self._sheet_paths)):
            self._flush_sheet_tree(i)

        dirpart = os.path.dirname(output_path)
        if dirpart:
            os.makedirs(dirpart, exist_ok=True)

        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zout:
            for name, data in self._files.items():
                zout.writestr(name, data)
        return output_path


# ─────────────────────────────────────────────────────────────────────────────
# XML cell-editing helpers
# ─────────────────────────────────────────────────────────────────────────────

def _col_letter_to_num(col: str) -> int:
    num = 0
    for ch in col.upper():
        num = num * 26 + (ord(ch) - ord('A') + 1)
    return num


def _col_num_to_letter(n: int) -> str:
    result = ''
    while n:
        n, r = divmod(n - 1, 26)
        result = chr(ord('A') + r) + result
    return result


def _cell_ref_to_row_col(ref: str):
    m = re.match(r'([A-Z]+)(\d+)', ref.upper())
    if not m:
        raise ValueError(f"Invalid cell ref: {ref}")
    return int(m.group(2)), _col_letter_to_num(m.group(1))


def _find_or_create_row(tree: etree._Element, ns: dict, row_num: int) -> etree._Element:
    sheet_data = tree.find('ns:sheetData', ns)
    if sheet_data is None:
        sheet_data = tree.find('{%s}sheetData' % _NS_WB)
    for row_el in sheet_data:
        r = int(row_el.get('r', 0))
        if r == row_num:
            return row_el
        if r > row_num:
            new_row = etree.Element('{%s}row' % _NS_WB)
            new_row.set('r', str(row_num))
            sheet_data.insert(list(sheet_data).index(row_el), new_row)
            return new_row
    new_row = etree.Element('{%s}row' % _NS_WB)
    new_row.set('r', str(row_num))
    sheet_data.append(new_row)
    return new_row


def _find_or_create_cell(row_el: etree._Element, col_num: int) -> etree._Element:
    col_letter = _col_num_to_letter(col_num)
    row_num    = int(row_el.get('r'))
    cell_ref   = f'{col_letter}{row_num}'

    for cell in row_el:
        c_ref = cell.get('r', '')
        if c_ref == cell_ref:
            return cell
        if c_ref:
            c_col = _col_letter_to_num(re.match(r'([A-Z]+)', c_ref).group(1))
            if c_col > col_num:
                new_cell = etree.Element('{%s}c' % _NS_WB)
                new_cell.set('r', cell_ref)
                row_el.insert(list(row_el).index(cell), new_cell)
                return new_cell
    new_cell = etree.Element('{%s}c' % _NS_WB)
    new_cell.set('r', cell_ref)
    row_el.append(new_cell)
    return new_cell


def _set_cell_numeric(tree: etree._Element, ns: dict, row_num: int, col_num: int, value) -> None:
    row_el  = _find_or_create_row(tree, ns, row_num)
    cell_el = _find_or_create_cell(row_el, col_num)
    if 't' in cell_el.attrib:
        del cell_el.attrib['t']
    for f_el in cell_el.findall('{%s}f' % _NS_WB):
        cell_el.remove(f_el)
    v_el = cell_el.find('{%s}v' % _NS_WB)
    if v_el is None:
        v_el = etree.SubElement(cell_el, '{%s}v' % _NS_WB)
    v_el.text = str(int(value)) if isinstance(value, float) and value == int(value) else str(value)


def _set_cell_string(tree: etree._Element, ns: dict, row_num: int, col_num: int, value: str) -> None:
    row_el  = _find_or_create_row(tree, ns, row_num)
    cell_el = _find_or_create_cell(row_el, col_num)
    for child in list(cell_el):
        cell_el.remove(child)
    cell_el.set('t', 'inlineStr')
    is_el = etree.SubElement(cell_el, '{%s}is' % _NS_WB)
    t_el  = etree.SubElement(is_el,   '{%s}t'  % _NS_WB)
    t_el.text = str(value) if value else ''


def _set_cell_value_in_tree(tree, ns, row_num, col_num, value, cell_type='str'):
    _set_cell_string(tree, ns, row_num, col_num, value)


# ─────────────────────────────────────────────────────────────────────────────
# Core class (openpyxl-based, single-sheet operations)
# ─────────────────────────────────────────────────────────────────────────────

class AssessmentTemplateUpdater:
    """
    All exports use this class.

        upd = AssessmentTemplateUpdater(tpl_path)
        upd.load_template()
        upd.update_school_info(subject=…, term_year=…, form=…)
        upd.add_student(row, dict) | upd.add_students_batch(…)
        upd.save_workbook(output_path)

    For multi-sheet exports the class delegates to _ZipSheetDuplicator to
    preserve the school logo, drawings, grade table and every formula row.
    """

    def __init__(self, template_path: str):
        self.template_path = template_path
        self.wb            = None
        self._tmp          = None
        self._def_subject  = ''
        self._def_term     = ''
        self._def_form     = ''
        self._dup: _ZipSheetDuplicator | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def load_template(self):
        if not os.path.exists(self.template_path):
            raise FileNotFoundError(
                f"School template not found: {self.template_path}\n"
                "Place student_template.xlsx in the templates_excel/ folder."
            )
        fd, self._tmp = tempfile.mkstemp(suffix='.xlsx')
        os.close(fd)
        shutil.copy2(self.template_path, self._tmp)
        self.wb = load_workbook(self._tmp)
        return self

    def save_workbook(self, output_path: str) -> str:
        if self._dup is not None:
            try:
                return self._dup.save(output_path)
            finally:
                self._cleanup()
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
        if subject:
            self._def_subject = subject
        if term_year:
            self._def_term = term_year
        if form:
            self._def_form = form

        if self.wb is None:
            return

        sheets = [worksheet] if worksheet else [self.wb.active]
        for ws in sheets:
            if subject:
                ws['B2'] = _humanise(subject)
            if term_year:
                ws['B3'] = term_year
            if form:
                ws['B4'] = form

    # ── add single student (openpyxl path — single sheet) ────────────────────

    def add_student(self, row: int, student_dict: dict):
        ws = self.wb.active
        _ensure_formula_row(ws, row)
        _write_student_row(ws, row, student_dict)

    # ── batch ────────────────────────────────────────────────────────────────

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

        # Multi-sheet via ZIP duplicator
        groups: dict = {}
        order: list  = []
        for sd in students:
            key = (sd.get('sheet_subject', ''), sd.get('sheet_class', ''))
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(sd)

        labels = [
            _safe_sheet_name(
                f"{_humanise(subj)} \u2013 {cls}" if cls and subj
                else _humanise(subj) or cls or 'Sheet'
            )
            for subj, cls in order
        ]

        dup = _ZipSheetDuplicator(self.template_path)
        dup.prepare(labels[1:] if len(order) > 1 else [])
        if len(order) == 1:
            dup._rename_sheet_in_workbook(1, labels[0])
        self._dup = dup

        for sheet_idx, key in enumerate(order):
            subj, cls = key
            dup.write_header(
                sheet_idx,
                subj if subj else self._def_subject,
                self._def_term,
                cls  if cls  else self._def_form,
            )
            for i, sd in enumerate(groups[key]):
                dup.write_student_row(sheet_idx, STUDENT_START_ROW + i, sd)

    # ── admin "all students by subject+class" ────────────────────────────────

    def export_by_subject_class(self, students_list: list, settings=None,
                                subject_filter=None, class_filter=None):
        term_year = _build_term_year(settings)

        groups: dict = {}
        order:  list = []
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
                key = (subj, cls)
                if key not in groups:
                    groups[key] = []
                    order.append(key)
                groups[key].append((student, subj))

        if not groups:
            self._write_single_header_only(term_year)
            return

        labels = [
            _safe_sheet_name(
                f"{_humanise(subj)} \u2013 {cls}" if cls and subj
                else _humanise(subj) or cls or 'Sheet'
            )
            for subj, cls in order
        ]

        dup = _ZipSheetDuplicator(self.template_path)
        dup.prepare(labels[1:])
        dup._rename_sheet_in_workbook(1, labels[0])
        self._dup = dup

        for sheet_idx, key in enumerate(order):
            subj, cls = key
            dup.write_header(
                sheet_idx,
                subj or 'All Subjects',
                term_year,
                cls  or 'All Classes',
            )
            for i, (student, s) in enumerate(groups[key]):
                sd = student.to_template_dict(s if s else None)
                dup.write_student_row(sheet_idx, STUDENT_START_ROW + i, sd)

    def _write_single_header_only(self, term_year: str):
        if self.wb is None:
            return
        ws = self.wb.active
        if term_year:
            ws['B3'] = term_year

    # ── raw assessments export ───────────────────────────────────────────────

    def export_assessments_raw(self, assessments: list, output_path: str,
                               settings=None) -> str:
        term_year = _build_term_year(settings)

        groups: dict       = {}
        order:  list       = []
        student_meta: dict = {}

        for a in assessments:
            key = (a.subject or '', a.class_name or '')
            if key not in groups:
                groups[key] = {}
                order.append(key)
            sid = a.student_id
            groups[key].setdefault(sid, {})
            if a.category in CATEGORY_MAX:
                prev = groups[key][sid].get(a.category, -1)
                if float(a.score or 0) > prev:
                    groups[key][sid][a.category] = float(a.score or 0)
            if sid not in student_meta and a.student:
                st = a.student
                student_meta[sid] = {
                    'student_number': st.student_number or '',
                    'last_name':      st.last_name or '',
                    'first_name':     st.first_name or '',
                    'middle_name':    st.middle_name or '',
                    'ref_id':         st.reference_number or '',
                    'study_area':     (st.get_study_area_display()
                                       if hasattr(st, 'get_study_area_display')
                                       else (st.study_area or '')),
                }

        if not groups:
            if self.wb is None:
                self.load_template()
            self._write_single_header_only(term_year)
            return self.save_workbook(output_path)

        labels = [
            _safe_sheet_name(
                f"{_humanise(subj)} \u2013 {cls}" if cls and subj
                else _humanise(subj) or cls or 'Sheet'
            )
            for subj, cls in order
        ]

        dup = _ZipSheetDuplicator(self.template_path)
        dup.prepare(labels[1:])
        dup._rename_sheet_in_workbook(1, labels[0])
        self._dup = dup

        for sheet_idx, key in enumerate(order):
            subj, cls = key
            dup.write_header(
                sheet_idx,
                subj or 'All Subjects',
                term_year,
                cls or 'All Classes',
            )
            sorted_sids = sorted(
                groups[key],
                key=lambda s: student_meta.get(s, {}).get('last_name', '')
            )
            for i, sid in enumerate(sorted_sids):
                meta = student_meta.get(sid, {})
                sd = {
                    **meta,
                    **{cat: groups[key][sid].get(cat, 0) for cat in CATEGORY_MAX},
                }
                dup.write_student_row(sheet_idx, STUDENT_START_ROW + i, sd)

        return dup.save(output_path)


# ─────────────────────────────────────────────────────────────────────────────
# openpyxl-level helpers (single-sheet writes via wb.active)
# ─────────────────────────────────────────────────────────────────────────────

def _write_student_row(ws, row: int, sd: dict):
    """
    Write data columns only; formula columns are never touched.

    Columns written (1-based):
      A(1)  serial        B(2)  student_number  C(3)  last_name
      D(4)  first_name    E(5)  middle_name     F(6)  ref_id
      G(7)  study_area    H-V   score inputs (per _CAT_TO_COL)
    """
    serial = row - STUDENT_START_ROW + 1
    ws.cell(row=row, column=1,  value=serial)
    ws.cell(row=row, column=2,  value=sd.get('student_number', ''))
    ws.cell(row=row, column=3,  value=sd.get('last_name',      ''))
    ws.cell(row=row, column=4,  value=sd.get('first_name',     ''))
    ws.cell(row=row, column=5,  value=sd.get('middle_name',    '') or '')
    ws.cell(row=row, column=6,  value=sd.get('ref_id',         ''))
    ws.cell(row=row, column=7,  value=sd.get('study_area',     ''))
    for cat, col in _CAT_TO_COL.items():
        raw = sd.get(cat, 0)
        ws.cell(row=row, column=col,
                value=float(raw) if raw not in (None, '') else 0.0)


def _ensure_formula_row(ws, row: int):
    """
    The template pre-fills rows 10–110 with formulas.
    Only needs action when the target row is beyond that range.
    Uses row 11 as the preferred shared-formula source (row 10 has
    slightly different formula whitespace in the raw XML).
    """
    source_row   = STUDENT_START_ROW + 1   # row 11
    fallback_row = STUDENT_START_ROW        # row 10
    for col in _FORMULA_COLS:
        src = ws[f'{col}{source_row}']
        if not (src.value and str(src.value).startswith('=')):
            src = ws[f'{col}{fallback_row}']
        tgt = ws[f'{col}{row}']
        if (src.value and str(src.value).startswith('=')) and \
                not (tgt.value and str(tgt.value).startswith('=')):
            tgt.value = _shift_formula(str(src.value), int(src.row), row)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _humanise(key: str) -> str:
    return key.replace('_', ' ').title() if key else ''


def _safe_sheet_name(name: str) -> str:
    for ch in r'/\?*[]:\'':
        name = name.replace(ch, '-')
    return name[:31]


def _shift_formula(formula: str, from_row: int, to_row: int) -> str:
    """Shift all cell references in a formula from from_row to to_row."""
    pattern = re.compile(r'([A-Z]+)' + str(from_row) + r'(?!\d)')
    return pattern.sub(lambda m: m.group(1) + str(to_row), formula)


def _build_term_year(settings) -> str:
    """Always returns a clean string, never raises."""
    if not settings:
        return ''
    term_raw = getattr(settings, 'current_term', '') or ''
    year     = getattr(settings, 'current_academic_year', '') or ''
    try:
        from flask import current_app
        terms_cfg  = current_app.config.get('TERMS', [])
        term_label = dict(terms_cfg).get(term_raw, term_raw)
    except Exception:
        term_label = re.sub(r'term(\d+)', r'Term \1', term_raw,
                            flags=re.IGNORECASE).strip() or term_raw
    return f"{term_label} {year}".strip()
