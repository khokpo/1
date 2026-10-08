"""Login portals (Student/Teacher/Mentor/Staff/HOD/Office), merged student support page, simplified navigation."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import create_app
from models import *
from test_smoke import client, tok

def attempt(app, user, pw, cat):
    c = app.test_client(); t = re.search(r'name="_csrf" value="(\w+)"', c.get('/login').get_data(as_text=True)).group(1)
    return c.post('/login', data={'username': user, 'password': pw, 'category': cat, '_csrf': t})

def test_ui_roles():
    app = create_app('sqlite://')
    assert b'Enter your user ID' in attempt(app, '', 'x', 'student').data and b'Enter your password' in attempt(app, 's01', '', 'student').data
    assert b'Incorrect user ID or password' in attempt(app, 's01', 'nope', 'student').data
    assert attempt(app, 'priya', 'demo123', 'mentor').status_code == 302 and attempt(app, 'priya', 'demo123', 'teacher').status_code == 302
    assert b'cannot sign in to the Mentor portal' in attempt(app, 'meena', 'demo123', 'mentor').data      # teacher without mentor group
    assert b'cannot sign in to the Teacher portal' in attempt(app, 'kumar', 'demo123', 'teacher').data    # mentor without courses
    with app.app_context():
        u = User.query.filter_by(username='anitha').first(); u.active = False; db.session.commit()
    assert b'not active' in attempt(app, 'anitha', 'demo123', 'staff').data
    # student: four nav items, one support page holding the form and the request list
    s = client(app, 's01'); page = s.get('/student').get_data(as_text=True)
    assert 'My Profile' in page and 'Request Support' in page and 'Marks &amp; Graph' in page and 'My Requests' not in page.split('<main')[0]
    t = tok(s, '/student/request')
    assert s.post('/student/request', data={'category': 'Academic Help', 'subject': '', 'message': 'x', '_csrf': t}).status_code == 200      # title required
    assert s.post('/student/request', data={'category': 'Academic Help', 'subject': 'Help', 'message': 'Need help', '_csrf': t}).status_code == 302
    body = s.get('/student/request').get_data(as_text=True); assert 'REQ-' in body and 'Submitted' in body
    assert s.get('/student/requests').status_code == 302
    # staff: no student list on dashboard; unauthorised users cannot reach teacher-profile editing
    m = client(app, 'meena'); assert 'Students by class' in m.get('/staff').get_data(as_text=True)
    assert m.post('/admin/staff/1', data={'act': 'profile', 'designation': 'x', '_csrf': tok(m, '/staff')}).status_code == 403
