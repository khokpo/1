import io, os, re, sys, sqlite3, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import openpyxl
from app import create_app
from models import *
from test_smoke import client, tok

def xl(rows):
    wb = openpyxl.Workbook(); ws = wb.active
    for r in rows: ws.append(r)
    b = io.BytesIO(); wb.save(b); b.seek(0); return b

def anon(app):
    c = app.test_client(); t = re.search(r'name="_csrf" value="(\w+)"', c.get('/login').get_data(as_text=True)).group(1); return c, t

def test_roles():
    app = create_app('sqlite://'); h = client(app, 'hod'); o = client(app, 'office')
    # login categories: four only, and the account must match the chosen category
    page = anon(app)[0].get('/login').get_data(as_text=True)
    assert all(x in page for x in ('Student', 'Teacher', 'Mentor', 'Staff', 'HOD', 'Office', 'Responsible use', 'Forgot password', 'Show'))
    c, t = anon(app); r = c.post('/login', data={'username': 'priya', 'password': 'demo123', 'category': 'hod', '_csrf': t}); assert r.status_code == 200 and b'cannot sign in to the HOD portal' in r.data
    c, t = anon(app); assert c.post('/login', data={'username': 'PRIYA', 'password': 'wrong', 'category': 'staff', '_csrf': t}).status_code == 200
    c, t = anon(app); assert c.post('/login', data={'username': 'meena', 'password': 'demo123', 'category': 'staff', '_csrf': t}).status_code == 302
    assert app.config['PERMANENT_SESSION_LIFETIME'].total_seconds() == 1800
    # Staff without mentor responsibility: no mentorship, no menu; Office assigns -> appears
    m = client(app, 'meena'); assert m.get('/mentor').status_code == 403 and 'Mentorship' not in m.get('/staff').get_data(as_text=True)
    with app.app_context():
        meena = User.query.filter_by(username='meena').first().id; ids = [s.id for s in Student.query.filter(Student.reg_no.in_(['S2536', 'S2537'])).all()]
    t = tok(o, '/admin/groups'); o.post('/admin/groups', data={'name': 'Meena Group', 'programme': 'M.Sc Statistics', 'year': '2026-27', 'semester': 'III', 'mentor': str(meena), '_csrf': t})
    with app.app_context(): gid = MentorGroup.query.filter_by(name='Meena Group').first().id
    assert m.get('/mentor/student/S2536').status_code == 403
    t = tok(o, '/admin/assign'); o.post('/admin/assign', data={'mentor': str(meena), 'group': str(gid), 'students': ids, 'confirmed': '1', 'reason': 'x', '_csrf': t})
    assert m.get('/mentor').status_code == 200 and m.get('/mentor/student/S2536').status_code == 200 and m.get('/mentor/student/S2501').status_code == 403
    assert 'Mentorship' in m.get('/staff').get_data(as_text=True)
    # Permissions: priya teaches ST304 (id 4); meena does not -> no attendance / marks for it
    p = client(app, 'priya'); assert p.get('/staff/attendance?course=4').status_code == 200 and m.get('/staff/attendance?course=4').status_code == 403
    assert m.get('/course/4').status_code == 403
    t = tok(p, '/staff/attendance?course=4'); assert p.post('/staff/attendance', data={'course': '4', 'date': '2026-09-01', 'present': ['S2501'], '_csrf': t}).status_code == 302
    with app.app_context(): assert CourseAttendance.query.filter_by(course_id=4, on_date=__import__('datetime').date(2026, 9, 1), present=True).count() == 1
    assert p.get('/staff/attendance-sheet?course=4').status_code == 200 and m.get('/staff/attendance-sheet?course=4').status_code == 403
    # new staff: teacher of a course but no marks permission -> upload denied (server side); exam-scoped grant
    t = tok(o, '/admin/users'); r = o.post('/admin/users', data={'username': 'newstaff', 'name': 'New Staff', 'role': 'staff', '_csrf': t}, follow_redirects=True)
    pw = re.search(r'Temporary password: ([\w-]+)', r.get_data(as_text=True)).group(1)
    n0 = client(app, 'newstaff', pw); t = tok(n0, '/account'); n0.post('/account', data={'old': pw, 'new': 'Strong#Pass1', 'again': 'Strong#Pass1', '_csrf': t}); n = client(app, 'newstaff', 'Strong#Pass1')
    with app.app_context(): nid = User.query.filter_by(username='newstaff').first().id
    t = tok(o, f'/admin/staff/{nid}'); o.post(f'/admin/staff/{nid}', data={'act': 'assign_course', 'course_id': '5', '_csrf': t})   # AM301
    assert n.get('/course/5').status_code == 200 and 'Upload marks (Excel)' not in n.get('/course/5').get_data(as_text=True)
    f = lambda: xl([['reg_no', 'score'], ['S2531', 20]])
    t = tok(n, '/staff/requests'); assert n.post('/course/5/upload', data={'exam': 'Internal 2', 'max_score': '50', 'file': (f(), 'a.xlsx'), '_csrf': t}, content_type='multipart/form-data').status_code == 403
    assert n.post('/course/5/mark', data={'reg_no': 'S2531', 'exam': 'Internal 2', 'score': '20', '_csrf': t}).status_code == 403
    t = tok(o, f'/admin/staff/{nid}'); o.post(f'/admin/staff/{nid}', data={'act': 'grant', 'perm': 'marks_upload', 'course_id': '5', 'scope': 'Internal 2', '_csrf': t})
    with app.app_context(): assert Notification.query.filter_by(user_id=nid, priority='High').filter(Notification.text.like('Permission granted%')).count() == 1
    t = tok(n, '/staff/requests')
    assert n.post('/course/5/upload', data={'exam': 'Internal 1', 'max_score': '50', 'file': (f(), 'a.xlsx'), '_csrf': t}, content_type='multipart/form-data').status_code == 403   # other exam still denied
    r = n.post('/course/5/upload', data={'exam': 'Internal 2', 'max_score': '50', 'file': (f(), 'a.xlsx'), '_csrf': t}, content_type='multipart/form-data'); assert r.status_code == 200 and b'Valid' in r.data
    # revoke
    with app.app_context(): pid = Permission.query.filter_by(user_id=nid, perm='marks_upload', active=True).first().id
    t = tok(o, '/admin/permissions'); o.post(f'/admin/staff/{nid}', data={'act': 'revoke', 'pid': pid, '_csrf': t})
    assert n.post('/course/5/mark', data={'reg_no': 'S2531', 'exam': 'Internal 2', 'score': '20', '_csrf': tok(n, '/staff/requests')}).status_code == 403
    # staff dashboard has notifications, not a student list
    d = p.get('/staff').get_data(as_text=True); assert 'Notifications' in d and 'S2501' not in d
    # staff data scope: priya (ST304 cohort + mentees) cannot open a student outside it
    assert p.get('/staff/student/S2520').status_code == 200 and p.get('/staff/student/S2531').status_code == 403 and client(app, 'meena').get('/staff/student/S2531').status_code == 403   # in course cohort yes, other programme no
    # staff -> HOD request; HOD decides; staff notified
    t = tok(p, '/staff/requests'); p.post('/staff/requests', data={'to_role': 'hod', 'kind': 'Permission request', 'message': 'Need Internal 3 upload', '_csrf': t})
    t = tok(h, '/admin/staff-requests'); with_id = re.search(r'name="rid" value="(\d+)"', h.get('/admin/staff-requests').get_data(as_text=True)).group(1)
    assert o.get('/admin/staff-requests').status_code == 200 and 'Need Internal 3' not in o.get('/admin/staff-requests').get_data(as_text=True)   # routed to HOD only
    h.post('/admin/staff-requests', data={'rid': with_id, 'status': 'Approved', 'response': 'ok', '_csrf': t})
    with app.app_context(): assert Notification.query.filter(Notification.text.like('Your request%approved%')).count() == 1
    # forgot password: identical reply, Office issues a one-time temporary password, forced change
    c, t = anon(app); a1 = c.post('/forgot', data={'username': 's05', '_csrf': t}).get_data(as_text=True); c2, t2 = anon(app); a2 = c2.post('/forgot', data={'username': 'nobody', '_csrf': t2}).get_data(as_text=True)
    assert a1 == a2
    page = o.get('/admin/staff-requests').get_data(as_text=True); rid = re.search(r'name="kind" value="reset"><input type="hidden" name="rid" value="(\d+)"', page).group(1)
    r = o.post('/admin/staff-requests', data={'kind': 'reset', 'rid': rid, '_csrf': tok(o, '/admin/staff-requests')}, follow_redirects=True); pw = re.search(r'shown only once\): ([\w-]+)', r.get_data(as_text=True)).group(1)
    s5 = client(app, 's05', pw); assert s5.get('/student').status_code == 302
    # routine: student sees own class only; staff cannot edit; office edits; HOD can switch off office editing
    s1 = client(app, 's01'); assert 'Monday' in s1.get('/routine').get_data(as_text=True) and 'Add slot' not in s1.get('/routine').get_data(as_text=True)
    assert p.post('/routine', data={'day': 'Monday', 'start': '09:00', 'end': '10:00', 'course_id': '1', '_csrf': tok(p, '/routine')}).status_code == 403
    me_ = client(app, 'meena')        # Teacher of course 1 only: may edit own course's timetable, not another's
    assert me_.post('/routine', data={'day': 'Friday', 'start': '15:00', 'end': '16:00', 'course_id': '1', '_csrf': tok(me_, '/routine')}).status_code == 302
    assert me_.post('/routine', data={'day': 'Friday', 'start': '15:00', 'end': '16:00', 'course_id': '4', '_csrf': tok(me_, '/routine')}).status_code == 403
    assert o.post('/routine', data={'day': 'Friday', 'start': '09:00', 'end': '10:00', 'course_id': '1', 'room': 'R9', '_csrf': tok(o, '/routine')}).status_code == 302
    h.post('/admin/settings', data={'act': 'routine', 'routine_hod': '1', '_csrf': tok(h, '/admin/settings')})
    assert o.post('/routine', data={'day': 'Friday', 'start': '11:00', 'end': '12:00', 'course_id': '1', '_csrf': tok(o, '/routine')}).status_code == 403
    # staff with detail-correction permission handles only in-scope students
    t = tok(o, '/admin/permissions'); o.post('/admin/permissions', data={'user': str(meena), 'perm': 'detail_correction', 'course_id': '', 'scope': '', '_csrf': t})
    assert 'Detail Corrections' in client(app, 'meena').get('/staff').get_data(as_text=True) and client(app, 'meena').get('/staff/corrections').status_code == 200 and p.get('/staff/corrections').status_code == 403
    # impact dashboard: HOD only
    assert h.get('/admin/impact').status_code == 200 and o.get('/admin/impact').status_code == 403 and p.get('/admin/impact').status_code == 403
    assert client(app, 'office').get('/admin/audit').status_code == 200
    print('ROLES OK')

def test_followup_outcome():
    app = create_app('sqlite://'); p = client(app, 'priya')
    t = tok(p, '/mentor/student/S2501'); p.post('/mentor/student/S2501', data={'itype': 'Mentor Meeting', 'description': 'd', 'follow_up': '2026-10-20', 'response': 'agreed', 'remarks': 'r', '_csrf': t})
    with app.app_context(): iv = Intervention.query.filter_by(student_id=Student.query.filter_by(reg_no='S2501').first().id).order_by(Intervention.id.desc()).first(); iid = iv.id; assert iv.follow_up_status == 'Pending' and iv.student_response == 'agreed'
    assert p.post(f'/mentor/followup/{iid}/reschedule', data={'new_date': '2026-10-25', '_csrf': tok(p, '/mentor')}).status_code == 302
    with app.app_context(): assert db.session.get(Intervention, iid).follow_up_status == 'Rescheduled'
    k = client(app, 'kumar'); assert k.post(f'/mentor/followup/{iid}/reschedule', data={'new_date': '2026-10-25', '_csrf': tok(k, '/mentor')}).status_code == 403   # another mentor's student
    p.post(f'/mentor/followup/{iid}', data={'_csrf': tok(p, '/mentor')})
    with app.app_context(): assert db.session.get(Intervention, iid).follow_up_status == 'Completed'
    assert 'Waiting for academic data' in p.get('/mentor/student/S2501').get_data(as_text=True) or 'Outcome' in p.get('/mentor/student/S2501').get_data(as_text=True)
    with app.app_context():
        iv = db.session.get(Intervention, iid); iv.on_date = __import__('datetime').date.today() - __import__('datetime').timedelta(days=60)
        for x in Intervention.query.filter_by(student_id=iv.student_id): x.on_date = iv.on_date
        db.session.commit()
    page = p.get('/mentor/student/S2501').get_data(as_text=True); assert 'Outcome' in page and 'does not show that the intervention caused' in page and 'Support status' in page
    assert client(app, 'hod').get('/admin/impact').status_code == 200
    print('FOLLOWUP OK')

def test_role_migration():
    d = tempfile.mkdtemp(); path = os.path.join(d, 'v1.db'); c = sqlite3.connect(path)
    c.executescript("CREATE TABLE user(id INTEGER PRIMARY KEY,username VARCHAR(40),name VARCHAR(80),role VARCHAR(10),pw_hash VARCHAR(255),email VARCHAR(120),is_demo BOOLEAN,must_change BOOLEAN);"
        "CREATE TABLE course(id INTEGER PRIMARY KEY,code VARCHAR(20),name VARCHAR(100),programme VARCHAR(60),semester VARCHAR(5),staff_id INT,active BOOLEAN);"
        "INSERT INTO user VALUES(1,'hod','H','hod','x',NULL,0,0),(2,'off','O','staff','x',NULL,0,0),(3,'mt','M','mentor','x',NULL,0,0),(4,'cs','C','course','x',NULL,0,0);"
        "INSERT INTO course VALUES(1,'X1','X','P','III',4,1);"); c.commit(); c.close()
    app = create_app('sqlite:///' + path)
    with app.app_context():
        assert {u.username: u.role for u in User.query} == {'hod': 'hod', 'off': 'office', 'mt': 'staff', 'cs': 'staff'}
        assert Permission.query.filter_by(user_id=4, perm='marks_upload', course_id=1).count() == 1
    app2 = create_app('sqlite:///' + path)      # second start must NOT convert again
    with app2.app_context(): assert User.query.filter_by(username='off').first().role == 'office' and User.query.filter_by(role='staff').count() == 2
    print('ROLE MIGRATION OK')
if __name__ == '__main__': test_roles(); test_followup_outcome(); test_role_migration()
