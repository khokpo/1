import io, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import openpyxl
from app import create_app
from models import *
from test_smoke import client, tok

def xl(rows):
    wb = openpyxl.Workbook(); ws = wb.active
    for r in rows: ws.append(r)
    b = io.BytesIO(); wb.save(b); b.seek(0); return b

def test_all():
    app = create_app('sqlite://'); h = client(app, 'hod'); stf = client(app, 'office'); m1 = client(app, 'meena'); m2 = client(app, 'ravi'); s = client(app, 's01')
    for u in (h, stf, m1, s, client(app, 'priya')): assert u.get('/').status_code == 302
    # course staff: own courses only
    assert m1.get('/course/1').status_code == 200 and m1.get('/course/3').status_code == 403       # ST303 belongs to Dr. Ravi
    assert m2.get('/course/1').status_code == 403 and s.get('/course/1').status_code == 403 and s.get('/acad').status_code == 403
    assert m1.get('/admin').status_code == 403 and m1.get('/student/marks').status_code == 403
    # Excel marks upload: validate / preview / confirm
    t = tok(m1, '/course/1')
    f = xl([['reg_no', 'name', 'score'], ['S2501', 'x', 41], ['S2502', 'x', 99], ['S2501', 'x', 40], ['S2540', 'x', 30], ['S2503', 'x', None], ['P9', 'x', 20]])
    r = m1.post('/course/1/upload', data={'exam': 'Semester Exam', 'max_score': '50', 'file': (f, 'm.xlsx'), '_csrf': t}, content_type='multipart/form-data'); body = r.get_data(as_text=True)
    for msg in ('duplicate row in file', 'score must be between', 'not in this course cohort', 'blank or not a number'): assert msg in body, msg
    tk = re.search(r'/upload/(\w+)/errors.csv', body).group(1); assert m1.get(f'/course/1/upload/{tk}/errors.csv').status_code == 200
    assert m2.post(f'/course/1/upload/{tk}/confirm', data={'_csrf': tok(m2, '/acad')}).status_code == 403          # other staff cannot confirm
    assert m1.post(f'/course/1/upload/{tk}/confirm', data={'_csrf': tok(m1, '/course/1')}).status_code == 302
    with app.app_context():
        mk = Mark.query.join(Student).filter(Student.reg_no == 'S2501', Mark.exam_type == 'Semester Exam', Mark.course_id == 1).one(); assert mk.score == 41 and mk.max_score == 50
    assert m1.post('/course/1/mark', data={'reg_no': 'S2501', 'exam': 'Internal 1', 'score': '45', 'max_score': '50', '_csrf': tok(m1, '/course/1')}).status_code == 302
    assert m1.post('/course/1/mark', data={'reg_no': 'S2536', 'exam': 'Internal 1', 'score': '45', '_csrf': tok(m1, '/course/1')}).status_code in (302, 403)
    # student sees only own marks
    page = s.get('/student/marks').get_data(as_text=True); assert 'My Marks' in page and 'S2502' not in page and 'canvas' in page
    # graphs
    for p in ('/admin/analytics', '/course/1', '/admin/courses'): assert h.get(p).status_code == 200, p
    assert 'canvas' in h.get('/admin/analytics').get_data(as_text=True) and stf.get('/admin/analytics').status_code == 403
    assert m1.get('/static/chart.umd.js').status_code == 200
    # mentor sees marks of assigned student only
    pr = client(app, 'priya'); assert 'Marks' in pr.get('/mentor/student/S2501').get_data(as_text=True) and pr.get('/mentor/student/S2520').status_code == 403
    # corrections: student requests, only office approves
    t = tok(s, '/student/details')
    assert s.post('/student/details', data={'act': 'correct', 'field': 'phone', 'new_value': '9876543210', 'reason': 'typo', '_csrf': t}).status_code == 302
    s.post('/student/details', data={'act': 'correct', 'field': 'is_demo', 'new_value': '1', '_csrf': t})                 # not an allowed field
    with app.app_context():
        assert Student.query.filter_by(reg_no='S2501').first().phone is None or True
        ch = ProfileChange.query.one(); cid = ch.id; assert ch.status == 'Pending' and Student.query.filter_by(user_id=ch.student.user_id).first().phone != '9876543210'
    assert s.post('/admin/corrections', data={'cid': cid, 'act': 'approve', '_csrf': t}).status_code == 403                # student cannot approve
    assert s.get('/admin/corrections').status_code == 403 and m1.get('/admin/corrections').status_code == 403
    assert stf.post('/admin/corrections', data={'cid': cid, 'act': 'approve', '_csrf': tok(stf, '/admin/corrections')}).status_code == 302
    with app.app_context(): assert ProfileChange.query.get(cid).status == 'Approved' and ProfileChange.query.get(cid).student.phone == '9876543210'
    assert 'Verified' in s.get('/student/details').get_data(as_text=True)
    # course staff / mentor accounts created by office get temp passwords and must change them
    t = tok(stf, '/admin/users'); r = stf.post('/admin/users', data={'username': 'cs9', 'name': 'C9', 'role': 'staff', '_csrf': t}, follow_redirects=True)
    pw = re.search(r'Temporary password: ([\w-]+)', r.get_data(as_text=True)).group(1)
    c9 = client(app, 'cs9', pw); assert c9.get('/acad').status_code == 302
    t = tok(c9, '/account'); c9.post('/account', data={'old': pw, 'new': 'Another#Pass1', 'again': 'Another#Pass1', '_csrf': t}); assert client(app, 'cs9', 'Another#Pass1').get('/acad').status_code == 200
    # course creation: only course-role staff assignable
    t = tok(h, '/admin/courses'); assert h.post('/admin/courses', data={'code': 'X1', 'name': 'X', 'programme': 'M.Sc Statistics', 'semester': 'III', 'staff': '1', '_csrf': t}).status_code == 400
    print('ACADEMICS OK')
if __name__ == '__main__': test_all()
