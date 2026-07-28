from template_updater import _ZipSheetDuplicator
from pathlib import Path
from test_excel_exports import _create_minimal_school_template
import shutil

root = Path('tmp_debug')
if root.exists():
    shutil.rmtree(root)
root.mkdir()
_create_minimal_school_template(str(root / 'student_template.xlsx'))
name = str(root / 'student_template.xlsx')
dup = _ZipSheetDuplicator(name)
try:
    dup.prepare([])
    print('src', dup._src_sheet_path)
    print('sheet_paths', dup._sheet_paths)
    print('sheet_names', dup._sheet_names)
except Exception as e:
    import traceback
    traceback.print_exc()
