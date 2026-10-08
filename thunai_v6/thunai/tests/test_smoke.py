import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import create_app
from models import Student

def cat_of(u):
    return 'hod' if u == 'hod' else 'office' if u == 'office' else 'student' if re.fullmatch(r's\d\d|q\d|p25\d+', u) else 'staff'

def client(app, user, pw='demo123', cat=None):
    c = app.test_client(); r = c.get('/login'); tok = re.search(r'name="_csrf" value="(\w+)"', r.get_data(as_text=True)).group(1)
    assert c.post('/login', data={'username': user, 'password': pw, 'category': cat or cat_of(user), '_csrf': tok}).status_code == 302
    return c

def tok(c, path):
    return re.search(r'name="_csrf" value="(\w+)"', c.get(path).get_data(as_text=True)).group(1)

def test_all():
    app = create_app('sqlite://')
    for u, p in [('hod','/admin'),('office','/admin'),('priya','/mentor'),('meena','/staff'),('s01','/student')]:
        c = client(app, u); assert c.get(p).status_code == 200, (u, p)
    h = client(app, 'hod')
    for p in ['/admin/groups','/admin/assign','/admin/workload','/admin/outcomes','/admin/audit','/admin/export/students.csv','/admin/history/S2501']:
        assert h.get(p).status_code == 200, p
    assert 'Priority Support' in h.get('/admin').get_data(as_text=True)
    assert client(app, 'office').get('/admin/analytics').status_code == 403       # office has no analytics
    assert 'Priority Support' not in client(app, 'office').get('/admin').get_data(as_text=True)
    assert client(app, 'meena').get('/mentor').status_code == 403            # staff without mentor responsibility: no mentorship
    m = client(app, 'priya'); assert m.get('/mentor/student/S2501').status_code == 200
    assert m.get('/mentor/student/S2520').status_code == 403                    # IDOR: another mentor's student
    assert m.get('/mentor/student/S2540').status_code == 403                    # unassigned student
    assert m.get('/admin').status_code == 403
    s = client(app, 's01'); assert s.get('/mentor').status_code == 403 and s.get('/admin').status_code == 403
    assert s.post('/student/request', data={'category':'Academic Help','message':'help','_csrf':'bad'}).status_code == 400  # CSRF
    t = tok(s, '/student/request'); assert s.post('/student/request', data={'category':'Academic Help','subject':'Need help','message':'Need help','_csrf':t}).status_code == 302
    t = tok(m, '/mentor/student/S2501')
    assert m.post('/mentor/student/S2501', data={'itype':'Mentor Meeting','description':'Met','follow_up':'2026-10-20','_csrf':t}).status_code == 302
    # reassign keeps history, bulk assign unassigned -> kumar group
    from models import MentorAssignment, MentorGroup, User
    with app.app_context():
        gid = MentorGroup.query.filter(MentorGroup.name.like('%Group B')).first().id
        ids = [s.id for s in Student.query.filter(Student.reg_no.in_(['S2536','S2537'])).all()]
    t = tok(h, '/admin/assign')
    r = h.post('/admin/assign', data={'mentor':'3','group':str(gid),'students':ids,'_csrf':t}); assert 'will be assigned' in r.get_data(as_text=True)
    t = tok(h, '/admin/assign'); h.post('/admin/assign', data={'mentor':'3','group':str(gid),'students':ids,'confirmed':'1','reason':'Bulk','_csrf':t})
    t = tok(h, '/admin/history/S2501'); h.post('/admin/reassign', data={'reg':'S2501','group':str(gid),'effective':'2026-10-01','reason':'Workload','_csrf':t})
    with app.app_context():
        rows = MentorAssignment.query.join(Student).filter(Student.reg_no=='S2501').all()
        assert len(rows) == 2 and sum(r.end_date is None for r in rows) == 1
    assert client(app, 'priya').get('/mentor/student/S2501').status_code == 403  # lost access after transfer
    assert client(app, 'kumar').get('/mentor/student/S2501').status_code == 200
    assert h.get('/logout').status_code == 405
    print('ALL OK')
if __name__ == '__main__': test_all()
