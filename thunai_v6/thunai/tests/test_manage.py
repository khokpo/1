import io, os, re, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import openpyxl
from app import create_app
from models import Student, AcademicRecord, User, MentorAssignment
from test_smoke import client, tok

def xlsx(rows):
    wb = openpyxl.Workbook(); ws = wb.active
    for r in rows: ws.append(r)
    b = io.BytesIO(); wb.save(b); b.seek(0); return b

def test_manage():
    app = create_app('sqlite://'); h = client(app, 'hod'); st = client(app, 'office')
    for p in ['/admin/students', '/admin/students/S2501', '/admin/users', '/admin/groups/1', '/admin/upload', '/admin/requests', '/admin/settings', '/account']:
        assert h.get(p).status_code == 200, p
    for p in ['/admin/students', '/admin/users', '/admin/upload', '/admin/requests']: assert st.get(p).status_code == 200, p
    assert st.post('/admin/settings', data={'confirm': 'REMOVE DEMO', '_csrf': tok(st, '/admin/settings')}).status_code == 403   # only HOD may remove demo data
    # add + edit student
    t = tok(h, '/admin/students'); assert h.post('/admin/students/new', data={'reg_no': 'p252701', 'name': 'Arun K', '_csrf': t}).status_code == 302
    t = tok(h, '/admin/students/P252701')
    h.post('/admin/students/P252701', data={'name': 'Arun Kumar', 'programme': 'M.Sc Statistics', 'semester': 'III', 'email': 'a@x.com', 'phone': '1', 'address': 'x', '_csrf': t})
    h.post('/admin/students/P252701/record', data={'period': '1', 'attendance': '80', 'assessment': '70', 'assignment_pct': '90', 'late': '0', '_csrf': t})
    assert h.post('/admin/students/P252701/record', data={'period': '2', 'attendance': '180', 'assessment': '70', 'assignment_pct': '90', '_csrf': t}).status_code == 302
    with app.app_context():
        s = Student.query.filter_by(reg_no='P252701').first(); assert s.name == 'Arun Kumar' and AcademicRecord.query.filter_by(student_id=s.id).count() == 1
    # staff cannot delete
    assert st.post('/admin/students/P252701/delete', data={'confirm': 'P252701', '_csrf': tok(st, '/admin/students')}).status_code == 403
    # users: staff cannot create hod
    t = tok(st, '/admin/users'); st.post('/admin/users', data={'username': 'evil', 'name': 'E', 'role': 'hod', '_csrf': t})
    st.post('/admin/users', data={'username': 'newmentor', 'name': 'New M', 'role': 'staff', '_csrf': t})
    with app.app_context(): assert not User.query.filter_by(username='evil').first() and User.query.filter_by(username='newmentor').first()
    # excel upload with errors/duplicates
    t = tok(h, '/admin/upload')
    r = h.post('/admin/upload', data={'kind': 'students', 'file': (xlsx([['reg_no', 'name', 'semester'], ['Q1', 'A', 'III'], ['Q2', ''], ['Q1', 'Dup'], ['P252701', 'Upd']]), 'a.xlsx'), '_csrf': t}, content_type='multipart/form-data')
    body = r.get_data(as_text=True); assert 'Upload preview' in body and 'duplicate row in file' in body and 'name missing' in body
    tk = re.search(r'/admin/upload/(\w+)/errors.csv', body).group(1); assert h.get(f'/admin/upload/{tk}/errors.csv').status_code == 200
    assert st.get(f'/admin/upload/{tk}/errors.csv').status_code == 403   # other user cannot read someone else's job
    rc = h.post(f'/admin/upload/{tk}/confirm', data={'_csrf': tok(h, '/admin/upload')}); assert rc.status_code == 302
    page = h.get(rc.headers['Location']).get_data(as_text=True); codes = re.findall(r'<code>([^<]+)</code>', page)
    PW = codes[codes.index('q1') + 1]; assert 'Shown only once' in page
    assert 'already shown' in h.get(rc.headers['Location'], follow_redirects=True).get_data(as_text=True)   # one-time sheet
    with app.app_context(): assert Student.query.filter_by(reg_no='Q1').first()
    bad = h.post('/admin/upload', data={'kind': 'students', 'file': (io.BytesIO(b'notexcel'), 'a.xlsx'), '_csrf': t}, content_type='multipart/form-data'); assert bad.status_code == 302
    # student profile + photo
    from werkzeug.security import check_password_hash
    qc = app.test_client(); tk0 = re.search(r'name="_csrf" value="(\w+)"', qc.get('/login').get_data(as_text=True)).group(1)
    qc.post('/login', data={'username': 'q1', 'password': PW, 'category': 'student', '_csrf': tk0})
    assert qc.get('/student/profile').status_code == 302     # forced to change the temporary password first
    t = tok(qc, '/account'); qc.post('/account', data={'old': PW, 'new': 'MyNewPass#1', 'again': 'MyNewPass#1', '_csrf': t})
    q = client(app, 'q1', 'MyNewPass#1'); t = tok(q, '/student/profile')
    png = b'\x89PNG\r\n\x1a\n' + b'0' * 100
    assert q.post('/student/profile', data={'bio': 'Hi', 'phone': '9', 'photo': (io.BytesIO(png), 'me.png'), '_csrf': t}, content_type='multipart/form-data').status_code == 302
    assert q.get('/photo/Q1').status_code == 200 and client(app, 's01').get('/photo/Q1').status_code == 403
    assert q.post('/student/profile', data={'photo': (io.BytesIO(b'<script>'), 'x.png'), '_csrf': t}, content_type='multipart/form-data').status_code == 302
    assert q.get('/student/requests').status_code == 200 and q.get('/admin/students').status_code == 403
    # change password
    # group mentor change keeps history; remove demo
    t = tok(h, '/admin/groups/1'); h.post('/admin/groups/1', data={'name': 'G', 'programme': 'P', 'year': '2026-27', 'semester': 'III', 'mentor': '4', 'status': 'active', 'description': '', 'reason': 'x', '_csrf': t})
    with app.app_context(): assert MentorAssignment.query.filter(MentorAssignment.end_date.isnot(None)).count() >= 15
    h.post('/admin/settings', data={'confirm': 'REMOVE DEMO', '_csrf': tok(h, '/admin/settings')})
    with app.app_context(): assert Student.query.filter_by(is_demo=True).count() == 0 and Student.query.filter_by(reg_no='Q1').first()
    assert h.get('/admin').status_code == 200 and h.get('/admin/workload').status_code == 200
    print('MANAGE OK')

def test_migration():
    d = tempfile.mkdtemp(); p = os.path.join(d, 'old.db'); import sqlite3
    c = sqlite3.connect(p); c.executescript("CREATE TABLE student(id INTEGER PRIMARY KEY,user_id INT,reg_no VARCHAR(20),name VARCHAR(80),programme VARCHAR(60),semester VARCHAR(5),created DATE);"
        "CREATE TABLE user(id INTEGER PRIMARY KEY,username VARCHAR(40),name VARCHAR(80),role VARCHAR(10),pw_hash VARCHAR(255));"
        "INSERT INTO user VALUES(1,'hod','H','hod','x');INSERT INTO student VALUES(1,NULL,'S1','A','P','III',NULL);"); c.commit(); c.close()
    app = create_app('sqlite:///' + p)
    with app.app_context(): assert Student.query.first().bio is None and User.query.count() == 1
    print('MIGRATION OK')
if __name__ == '__main__': test_manage(); test_migration()
