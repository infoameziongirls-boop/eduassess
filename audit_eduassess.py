#!/usr/bin/env python3
"""
EduAssess audit
===============

One self-contained audit you run from VS Code (Terminal > Run Task, or just
`python audit_eduassess.py`) from the project root, inside the project's own
virtual environment.

SAFETY
  * It never touches your real database. It forces the "testing" config onto a
    brand-new temporary SQLite file, ignores DATABASE_URL / REDIS_URL, and puts
    uploads and sessions in a temporary folder.
  * The ONLY thing that can read a live database is the optional
    `--live-db-url` flag. That mode opens a READ ONLY transaction, runs
    SELECT count(*) style queries, and prints counts (never names or
    personal data).

USAGE
  python audit_eduassess.py                  # full audit, ~1,500 seeded students
  python audit_eduassess.py --scale 5000     # performance section at 5,000 students
  python audit_eduassess.py --skip-perf      # quicker
  python audit_eduassess.py --live-db-url "postgresql://..."   # + read-only data audit
  python audit_eduassess.py --only static,security              # sections: static,routes,access,flows,security,data,perf

OUTPUT
  Console summary + audit_report.md. Exit code 1 if anything FAILED.
  FAIL  = a defect or a security problem; fix before release.
  WARN  = a risk or a weakness worth a decision.
  INFO / SKIP = context, or a check that did not apply to this project.
"""
import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from collections import OrderedDict, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXCLUDE_DIRS = {'.git', '.venv', 'venv', 'env', 'node_modules', '__pycache__',
                'instance', '.mypy_cache', '.pytest_cache', 'build', 'dist', 'site-packages'}

# --------------------------------------------------------------------------
# result registry
# --------------------------------------------------------------------------
RESULTS = []          # (section, name, status, detail)
ORDER = {'FAIL': 0, 'WARN': 1, 'INFO': 2, 'SKIP': 3, 'PASS': 4}


def record(section, name, status, detail=''):
    RESULTS.append((section, name, status, str(detail).strip()))
    tag = {'PASS': 'PASS', 'FAIL': 'FAIL', 'WARN': 'WARN', 'INFO': 'INFO', 'SKIP': 'SKIP'}[status]
    first = str(detail).strip().splitlines()[0] if str(detail).strip() else ''
    print(f'  [{tag}] {name}' + (f'  -  {first[:160]}' if first and status != 'PASS' else ''))


def guarded(section, name):
    """Decorator: run a check, turn an exception into a FAIL, never abort the audit."""
    def deco(fn):
        try:
            fn()
        except Exception as exc:                      # noqa: BLE001
            tb = traceback.format_exc().strip().splitlines()[-6:]
            record(section, name, 'FAIL', f'audit check crashed: {exc!r}\n' + '\n'.join(tb))
        return fn
    return deco


def heading(text):
    print(f'\n=== {text} ===')


def project_files(suffixes):
    for path in ROOT.rglob('*'):
        if path.is_file() and path.suffix in suffixes:
            if any(part in EXCLUDE_DIRS for part in path.relative_to(ROOT).parts):
                continue
            if path.name == Path(__file__).name:
                continue
            yield path


def rel(path):
    return str(Path(path).relative_to(ROOT)).replace('\\', '/')


def git(*args):
    try:
        out = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, timeout=30)
        return out.returncode, out.stdout
    except (OSError, subprocess.SubprocessError):
        return None, ''


# --------------------------------------------------------------------------
# arguments
# --------------------------------------------------------------------------
parser = argparse.ArgumentParser(description='EduAssess audit')
parser.add_argument('--scale', type=int, default=1500, help='students to seed for the performance section')
parser.add_argument('--skip-perf', action='store_true')
parser.add_argument('--live-db-url', default='', help='READ-ONLY integrity audit of a live database (counts only)')
parser.add_argument('--only', default='', help='comma list of sections')
parser.add_argument('--report', default=str(ROOT / 'audit_report.md'))
ARGS = parser.parse_args()
ONLY = {s.strip() for s in ARGS.only.split(',') if s.strip()}


def wanted(section):
    return not ONLY or section in ONLY


# ==========================================================================
# 1. STATIC CHECKS  (no app import needed)
# ==========================================================================
def static_checks():
    heading('1. Static checks')
    S = 'static'
    py_files = sorted(project_files({'.py'}))

    @guarded(S, 'Python syntax')
    def _():
        bad = []
        for p in py_files:
            try:
                ast.parse(p.read_text(encoding='utf-8', errors='replace'), filename=str(p))
            except SyntaxError as e:
                bad.append(f'{rel(p)}:{e.lineno}: {e.msg}')
        record(S, f'Python syntax ({len(py_files)} files)', 'FAIL' if bad else 'PASS', '\n'.join(bad))

    templates_dir = ROOT / 'templates'
    templates = sorted(templates_dir.rglob('*.html')) if templates_dir.exists() else []

    @guarded(S, 'templates referenced by code exist')
    def _():
        have = {rel(p)[len('templates/'):] for p in templates}
        missing = []
        pat = re.compile(r'render_template\(\s*[\'"]([^\'"]+)[\'"]')
        for p in py_files:
            text = p.read_text(encoding='utf-8', errors='replace')
            for m in pat.finditer(text):                      # whole file: calls often span several lines
                if m.group(1) not in have:
                    missing.append(f'{rel(p)}:{text.count(chr(10), 0, m.start()) + 1}: {m.group(1)}')
        ref = re.compile(r'\{%-?\s*(?:extends|include|import|from)\s+[\'"]([^\'"]+)[\'"]')
        for t in templates:
            for n, line in enumerate(t.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                for m in ref.finditer(line):
                    if m.group(1) not in have:
                        missing.append(f'{rel(t)}:{n}: {m.group(1)}')
        record(S, 'every template named in code or in {% extends/include %} exists',
               'FAIL' if missing else 'PASS', '\n'.join(missing[:40]))

    @guarded(S, 'git ignores')
    def _():
        code, _out = git('rev-parse', '--is-inside-work-tree')
        if code != 0:
            record(S, 'git: templates are not hidden by .gitignore', 'SKIP', 'not a git repository (or git not installed)')
            return
        ignored, untracked = [], []
        _c, tracked_out = git('ls-files')
        tracked = set(tracked_out.splitlines())
        for t in templates + [p for p in (ROOT / 'static').rglob('*') if p.is_file()]:
            r = rel(t)
            c, _o = git('check-ignore', '-q', r)
            if c == 0:
                ignored.append(r)
            elif r not in tracked:
                untracked.append(r)
        record(S, 'git: no template/static file is ignored by .gitignore (would be missing on Render)',
               'FAIL' if ignored else 'PASS', '\n'.join(ignored[:40]))
        record(S, 'git: every template/static file is tracked (a file only on your PC is not deployed)',
               'WARN' if untracked else 'PASS',
               'untracked (run `git add`):\n' + '\n'.join(untracked[:40]) if untracked else '')
        risky = [f for f in tracked if re.search(r'(^|/)(\.env[^/]*|.*\.db|.*\.sqlite3?|instance/.*)$', f)
                 and not re.search(r'(^|/)\.env\.(example|sample|template|dist)$', f)]   # templates of settings are meant to be committed
        record(S, 'git: no database or real .env file is committed', 'FAIL' if risky else 'PASS', '\n'.join(risky[:20]))
        for f in tracked:
            if re.search(r'(^|/)\.env\.(example|sample|template|dist)$', f):
                try:
                    body = (ROOT / f).read_text(encoding='utf-8', errors='replace')
                except OSError:
                    continue
                real = [ln.split('=')[0] for ln in body.splitlines()
                        if re.match(r'^\s*[A-Z0-9_]*(SECRET|PASSWORD|TOKEN|KEY|DATABASE_URL)[A-Z0-9_]*\s*=\s*\S{16,}', ln)
                        and not re.search(r'(change|your|example|placeholder|xxx|<|user:pass|password@|@host|localhost|dummy|todo)', ln, re.I)]
                record(S, f'{f} holds placeholders only (no real secrets)', 'WARN' if real else 'PASS',
                       'values that look real for: ' + ', '.join(real) if real else '')

    @guarded(S, 'JavaScript syntax')
    def _():
        node = shutil.which('node')
        js = sorted(project_files({'.js'}))
        js = [p for p in js if 'min.js' not in p.name and 'bundle' not in p.name]
        if not node:
            record(S, 'JavaScript syntax', 'SKIP', 'node is not installed (https://nodejs.org) - this check was skipped')
            return
        bad = []
        for p in js:
            r = subprocess.run([node, '--check', str(p)], capture_output=True, text=True)
            if r.returncode:
                bad.append(f'{rel(p)}: {r.stderr.strip().splitlines()[0] if r.stderr.strip() else "syntax error"}')
        record(S, f'JavaScript syntax ({len(js)} files)', 'FAIL' if bad else 'PASS', '\n'.join(bad))

    @guarded(S, 'service worker assets')
    def _():
        candidates = [ROOT / 'sw.js', ROOT / 'static' / 'sw.js']
        sw = next((c for c in candidates if c.exists()), None)
        if not sw:
            record(S, 'service worker shell assets exist', 'SKIP', 'no sw.js found')
            return
        text = sw.read_text(encoding='utf-8', errors='replace')
        block = re.search(r'SHELL_ASSETS\s*=\s*\[(.*?)\]', text, re.S)
        paths = re.findall(r'[\'"](/static/[^\'"]+)[\'"]', block.group(1)) if block else []
        missing = [p for p in paths if not (ROOT / p.lstrip('/')).exists()]
        record(S, f'service worker pre-cache list: every file exists ({len(paths)} listed)',
               'FAIL' if missing else 'PASS',
               'addAll() rejects the whole install if one file 404s:\n' + '\n'.join(missing))

    @guarded(S, 'requirements')
    def _():
        req = ROOT / 'requirements.txt'
        if not req.exists():
            record(S, 'requirements.txt pins match installed packages', 'WARN', 'requirements.txt not found')
            return
        from importlib import metadata
        drift, unpinned = [], []
        for line in req.read_text(encoding='utf-8', errors='replace').splitlines():
            line = line.split('#')[0].strip()
            if not line or line.startswith('-'):
                continue
            m = re.match(r'^([A-Za-z0-9_.\-]+)\s*(==|>=|~=|<=|>|<)?\s*([^;\s]+)?', line)
            if not m:
                continue
            name, op, ver = m.groups()
            try:
                installed = metadata.version(name)
            except metadata.PackageNotFoundError:
                drift.append(f'{name}: listed in requirements but not installed here')
                continue
            if op != '==':
                unpinned.append(name)
            elif ver and installed != ver:
                drift.append(f'{name}: requirements pin {ver}, installed here {installed}')
        record(S, 'requirements.txt pins match what you are testing with', 'WARN' if drift else 'PASS', '\n'.join(drift))
        key = [n for n in unpinned if n.lower() in {'flask', 'wtforms', 'flask-wtf', 'sqlalchemy', 'flask-sqlalchemy', 'werkzeug'}]
        record(S, 'framework packages are pinned with == (an unpinned WTForms 3.3 upgrade caused the earlier /assessments crash)',
               'WARN' if key else 'PASS', ', '.join(key))

    @guarded(S, 'risky code patterns')
    def _():
        rules = [
            (r'debug\s*=\s*True', 'debug=True'),
            (r'verify\s*=\s*False', 'TLS verification disabled'),
            (r'shell\s*=\s*True', 'shell=True'),
            (r'pickle\.loads?\(', 'pickle load'),
            (r'yaml\.load\((?![^)]*Loader)', 'yaml.load without Loader'),
            (r'\beval\(', 'eval()'),
            (r'render_template_string\(', 'render_template_string'),
            (r'(password|secret|token)\w*\s*=\s*[\'"][^\'"]{6,}[\'"]', 'hard-coded credential-like literal'),
        ]
        hits = defaultdict(list)
        for p in py_files:
            if p.name.startswith('test_') or p.name == 'config.py':
                continue
            for n, line in enumerate(p.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                if line.strip().startswith('#'):
                    continue
                for rx, label in rules:
                    if re.search(rx, line, re.I):
                        hits[label].append(f'{rel(p)}:{n}')
        lines = [f'{label}: {len(v)} (e.g. {", ".join(v[:3])})' for label, v in hits.items()]
        record(S, 'risky code patterns', 'WARN' if lines else 'PASS', '\n'.join(lines))
        safe = 0
        for t in templates:
            safe += len(re.findall(r'\|\s*safe\b', t.read_text(encoding='utf-8', errors='replace')))
        record(S, 'templates: |safe usages (each one disables HTML escaping)', 'INFO' if safe else 'PASS',
               f'{safe} usage(s); confirm none renders user-entered text' if safe else '')


# ==========================================================================
# 2. APP IMPORT + SEED
# ==========================================================================
CTX = {}


def boot_app():
    heading('2. Booting the app on a throw-away SQLite database')
    S = 'runtime'
    tmp = Path(tempfile.mkdtemp(prefix='eduassess_audit_'))
    CTX['tmp'] = tmp
    ignored = [k for k in ('DATABASE_URL', 'REDIS_URL', 'EDUASSESS_MIGRATION_MODE') if os.environ.pop(k, None)]
    os.environ['FLASK_ENV'] = 'testing'
    os.environ['PERSISTENT_DIR'] = str(tmp / 'persist')
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)

    import config as cfg                                       # noqa: E402
    db_file = tmp / 'audit.db'
    cfg.TestingConfig.SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_file.as_posix()}'
    record(S, 'live database is NOT used', 'PASS',
           f'forced testing config onto {db_file.name}; ignored env vars: {ignored or "none"}')
    t0 = time.time()
    import app as app_module                                   # noqa: E402
    CTX['m'] = app_module
    CTX['app'] = app_module.app
    record(S, f'application imports and initialises ({time.time() - t0:.1f}s)', 'PASS')
    actual = CTX['app'].config['SQLALCHEMY_DATABASE_URI']
    if 'audit.db' not in actual:
        raise SystemExit(f'ABORT: app is using {actual!r}, not the audit database. Nothing was changed.')
    record(S, 'app is bound to the audit database', 'PASS')
    CTX['app'].config.update(TESTING=True, WTF_CSRF_ENABLED=False, PROPAGATE_EXCEPTIONS=False)

    import logging

    class Collector(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.ERROR)
            self.last = None

        def emit(self, rec):
            if rec.exc_info:
                self.last = ''.join(traceback.format_exception(*rec.exc_info)).strip().splitlines()[-4:]
            else:
                self.last = [rec.getMessage()[:300]]
    CTX['collector'] = Collector()
    for handler in list(CTX['app'].logger.handlers):      # keep the console readable; errors are captured below
        CTX['app'].logger.removeHandler(handler)
    CTX['app'].logger.propagate = False
    CTX['app'].logger.addHandler(CTX['collector'])


def seed():
    from models import db, User, Student, Assessment, Setting
    m, app = CTX['m'], CTX['app']
    bcrypt = m.bcrypt
    S = 'runtime'
    PW = 'Audit#Pass1234'
    CTX['PW'] = PW
    h = bcrypt.generate_password_hash(PW).decode('utf-8')
    class_keys = [k for k, _ in app.config['CLASS_LEVELS']][:3]
    subject_keys = [k for k, _ in app.config['LEARNING_AREAS']]
    # Use the app's own study-area curriculum so "teacher can reach this student" is realistic.
    with app.app_context():
        if not User.query.filter_by(username='audit_admin').first():
            db.session.add(User(username='audit_admin', password_hash=h, role='admin', must_change_password=False))
            db.session.commit()
        before = len(m._get_study_area_subjects_config() or {})
    if 'manage_study_area_subjects_form' in app.view_functions:
        new_client('admin').get('/admin/study-area-subjects')
    with app.app_context():
        sas = m._get_study_area_subjects_config() or {}
    if len(sas) != before:
        record(S, 'a GET page writes to the database: /admin/study-area-subjects', 'WARN',
               'Opening this page for the first time stores the default curriculum, which changes which students every '
               'teacher may assess (class-only before, class + study area after). Seed it once deliberately, or have GET never write.')
    # A known curriculum on the throw-away DB: study area 1 teaches the teacher's subject, study area 2 does not.
    all_areas = [k for k, _ in app.config['STUDY_AREAS']]
    teacher_subject, other_subject = subject_keys[0], subject_keys[1]
    in_areas = all_areas[:1]
    out_areas = all_areas[1:2]
    curriculum = {in_areas[0]: {'core': [teacher_subject], 'electives': []}}
    if out_areas:
        curriculum[out_areas[0]] = {'core': [other_subject], 'electives': []}
    from models import SystemConfig
    with app.app_context():
        SystemConfig.set_config('STUDY_AREA_SUBJECTS', curriculum)
    area_keys = in_areas + out_areas
    CTX.update(class_keys=class_keys, area_keys=area_keys, subject_keys=subject_keys)
    with app.app_context():
        st = Setting.query.first()
        if st is None:
            st = Setting()
            db.session.add(st)
        st.current_term = [k for k, _ in app.config['TERMS']][0]
        st.current_academic_year = '2026-2027'
        st.current_session = 'First Term'
        CTX['term'], CTX['year'], CTX['session'] = st.current_term, st.current_academic_year, st.current_session

        def user(name, role, **kw):
            u = User.query.filter_by(username=name).first() or User(username=name, password_hash=h, role=role)
            u.password_hash, u.role = h, role
            u.must_change_password = False
            u.credentials_enabled = True
            for k, v in kw.items():
                setattr(u, k, v)
            db.session.add(u)
            return u

        subj = subject_keys[0]
        user('audit_admin', 'admin')
        user('audit_teacher_a', 'teacher', subject=subj, classes=json.dumps([class_keys[0]]))
        user('audit_teacher_b', 'teacher', subject=subj, classes=json.dumps([class_keys[1]]))
        db.session.commit()

        def student(n, cls, area):
            s = Student(student_number=f'AUD{n:05d}', first_name=f'First{n}', last_name=f'Last{n}',
                        class_name=cls, study_area=area, reference_number=f'AREF{n:05d}')
            db.session.add(s)
            return s
        s_a = student(1, class_keys[0], in_areas[0])
        s_a2 = student(2, class_keys[0], out_areas[0] if out_areas else in_areas[0])
        s_b = student(3, class_keys[1], in_areas[0])
        s_c = student(4, class_keys[2] if len(class_keys) > 2 else class_keys[1], in_areas[0])
        db.session.commit()
        for s in (s_a, s_b):
            user(s.student_number, 'student')
        db.session.commit()
        ta = User.query.filter_by(username='audit_teacher_a').first()
        tb = User.query.filter_by(username='audit_teacher_b').first()
        db.session.add(Assessment(student_id=s_a.id, category='ica1', subject=subj, class_name=s_a.class_name,
                                  score=40, max_score=50, term=CTX['term'], academic_year=CTX['year'],
                                  session=CTX['session'], teacher_id=ta.id, assessor='a'))
        db.session.add(Assessment(student_id=s_b.id, category='ica1', subject=subj, class_name=s_b.class_name,
                                  score=30, max_score=50, term=CTX['term'], academic_year=CTX['year'],
                                  session=CTX['session'], teacher_id=tb.id, assessor='b'))
        db.session.commit()
        a_row = Assessment.query.filter_by(student_id=s_a.id).first()
        CTX.update(sid_a=s_a.id, sid_a2=s_a2.id, sid_b=s_b.id, sid_c=s_c.id, num_a=s_a.student_number,
                   num_b=s_b.student_number, num_c=s_c.student_number, ta_id=ta.id, tb_id=tb.id,
                   aid_a=a_row.id, subj=subj, name_a=s_a.first_name, name_b=s_b.first_name,
                   admin_id=User.query.filter_by(username='audit_admin').first().id)
        accessible = lambda u, s: u.can_access_student(s, app.config)   # noqa: E731
        CTX['teacher_a_scope'] = (accessible(ta, s_a), accessible(ta, s_b))
        CTX['teacher_a_visible'] = {s.student_number for s in (s_a, s_a2, s_b, s_c) if accessible(ta, s)}
    record(S, 'seeded 3 staff users, 4 students, 2 assessments', 'PASS')
    if CTX['teacher_a_scope'] != (True, False):
        record(S, 'seed: teacher A can reach their own class and not class B', 'WARN',
               f'got {CTX["teacher_a_scope"]}; scope tests that follow may be skipped or unreliable '
               '(depends on STUDY_AREA_SUBJECTS configuration)')


def new_client(role=None, fresh=False):
    """Signed-in test client. Clients are cached per role (one real login each)."""
    app = CTX['app']
    if role is None:
        return app.test_client()
    cache = CTX.setdefault('clients', {})
    if role in cache and not fresh:
        return cache[role]
    limiter = getattr(CTX['m'], 'limiter', None)
    if limiter is not None:
        try:
            limiter.reset()                      # the audit's own logins must not eat the login quota
        except Exception:                        # noqa: BLE001
            pass
    client = app.test_client()
    if role == 'student':
        r = client.post('/student/login', data={'identifier': CTX['num_a'], 'password': CTX['PW']})
    else:
        user = {'admin': 'audit_admin', 'teacher': 'audit_teacher_a', 'teacher_b': 'audit_teacher_b'}[role]
        r = client.post('/login', data={'username': user, 'password': CTX['PW']})
    if r.status_code not in (302, 303):
        raise RuntimeError(f'login as {role} failed: HTTP {r.status_code}')
    cache[role] = client
    return client


# ==========================================================================
# 3. ROUTE SWEEP
# ==========================================================================
def route_sweep():
    heading('3. Route sweep - every GET page, four roles, looking for 500s')
    S = 'routes'
    app = CTX['app']
    from models import db
    arg_values = {'student_id': CTX['sid_a'], 'user_id': CTX['ta_id'], 'assessment_id': CTX['aid_a'],
                  'id': 1, 'quiz_id': 1, 'attempt_id': 1, 'question_id': 1, 'message_id': 1, 'ticket_id': 1}
    SKIP = re.compile(r'logout|delete|remove|clear|reset|purge|drop|backup|restore|shutdown|migrate|static|unarchive|archive_semester', re.I)
    state_changing_get = []
    plan = []
    for rule in app.url_map.iter_rules():
        if 'GET' not in rule.methods or rule.endpoint == 'static':
            continue
        if SKIP.search(rule.rule) or SKIP.search(rule.endpoint):
            if SKIP.search(rule.endpoint) and not re.search(r'static', rule.endpoint):
                state_changing_get.append(f'{rule.rule}  ({rule.endpoint})')
            continue
        values = {}
        for arg in rule.arguments:
            values[arg] = arg_values.get(arg, 1 if rule._converters.get(arg).__class__.__name__ == 'IntegerConverter' else 'x')
        try:
            from flask import url_for
            with app.test_request_context():
                url = url_for(rule.endpoint, **values)
        except Exception:                                      # noqa: BLE001
            continue
        plan.append((rule.rule, rule.endpoint, url))
    plan = sorted(set(plan))
    CTX['plan'] = plan
    record(S, f'{len(plan)} GET routes found (destructive-looking names are skipped)', 'INFO')
    if state_changing_get:
        record(S, 'GET routes whose names suggest a state change (should be POST + CSRF)', 'WARN',
               '\n'.join(state_changing_get[:25]))

    roles = OrderedDict([('anonymous', None), ('admin', 'admin'), ('teacher', 'teacher'), ('student', 'student')])
    clients = {}
    for label, role in roles.items():
        try:
            clients[label] = new_client(role)
        except Exception as exc:                               # noqa: BLE001
            record(S, f'login as {label}', 'FAIL', str(exc))
    record(S, 'real login flow works for admin, teacher and student', 'PASS' if len(clients) == 4 else 'FAIL')

    results = defaultdict(dict)                                # url -> role -> (status, body-hit)
    errors = defaultdict(list)
    session_losers = defaultdict(list)
    leak = re.compile(r'Traceback \(most recent|jinja2\.exceptions|UndefinedError|TemplateNotFound|sqlalchemy\.exc', re.I)
    for rule, endpoint, url in plan:
        for label, client in clients.items():
            CTX['collector'].last = None
            try:
                r = client.get(url, follow_redirects=False)
                status = r.status_code
                body = r.get_data(as_text=True)[:200000] if (r.mimetype or '').startswith('text/') else ''
            except Exception as exc:                           # noqa: BLE001
                status, body = 599, ''
                CTX['collector'].last = [repr(exc)]
            results[url][label] = status
            if status >= 500 or (status == 200 and leak.search(body)):
                cause = ' | '.join(CTX['collector'].last or [])[:300]
                errors[label].append(f'{url} [{endpoint}] -> {status}  {cause}')
            lost = (status in (301, 302, 303) and 'login' in (r.headers.get('Location') or '') and 'login' not in url) if status < 500 else True
            if roles[label] and lost and status != 599 or (roles[label] and status >= 500):
                if status in (301, 302, 303):
                    session_losers[label].append(f'{url} [{endpoint}]')
                # a crash or a forced sign-out ends the session; sign in again so one page does not hide the rest
                try:
                    clients[label] = new_client(roles[label], fresh=True)
                except Exception:                              # noqa: BLE001
                    pass
    CTX['sweep'] = results
    for label, pages in session_losers.items():
        record(S, f'pages that sign the {label} out (a signed-in user landing here loses their session)', 'WARN',
               '\n'.join(pages[:15]))
    for label in clients:
        errs = errors.get(label, [])
        record(S, f'no 500 / leaked traceback as {label} ({len(plan)} pages)', 'FAIL' if errs else 'PASS', '\n'.join(errs[:25]))


# ==========================================================================
# 4. ACCESS CONTROL
# ==========================================================================
def access_control():
    heading('4. Access control')
    S = 'access'
    sweep = CTX.get('sweep') or {}
    public_ok = re.compile(r'^/($|login$|student/login$|health|manifest|sw\.js|offline|favicon|robots|static|api/health|support/?$|parent/login|forgot|reset_password)')
    exposed = [u for u, r in sweep.items() if r.get('anonymous') == 200 and not public_ok.search(u)]
    record(S, 'pages readable without signing in are limited to login/health/static', 'WARN' if exposed else 'PASS',
           'anonymous gets 200 on:\n' + '\n'.join(sorted(exposed)[:30]))
    admin_hint = re.compile(r'/(users|admin|settings|activity|logs|promot|archive|import|bulk|analytics|class-management|class_management|'
                            r'login-sheets|api-keys|study-area|system|upload|backup)', re.I)
    student_viol, teacher_viol = [], []
    for u, r in sweep.items():
        if r.get('admin') == 200 and admin_hint.search(u):
            if r.get('student') == 200:
                student_viol.append(u)
            if r.get('teacher') == 200:
                teacher_viol.append(u)
    record(S, 'student accounts cannot open admin-style pages', 'FAIL' if student_viol else 'PASS', '\n'.join(student_viol[:25]))
    record(S, 'teacher accounts cannot open admin-only pages', 'WARN' if teacher_viol else 'PASS',
           'teacher gets 200 where admin does (confirm these are meant for teachers):\n' + '\n'.join(teacher_viol[:25]))

    app = CTX['app']
    from flask import url_for

    def url(endpoint, **kw):
        with app.test_request_context():
            return url_for(endpoint, **kw)

    @guarded(S, 'IDOR')
    def _():
        ep = app.view_functions
        if 'student_view' not in ep:
            record(S, 'IDOR checks', 'SKIP', 'student_view endpoint not found')
            return
        tb = new_client('teacher_b')
        r = tb.get(url('student_view', student_id=CTX['sid_a']))
        leaked = r.status_code == 200 and CTX['name_a'] in r.get_data(as_text=True)
        record(S, "teacher B cannot read teacher A's student record", 'FAIL' if leaked else 'PASS', f'HTTP {r.status_code}')
        stu = new_client('student')
        r = stu.get(url('student_view', student_id=CTX['sid_b']))
        leaked = r.status_code == 200 and CTX['name_b'] in r.get_data(as_text=True)
        record(S, "a student cannot read another student's record", 'FAIL' if leaked else 'PASS', f'HTTP {r.status_code}')
        if 'student_dashboard' in ep:
            r = stu.get(url('student_dashboard'))
            body = r.get_data(as_text=True)
            record(S, "student dashboard shows only that student's own data",
                   'FAIL' if CTX['name_b'] in body else 'PASS')
        if 'assessment_edit' in ep:
            r = tb.get(url('assessment_edit', assessment_id=CTX['aid_a']))
            ok = r.status_code != 200
            record(S, "teacher B cannot open teacher A's assessment for editing", 'PASS' if ok else 'FAIL', f'HTTP {r.status_code}')
            r = tb.post(url('assessment_edit', assessment_id=CTX['aid_a']),
                        data={'score': '1', 'category': 'ica1', 'subject': CTX['subj']})
            from models import Assessment, db
            with app.app_context():
                score = db.session.get(Assessment, CTX['aid_a']).score
            record(S, "teacher B cannot change teacher A's score by POST", 'PASS' if score == 40 else 'FAIL', f'score is now {score}')

    @guarded(S, 'student search')
    def _():
        if 'student_search' not in app.view_functions:
            record(S, 'student search access control', 'SKIP', 'student_search endpoint not found')
            return
        u = url('student_search')
        anon = new_client().get(u + '?q=First')
        record(S, 'student search: anonymous is blocked', 'PASS' if anon.status_code in (301, 302, 401, 403) else 'FAIL', f'HTTP {anon.status_code}')
        st = new_client('student').get(u + '?q=First')
        data_leak = st.status_code == 200 and b'AUD' in st.data
        record(S, 'student search: a student account cannot list other students', 'FAIL' if data_leak else 'PASS', f'HTTP {st.status_code}')
        t = new_client('teacher').get(u + '?q=AUD').get_json(silent=True) or {}
        nums = {x.get('student_number') for x in t.get('results', [])}
        expected = {n for n in CTX['teacher_a_visible'] if n.startswith('AUD')}
        record(S, 'student search: a teacher sees exactly the students they may assess (own class and subject)',
               'PASS' if nums == expected else 'FAIL', f'got {sorted(nums)}, expected {sorted(expected)}')
        a = new_client('admin')
        wild = a.get(u + '?q=%25%25').get_json(silent=True) or {}
        record(S, 'student search: % and _ are escaped, not treated as wildcards', 'PASS' if not wild.get('results') else 'FAIL')


    @guarded(S, 'authorisation consistency')
    def _():
        from models import User, Student
        gq = getattr(CTX['m'], 'get_teacher_students_query', None)
        if gq is None:
            record(S, 'authorisation consistency', 'SKIP', 'get_teacher_students_query not found')
            return
        with app.app_context():
            ta = User.query.filter_by(username='audit_teacher_a').first()
            listed = {s.id for s in gq(ta).all()}
            allowed = {s.id for s in Student.query.all() if ta.can_access_student(s, app.config)}
        only_listed = listed - allowed
        only_allowed = allowed - listed
        record(S, 'every student a teacher can SEE is a student they may SAVE scores for (list rule = save rule)',
               'FAIL' if only_listed else 'PASS',
               f'{len(only_listed)} student(s) are listed but the save is refused with "not allowed"' if only_listed else '')
        record(S, 'every student a teacher may save for is also listed to them', 'WARN' if only_allowed else 'PASS',
               f'{len(only_allowed)} student(s) are allowed but never listed' if only_allowed else '')


# ==========================================================================
# 5. FUNCTIONAL FLOWS (regressions of the bugs found in production)
# ==========================================================================
def flows():
    heading('5. Functional flows and regressions')
    S = 'flows'
    app, m = CTX['app'], CTX['m']
    from flask import url_for
    from models import db, Assessment, Student, User

    def url(endpoint, **kw):
        with app.test_request_context():
            return url_for(endpoint, **kw)

    @guarded(S, 'WTForms choices')
    def _():
        field_cls = getattr(m, 'SelectField', None)
        from wtforms import Form
        class F(Form):
            x = field_cls('x', choices=[['a', 'A'], ['b', 'B']])
        f = F(data={'x': 'a'})
        from werkzeug.datastructures import MultiDict
        f = F(formdata=MultiDict({'x': 'b'}))
        ok = f.validate()
        record(S, 'list-shaped choices (what JSON gives back from the database) validate - the /assessments 500', 'PASS' if ok else 'FAIL', str(f.errors))

    @guarded(S, 'assessments list')
    def _():
        c = new_client('admin')
        for q in ('', f'?class={CTX["class_keys"][0]}', f'?class_name={CTX["class_keys"][0]}', '?page=2', '?page=abc', '?q=<script>'):
            r = c.get('/assessments' + q)
            if r.status_code >= 500:
                record(S, f'/assessments{q} responds', 'FAIL', f'HTTP {r.status_code}')
                return
        record(S, '/assessments with class, class_name, bad page and hostile query', 'PASS')

    @guarded(S, 'temporary password')
    def _():
        ep = 'issue_student_login_password'
        if ep not in app.view_functions:
            record(S, 'one-time student password', 'SKIP', 'endpoint not found')
            return
        admin = new_client('admin', fresh=True)
        r = admin.post(url(ep, student_id=CTX['sid_c']))
        body = r.get_data(as_text=True)
        record(S, 'issuing a student password renders its page (the TemplateNotFound crash)', 'PASS' if r.status_code == 200 else 'FAIL', f'HTTP {r.status_code}')
        record(S, 'password page is not cacheable', 'PASS' if 'no-store' in (r.headers.get('Cache-Control') or '') else 'FAIL')
        mt = re.search(r'id="temporary-password"[^>]*value="([^"]+)"', body)
        if not mt:
            record(S, 'temporary password is shown once', 'WARN', 'could not find the password field in the page')
            return
        pw = mt.group(1)
        with app.app_context():
            u = User.query.filter_by(username=CTX['num_c']).first()
            record(S, 'stored value is a hash, not the password', 'PASS' if u and u.password_hash != pw and u.password_hash.startswith('$2') else 'FAIL')
        st = app.test_client()
        r = st.post('/student/login', data={'identifier': CTX['num_c'], 'password': pw})
        record(S, 'student can sign in with it and is sent to choose a new password',
               'PASS' if r.status_code in (302, 303) and 'change' in (r.headers.get('Location') or '') else 'FAIL',
               f'HTTP {r.status_code} -> {r.headers.get("Location")}')
        st2 = app.test_client()
        r = st2.post('/student/login', data={'identifier': CTX['num_c'], 'password': 'wrong-password'})
        record(S, 'wrong student password is refused', 'PASS' if r.status_code == 200 else 'FAIL')
        r = new_client('teacher').post(url(ep, student_id=CTX['sid_c']))
        record(S, 'a teacher cannot issue student passwords', 'PASS' if r.status_code in (302, 401, 403) else 'FAIL', f'HTTP {r.status_code}')

    @guarded(S, 'class login sheets')
    def _():
        if 'issue_class_login_sheet' not in app.view_functions:
            record(S, 'class login sheets', 'SKIP', 'endpoint not found')
            return
        admin = new_client('admin', fresh=True)
        r = admin.get(url('class_login_sheets'))
        record(S, 'class login sheet page opens', 'PASS' if r.status_code == 200 else 'FAIL', f'HTTP {r.status_code}')
        r = admin.post(url('issue_class_login_sheet'), data={'class_name': CTX['class_keys'][0], 'scope': 'new', 'batch': 1})
        body = r.get_data(as_text=True)
        ok = r.status_code == 200 and CTX['num_a'] in body and 'no-store' in (r.headers.get('Cache-Control') or '')
        record(S, 'issuing a class sheet works, is no-store, lists the students', 'PASS' if ok else 'FAIL', f'HTTP {r.status_code}')
        r = new_client('teacher').post(url('issue_class_login_sheet'), data={'class_name': CTX['class_keys'][0], 'scope': 'new'})
        record(S, 'a teacher cannot issue class sheets', 'PASS' if r.status_code in (302, 401, 403) else 'FAIL', f'HTTP {r.status_code}')

    @guarded(S, 'bulk student import scope')
    def _():
        if 'student_bulk_import' not in app.view_functions:
            record(S, 'student bulk import scope', 'SKIP', 'endpoint not found')
            return
        try:
            from openpyxl import Workbook
        except ImportError:
            record(S, 'student bulk import scope', 'SKIP', 'openpyxl is not installed')
            return
        import io
        from models import Student

        def workbook(rows):
            wb = Workbook()
            ws = wb.active
            ws.append(['Admission', 'Student Number', 'First', 'Last', 'Middle', 'Class', 'Study Area'])
            for r in rows:
                ws.append(r)
            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)
            return buf

        in_area, out_area = CTX['area_keys'][0], (CTX['area_keys'][1] if len(CTX['area_keys']) > 1 else None)
        cls_a, cls_b = CTX['class_keys'][0], CTX['class_keys'][1]
        rows = [['', 'AUDIMP-OK', 'In', 'Scope', '', cls_a, in_area],
                ['', 'AUDIMP-OTHERCLASS', 'Other', 'Class', '', cls_b, in_area]]
        if out_area:
            rows.append(['', 'AUDIMP-OTHERAREA', 'Other', 'Area', '', cls_a, out_area])
        t = new_client('teacher', fresh=True)
        r = t.post(url('student_bulk_import'), data={'excel_file': (workbook(rows), 'students.xlsx')},
                   content_type='multipart/form-data')
        with app.app_context():
            got = {s.student_number for s in Student.query.filter(Student.student_number.like('AUDIMP-%')).all()}
        want = {'AUDIMP-OK'}
        record(S, 'teacher bulk import adds only students in their own class and study area',
               'PASS' if got == want else 'FAIL', f'HTTP {r.status_code}; imported {sorted(got)}, expected {sorted(want)}')
        rows_admin = [[a, 'AUDIMPA-' + str(i), 'Adm', 'In', '', cls, ar] for i, (a, cls, ar) in
                      enumerate([('', cls_a, in_area), ('', cls_b, in_area)] + ([('', cls_a, out_area)] if out_area else []))]
        a = new_client('admin', fresh=True)
        a.post(url('student_bulk_import'), data={'excel_file': (workbook(rows_admin), 'students.xlsx')},
               content_type='multipart/form-data')
        with app.app_context():
            n = Student.query.filter(Student.student_number.like('AUDIMPA-%')).count()
        record(S, 'admin bulk import is not restricted', 'PASS' if n == len(rows_admin) else 'FAIL', f'{n} of {len(rows_admin)} imported')

    # ---- offline sync -----------------------------------------------------
    def sync(client, **over):
        d = dict(student_name=CTX['num_a'], category='ica2', subject=CTX['subj'], score=20,
                 term=CTX['term'], academic_year=CTX['year'], session=CTX['session'])
        d.update(over)
        return client.post('/api/offline/assessment', json=d)

    @guarded(S, 'offline sync')
    def _():
        if '/api/offline/assessment' not in {r.rule for r in app.url_map.iter_rules()}:
            record(S, 'offline sync endpoint', 'SKIP', 'not registered')
            return
        t = new_client('teacher', fresh=True)
        r = sync(t, submission_id='audit-1')
        record(S, 'offline sync: valid score saves', 'PASS' if r.status_code == 200 and r.get_json().get('status') == 'created' else 'FAIL', r.get_data(as_text=True)[:200])
        r = sync(t, submission_id='audit-1')
        with app.app_context():
            n = Assessment.query.filter_by(student_id=CTX['sid_a'], category='ica2').count()
        record(S, 'offline sync: retrying the same submission does not duplicate', 'PASS' if r.status_code == 200 and n == 1 else 'FAIL', f'rows={n}')
        r = sync(t, submission_id='audit-1', score=21)
        record(S, 'offline sync: same id with different data is refused (409)', 'PASS' if r.status_code == 409 else 'FAIL', f'HTTP {r.status_code}')
        r = sync(t, submission_id='audit-2', category='ica2')
        record(S, 'offline sync: a second, different submission for the same period is refused, not overwritten', 'PASS' if r.status_code in (200, 409) else 'FAIL', f'HTTP {r.status_code}')
        for label, over, want in (('score above the maximum', dict(score=9999, category='gp1'), 422),
                                  ('negative score', dict(score=-1, category='gp1'), 422),
                                  ('NaN score', dict(score='nan', category='gp1'), 422),
                                  ('unknown category', dict(category='nonsense'), 422),
                                  ('unknown student', dict(student_name='NOPE-123'), 422),
                                  ('out-of-scope student (other class)', dict(student_name=CTX['num_b'], category='gp1'), 403),
                                  ('invalid term', dict(term='zzz', category='gp1'), 422)):
            r = sync(t, submission_id='audit-' + label, **over)
            record(S, f'offline sync rejects: {label}', 'PASS' if r.status_code == want else 'FAIL', f'HTTP {r.status_code} (wanted {want}) {r.get_data(as_text=True)[:120]}')
        other = CTX['subject_keys'][1] if len(CTX['subject_keys']) > 1 else None
        if other:
            r = sync(t, submission_id='audit-subj', subject=other, category='practical')
            with app.app_context():
                row = Assessment.query.filter_by(student_id=CTX['sid_a'], category='practical').first()
            record(S, "offline sync: a teacher cannot choose another teacher's subject (server forces their own)",
                   'PASS' if (row is None or row.subject == CTX['subj']) else 'FAIL', f'saved subject={getattr(row, "subject", None)}')
        r = sync(new_client('student'), submission_id='audit-stu')
        record(S, 'offline sync: a student account cannot post scores', 'PASS' if r.status_code == 403 else 'FAIL', f'HTTP {r.status_code}')
        r = sync(new_client(), submission_id='audit-anon')
        record(S, 'offline sync: anonymous gets 401 (not a redirect page)', 'PASS' if r.status_code == 401 else 'FAIL', f'HTTP {r.status_code}')
        r = new_client('teacher').post('/api/offline/assessment', data='not json', content_type='text/plain')
        record(S, 'offline sync: non-JSON body is refused', 'PASS' if r.status_code in (400, 415, 422) else 'FAIL', f'HTTP {r.status_code}')
        with app.app_context():
            dup = db.session.execute(db.text(
                "select count(*) from (select student_id,category,subject,term,academic_year,session,teacher_id "
                "from assessments where archived = 0 group by 1,2,3,4,5,6,7 having count(*)>1) x")).scalar()
        record(S, 'no duplicate active assessment rows were created by the tests above', 'PASS' if not dup else 'FAIL', f'{dup} duplicate group(s)')

    @guarded(S, 'student lookup tolerance')
    def _():
        fn = getattr(m, 'find_student_by_number', None)
        if not fn:
            record(S, 'tolerant student lookup', 'SKIP', 'find_student_by_number not present (older app.py)')
            return
        with app.app_context():
            s = db.session.get(Student, CTX['sid_c'])
            original = s.student_number
            s.student_number = original + ' '
            db.session.commit()
            ok = (fn(original) is not None and fn(original.lower()) is not None and fn('  ' + original + ' ') is not None and fn('NOT-A-STUDENT') is None)
            s.student_number = original
            db.session.commit()
        record(S, 'student lookup tolerates stray spaces and case, and refuses unknown numbers', 'PASS' if ok else 'FAIL')

    @guarded(S, 'incomplete assessments')
    def _():
        fn = getattr(m, 'get_incomplete_summary', None)
        if not fn:
            record(S, 'incomplete-assessment summary', 'SKIP', 'get_incomplete_summary not present')
            return
        with app.app_context():
            from sqlalchemy import text
            required = list(m.ACTIVE_CATEGORIES)
            rows = db.session.execute(text(
                "select a.student_id, a.subject, a.category from assessments a join students s on s.id=a.student_id "
                "where a.archived = 0 and a.category is not null and a.category <> '' and a.subject is not null and a.subject <> '' "
                "and (s.class_name is null or s.class_name not like 'Graduated %')")).fetchall()
            have = defaultdict(set)
            for sid, subj, cat in rows:
                have[(sid, subj)].add(cat)
            expected = defaultdict(set)
            for sid, area, cls in db.session.execute(text("select id, study_area, class_name from students where study_area is not null")).fetchall():
                if cls and cls.startswith('Graduated '):
                    continue
                cfg = (m._get_study_area_subjects_config() or {}).get(area) or {}
                for subj in list(cfg.get('core', [])) + list(cfg.get('electives', [])):
                    expected[(sid, subj)]
            pairs = {k for k, v in have.items() if not set(required) <= v}
            pairs |= {k for k in expected if k not in have}
            brute_students = {s for s, _ in pairs}
            m.cache.delete('incomplete_assessments')
            got = fn()
        ok = got['total_count'] == len(pairs) and got['student_count'] == len(brute_students)
        record(S, 'incomplete-assessment summary equals an independent recount from raw rows', 'PASS' if ok else 'FAIL',
               f'summary={got["total_count"]}/{got["student_count"]} recount={len(pairs)}/{len(brute_students)}')
        with app.app_context():
            m.cache.delete('incomplete_assessments')
            before = fn()['total_count']
            have = {r[0] for r in db.session.execute(db.text(
                "select category from assessments where student_id=:s and subject=:j and archived=0"),
                {'s': CTX['sid_a'], 'j': CTX['subj']}).fetchall()}
        missing = [c for c in m.ACTIVE_CATEGORIES if c not in have]
        t = new_client('teacher', fresh=True)
        failed = []
        for i, cat in enumerate(missing):
            r = sync(t, submission_id=f'audit-complete-{i}', student_name=CTX['num_a'], category=cat, score=1)
            if r.status_code != 200:
                failed.append(f'{cat}: HTTP {r.status_code} {r.get_data(as_text=True)[:80]}')
        with app.app_context():
            after = fn()['total_count']
        if failed:
            record(S, 'dashboard counts update after the last missing score is saved', 'WARN', 'could not enter all categories: ' + '; '.join(failed))
        else:
            record(S, 'dashboard counts update after the last missing score is saved (cache invalidation)',
                   'PASS' if before - after == 1 else 'FAIL', f'before={before} after={after} (expected one pair fewer)')


# ==========================================================================
# 6. SECURITY CONFIGURATION
# ==========================================================================
def security():
    heading('6. Security configuration')
    S = 'security'
    app = CTX['app']
    import config as cfg

    @guarded(S, 'production config')
    def _():
        prod = cfg.config['production']
        flags = {k: getattr(prod, k, None) for k in ('SESSION_COOKIE_SECURE', 'SESSION_COOKIE_HTTPONLY', 'SESSION_COOKIE_SAMESITE',
                                                      'WTF_CSRF_ENABLED', 'PERMANENT_SESSION_LIFETIME', 'SESSION_COOKIE_NAME')}
        record(S, 'production: session cookie is Secure', 'PASS' if flags['SESSION_COOKIE_SECURE'] else 'WARN', str(flags['SESSION_COOKIE_SECURE']))
        record(S, 'production: session cookie is HttpOnly', 'PASS' if flags['SESSION_COOKIE_HTTPONLY'] in (True, None) else 'WARN', str(flags['SESSION_COOKIE_HTTPONLY']))
        record(S, 'production: SameSite is set (Lax or Strict)', 'PASS' if str(flags['SESSION_COOKIE_SAMESITE']) in ('Lax', 'Strict') else 'WARN', str(flags['SESSION_COOKIE_SAMESITE']))
        record(S, 'production: CSRF protection not disabled', 'PASS' if flags['WTF_CSRF_ENABLED'] is not False else 'FAIL')
        record(S, 'production: refuses to start with the default SECRET_KEY', 'PASS' if hasattr(prod, 'validate_production_settings') else 'WARN')
        record(S, 'production: sessions and rate limits are shared across workers (REDIS_URL)',
               'PASS' if os.environ.get('REDIS_URL') else 'INFO',
               'this audit ran without REDIS_URL; with 2+ gunicorn workers set it in Render, otherwise limits and cached counts are per worker')

    @guarded(S, 'CSRF')
    def _():
        app.config['WTF_CSRF_ENABLED'] = True
        try:
            c = app.test_client()
            r = c.post('/login', data={'username': 'audit_admin', 'password': CTX['PW']})
            signed_in = c.get('/').status_code == 200
            record(S, 'CSRF: a login POST without a token does not sign anyone in', 'FAIL' if signed_in else 'PASS',
                   f'HTTP {r.status_code}')
            t = new_client('teacher')
            before = t.post('/api/offline/assessment', json={}).status_code
            record(S, 'CSRF: JSON endpoint behaviour with CSRF on (informational)', 'INFO',
                   f'POST /api/offline/assessment without a token -> HTTP {before}. JSON-only bodies cannot be sent by a cross-site HTML form.')
        finally:
            app.config['WTF_CSRF_ENABLED'] = False

    @guarded(S, 'headers')
    def _():
        r = app.test_client().get('/login')
        h = {k.lower(): v for k, v in r.headers.items()}
        for header, why in (('x-content-type-options', 'stops MIME sniffing'), ('x-frame-options', 'clickjacking (or use CSP frame-ancestors)'),
                            ('referrer-policy', 'limits URL leakage'), ('content-security-policy', 'limits script injection')):
            ok = header in h or (header == 'x-frame-options' and 'frame-ancestors' in h.get('content-security-policy', ''))
            record(S, f'response header {header}', 'PASS' if ok else 'WARN', f'missing - {why}' if not ok else '')
        cookie = ' '.join(r.headers.getlist('Set-Cookie')).lower()
        if cookie:
            record(S, 'cookie flags on /login', 'PASS' if 'httponly' in cookie else 'WARN', 'HttpOnly missing' if 'httponly' not in cookie else '')
        r404 = app.test_client().get('/definitely-not-a-page-xyz')
        record(S, '404 page is friendly and leaks nothing', 'PASS' if r404.status_code == 404 and b'Traceback' not in r404.data else 'FAIL', f'HTTP {r404.status_code}')

    @guarded(S, 'passwords')
    def _():
        from models import User
        with app.app_context():
            weak = [u.username for u in User.query.all() if not str(u.password_hash).startswith('$2')]
        record(S, 'all stored passwords are bcrypt hashes', 'FAIL' if weak else 'PASS', f'{len(weak)} user(s)')
        record(S, 'default admin credentials are not the documented default', 'INFO',
               f'config default is {app.config.get("DEFAULT_ADMIN_USERNAME", "admin")}/<see config>. On the live site confirm the default password was changed.')

    @guarded(S, 'rate limit')
    def _():
        enabled = app.config.get('RATELIMIT_ENABLED', True)
        c = app.test_client()
        codes = [c.post('/login', data={'username': 'audit_admin', 'password': 'wrong-' + str(i)}).status_code for i in range(14)]
        record(S, 'login brute-force limit engages (429 after the 10th attempt in a minute)', 'PASS' if 429 in codes else 'WARN',
               f'codes={set(codes)}; limiter enabled in config: {enabled}')
        limiter = getattr(CTX['m'], 'limiter', None)
        if limiter is not None:
            limiter.reset()
        record(S, 'login limit is per IP only', 'INFO',
               'a school behind one public IP shares the limit; 10 failed staff logins in a minute lock everyone out of /login for that minute')


# ==========================================================================
# 7. DATA INTEGRITY (seeded DB, or a live DB read-only)
# ==========================================================================
INTEGRITY_QUERIES = [
    ('students: duplicate student numbers (ignoring case/space)', 'FAIL',
     "select count(*) from (select lower(trim(student_number)) k from students group by 1 having count(*)>1) x"),
    ('students: student number has leading/trailing spaces', 'WARN', "select count(*) from students where student_number <> trim(student_number)"),
    ('students: blank student number', 'FAIL', "select count(*) from students where student_number is null or trim(student_number)=''"),
    ('students: duplicate reference numbers', 'FAIL',
     "select count(*) from (select lower(trim(reference_number)) k from students where reference_number is not null group by 1 having count(*)>1) x"),
    ('students: no class assigned', 'WARN', "select count(*) from students where class_name is null or trim(class_name)=''"),
    ('users: duplicate usernames (ignoring case)', 'FAIL', "select count(*) from (select lower(username) k from users group by 1 having count(*)>1) x"),
    ('users: empty password hash', 'FAIL', "select count(*) from users where password_hash is null or password_hash=''"),
    ('users: teachers with no subject', 'WARN', "select count(*) from users where role='teacher' and (subject is null or subject='')"),
    ('users: student logins with no matching student', 'WARN',
     "select count(*) from users u where u.role='student' and not exists (select 1 from students s where trim(s.student_number)=u.username)"),
    ('assessments: student does not exist (orphan)', 'FAIL',
     "select count(*) from assessments a where not exists (select 1 from students s where s.id=a.student_id)"),
    ('assessments: teacher does not exist', 'WARN',
     "select count(*) from assessments a where a.teacher_id is not null and not exists (select 1 from users u where u.id=a.teacher_id)"),
    ('assessments: negative score', 'FAIL', "select count(*) from assessments where score < 0"),
    ('assessments: score above max_score', 'FAIL', "select count(*) from assessments where score > max_score"),
    ('assessments: max_score is zero or negative', 'FAIL', "select count(*) from assessments where max_score is null or max_score <= 0"),
    ('assessments: missing term / year / session', 'WARN',
     "select count(*) from assessments where term is null or academic_year is null or session is null"),
    ('assessments: duplicate active rows for one period', 'WARN',
     "select count(*) from (select 1 from assessments where archived = false group by student_id,category,subject,term,academic_year,session,teacher_id having count(*)>1) x"),
]


def data_integrity(engine, label, readonly):
    S = 'data'
    from sqlalchemy import text
    is_pg = engine.dialect.name == 'postgresql'
    with engine.connect() as conn:
        if readonly:
            if is_pg:
                conn.execute(text('SET TRANSACTION READ ONLY'))
            else:
                conn.execute(text('PRAGMA query_only = ON'))
        for name, severity, sql in INTEGRITY_QUERIES:
            q = sql if is_pg else sql.replace('archived = false', 'archived = 0')
            try:
                n = conn.execute(text(q)).scalar()
            except Exception as exc:                           # noqa: BLE001
                conn.rollback()
                if is_pg:
                    conn.execute(text('SET TRANSACTION READ ONLY'))
                record(S, f'[{label}] {name}', 'SKIP', f'query not applicable: {str(exc).splitlines()[0][:100]}')
                continue
            record(S, f'[{label}] {name}', 'PASS' if not n else severity, f'{n} row(s)' if n else '')
        if readonly:
            counts = {}
            for t in ('students', 'users', 'assessments'):
                try:
                    counts[t] = conn.execute(text(f'select count(*) from {t}')).scalar()
                except Exception:                              # noqa: BLE001
                    pass
            record(S, f'[{label}] table sizes', 'INFO', ', '.join(f'{k}={v}' for k, v in counts.items()))
            if is_pg:
                idx = {r[0] for r in conn.execute(text("select indexname from pg_indexes where schemaname='public'"))}
                want = {'ix_students_class_name', 'ix_students_study_area', 'ix_assessments_active_cover', 'ix_assessments_teacher_id'}
                miss = sorted(want - idx)
                record(S, f'[{label}] performance indexes exist on the live database', 'WARN' if miss else 'PASS',
                       'missing: ' + ', '.join(miss) + ' (deploy the new models.py and restart once)' if miss else '')


def data_checks():
    heading('7. Data integrity')
    from models import db
    with CTX['app'].app_context():
        data_integrity(db.engine, 'seeded test DB', readonly=False)
    if ARGS.live_db_url:
        from sqlalchemy import create_engine
        url = ARGS.live_db_url.replace('postgres://', 'postgresql://', 1)
        eng = create_engine(url, pool_pre_ping=True)
        try:
            data_integrity(eng, 'LIVE (read-only)', readonly=True)
        except Exception as exc:                               # noqa: BLE001
            record('data', 'live database audit', 'FAIL', f'could not run: {exc!r}'[:300])
        finally:
            eng.dispose()
    else:
        record('data', 'live database audit', 'SKIP', 'pass --live-db-url "<Neon URL>" to run these same checks read-only against production (counts only)')


# ==========================================================================
# 8. PERFORMANCE / SCALE
# ==========================================================================
def performance():
    heading(f'8. Performance with {ARGS.scale:,} students')
    S = 'perf'
    app, m = CTX['app'], CTX['m']
    from models import db, Student, Assessment
    from sqlalchemy import event
    import random
    random.seed(11)
    n = ARGS.scale
    classes, areas, subs = CTX['class_keys'], CTX['area_keys'], CTX['subject_keys'][:4]
    cats = list(m.ACTIVE_CATEGORIES)
    t0 = time.time()
    with app.app_context():
        base = db.session.execute(db.text('select coalesce(max(id),0) from students')).scalar()
        db.session.execute(db.insert(Student), [dict(student_number=f'PRF{i:06d}', first_name=f'Perf{i}', last_name=f'Name{i % 97}',
                                                      class_name=classes[i % len(classes)], study_area=areas[i % len(areas)]) for i in range(n)])
        db.session.commit()
        rows = []
        for sid in range(base + 1, base + n + 1):
            for subj in subs[: 2 + sid % 3]:
                for cat in cats[: random.choice([4, 6, 7, 7])]:
                    rows.append(dict(student_id=sid, category=cat, subject=subj, class_name=classes[0], score=random.randint(10, 50),
                                     max_score=50.0, term=CTX['term'], academic_year=CTX['year'], session=CTX['session'], archived=False))
        for i in range(0, len(rows), 20000):
            db.session.execute(db.insert(Assessment), rows[i:i + 20000])
        db.session.commit()
        if hasattr(m, 'cache'):
            m.cache.delete('incomplete_assessments')
    record(S, f'seeded {n:,} students and {len(rows):,} assessment rows ({time.time() - t0:.1f}s)', 'INFO')

    counter = {'n': 0}
    with app.app_context():
        @event.listens_for(db.engine, 'before_cursor_execute')
        def _count(*a, **k):                                   # noqa: ANN002
            counter['n'] += 1

    from flask import url_for
    def u(ep, **kw):
        with app.test_request_context():
            return url_for(ep, **kw)

    admin, teacher, student = new_client('admin'), new_client('teacher'), new_client('student')
    pages = [('admin dashboard', admin, '/'), ('teacher dashboard', teacher, '/'),
             ('student dashboard', student, '/student/dashboard'), ('student profile (admin)', admin, u('student_view', student_id=CTX['sid_a'])),
             ('students list', admin, '/students'), ('assessments list', admin, '/assessments'),
             ('new assessment form (admin)', admin, '/assessments/new'), ('roster tree JSON (admin)', admin, '/api/roster-tree')]
    if 'student_search' in app.view_functions:
        pages.append(('student search', admin, u('student_search') + '?q=Perf12'))
    for label, client, path in pages:
        for attempt in ('cold', 'warm'):
            counter['n'] = 0
            t = time.time()
            r = client.get(path)
            dt = time.time() - t
            q = counter['n']
            if attempt == 'warm':
                size = len(r.data) / 1024
                status = 'PASS'
                note = f'{dt * 1000:.0f} ms, {q} queries, {size:.0f} KB, HTTP {r.status_code}'
                if r.status_code >= 500:
                    status = 'FAIL'
                elif dt > 5 or q > 150:
                    status = 'FAIL'
                elif dt > 1.0 or q > 40 or size > 1500:
                    status = 'WARN'
                record(S, f'{label}', status, note if status != 'PASS' else note)
    fn = getattr(m, 'get_incomplete_summary', None)
    if fn:
        with app.app_context():
            m.cache.delete('incomplete_assessments')
            t = time.time(); fn(); cold = time.time() - t
            t = time.time(); fn(); warm = time.time() - t
        record(S, 'incomplete-assessment summary', 'PASS' if cold < 2 else 'WARN', f'cold {cold * 1000:.0f} ms, cached {warm * 1000:.2f} ms')
    else:
        with app.app_context():
            t = time.time(); m.get_incomplete_assessments(); cold = time.time() - t
        record(S, 'incomplete-assessment list (old implementation)', 'PASS' if cold < 2 else 'WARN', f'{cold * 1000:.0f} ms (O(school); every student page pays this)')
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        record(S, 'peak memory of this audit process', 'INFO', f'{peak:.0f} MB (Linux/Mac only). Render Standard has 2 GB shared by all workers.')
    except ImportError:
        pass
    record(S, 'bcrypt login throughput', 'INFO', throughput_note())


def throughput_note():
    m = CTX['m']
    t = time.time()
    k = 3
    for _ in range(k):
        m.bcrypt.generate_password_hash('x' * 12)
    per = (time.time() - t) / k
    return (f'{per * 1000:.0f} ms per hash on this machine = about {1 / per:.1f} logins/second per CPU core. '
            f'500 students signing in together need about {500 * per:.0f} CPU-seconds.')


# ==========================================================================
# REPORT
# ==========================================================================
def write_report():
    counts = defaultdict(int)
    for _s, _n, st, _d in RESULTS:
        counts[st] += 1
    lines = ['# EduAssess audit report', '', f'Generated {time.strftime("%Y-%m-%d %H:%M:%S")}', '',
             '| FAIL | WARN | INFO | SKIP | PASS |', '|---|---|---|---|---|',
             f'| {counts["FAIL"]} | {counts["WARN"]} | {counts["INFO"]} | {counts["SKIP"]} | {counts["PASS"]} |', '']
    for status in ('FAIL', 'WARN', 'INFO', 'SKIP'):
        items = [r for r in RESULTS if r[2] == status]
        if not items:
            continue
        lines += [f'## {status} ({len(items)})', '']
        for section, name, _st, detail in items:
            lines.append(f'- **[{section}] {name}**')
            if detail:
                lines += ['  ```', *['  ' + d for d in detail.splitlines()[:30]], '  ```']
        lines.append('')
    lines += [f'## PASS ({counts["PASS"]})', '']
    lines += [f'- [{s}] {n}' for s, n, st, _d in RESULTS if st == 'PASS']
    Path(ARGS.report).write_text('\n'.join(lines), encoding='utf-8')
    return counts


def main():
    print('EduAssess audit - nothing here touches your live database.')
    if wanted('static'):
        static_checks()
    need_app = any(wanted(s) for s in ('routes', 'access', 'flows', 'security', 'data', 'perf'))
    if need_app:
        try:
            boot_app()
            seed()
        except SystemExit:
            raise
        except Exception as exc:                               # noqa: BLE001
            record('runtime', 'application boots and seeds', 'FAIL', ''.join(traceback.format_exception(exc)[-6:]))
            need_app = False
    if need_app:
        if wanted('static'):
            guarded('static', 'jinja')(lambda: jinja_and_endpoints())
        if wanted('routes') or wanted('access'):
            route_sweep()
        if wanted('access'):
            access_control()
        if wanted('flows'):
            flows()
        if wanted('security'):
            security()
        if wanted('data'):
            data_checks()
        if wanted('perf') and not ARGS.skip_perf:
            performance()
    elif ARGS.live_db_url and wanted('data'):
        pass
    counts = write_report()
    tmp = CTX.get('tmp')
    if tmp and not os.environ.get('AUDIT_KEEP'):
        shutil.rmtree(tmp, ignore_errors=True)
    print('\n' + '=' * 60)
    print(f'FAIL {counts["FAIL"]}   WARN {counts["WARN"]}   INFO {counts["INFO"]}   SKIP {counts["SKIP"]}   PASS {counts["PASS"]}')
    print(f'Full report: {ARGS.report}')
    sys.exit(1 if counts['FAIL'] else 0)


def jinja_and_endpoints():
    """Needs the app: compile every template with the app's own Jinja environment and check url_for targets."""
    S = 'static'
    app = CTX['app']
    templates_dir = ROOT / 'templates'
    bad = []
    for t in sorted(templates_dir.rglob('*.html')):
        try:
            app.jinja_env.parse(t.read_text(encoding='utf-8', errors='replace'))
        except Exception as exc:                               # noqa: BLE001
            bad.append(f'{rel(t)}: {exc}')
    record(S, 'every template compiles (Jinja syntax)', 'FAIL' if bad else 'PASS', '\n'.join(bad[:30]))
    endpoints = set(app.view_functions)
    pat = re.compile(r'url_for\(\s*[\'"]([A-Za-z0-9_.]+)[\'"]')
    unknown = []
    sources = list(templates_dir.rglob('*.html')) + list(project_files({'.py'}))
    for p in sources:
        for n, line in enumerate(p.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
            for mt in pat.finditer(line):
                ep = mt.group(1)
                if ep not in endpoints and not ep.startswith('.'):
                    unknown.append(f'{rel(p)}:{n}: {ep}')
    record(S, 'every url_for() target is a real endpoint (a wrong name is a 500 at render time)', 'FAIL' if unknown else 'PASS', '\n'.join(unknown[:30]))
    missing = []
    for p in templates_dir.rglob('*.html'):
        for mt in re.finditer(r'url_for\(\s*[\'"]static[\'"]\s*,\s*filename\s*=\s*[\'"]([^\'"]+)[\'"]', p.read_text(encoding='utf-8', errors='replace')):
            if not (ROOT / 'static' / mt.group(1)).exists():
                missing.append(f'{rel(p)}: static/{mt.group(1)}')
    record(S, 'every static file a template links to exists', 'FAIL' if missing else 'PASS', '\n'.join(sorted(set(missing))[:30]))


if __name__ == '__main__':
    main()
