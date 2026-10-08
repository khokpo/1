import io, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from datetime import date, timedelta
from app import create_app
from models import *
from test_smoke import client, tok
import development as D

def post(c, path, data, files=None):
    d = dict(data); d['_csrf'] = tok(c, '/student/development') if path.startswith('/student') else tok(c, '/admin/verification')
    if files: d.update(files)
    return c.post(path, data=d, content_type='multipart/form-data')

def test_dev():
    app = create_app('sqlite://'); s = client(app, 's01'); s2 = client(app, 's02'); o = client(app, 'office'); h = client(app, 'hod'); p = client(app, 'priya'); k = client(app, 'kumar'); meena = client(app, 'meena')
    pdf = (io.BytesIO(b'%PDF-1.4 x'), 'proof.pdf')
    assert post(s, '/student/dev/research', {'title': 'Time Series of Agri Output', 'organization': 'CUTN', 'rtype': 'Research project', 'doc_type': 'Project Report'}, {'evidence': pdf}).status_code == 302
    assert post(s, '/student/dev/research', {'title': 'Bad', 'evidence': (io.BytesIO(b'<script>alert(1)</script>'), 'x.pdf')}).status_code == 302
    assert post(s, '/student/dev/workshop', {'title': 'R Workshop', 'start_date': '2026-08-01', 'organization': 'X'}).status_code == 302
    assert post(s, '/student/dev/workshop', {'title': 'r workshop', 'start_date': '2026-08-01'}).status_code == 302          # duplicate (same title/date)
    assert post(s, '/student/dev/conference', {'title': 'National Seminar', 'role': 'Paper Presenter', 'level': 'National', 'start_date': '2026-09-01'}).status_code == 302
    assert post(s, '/student/dev/certification', {'title': 'Old cert', 'organization': 'NPTEL', 'start_date': '2024-01-01', 'expiry_date': '2025-01-01', 'cert_type': 'Course certificate'}).status_code == 302
    assert post(s, '/student/dev/skill', {'title': 'Python', 'proficiency': 'Intermediate', 'skill_category': 'Programming'}).status_code == 302
    with app.app_context():
        st = Student.query.filter_by(reg_no='S2501').first(); rs = DevRecord.query.filter_by(student_id=st.id).all()
        assert len(rs) == 6 and all(r.status == 'Pending Verification' for r in rs) and sum(1 for r in rs if r.category == 'research') == 1   # bad evidence rolled back
        ids = {r.title: r.id for r in rs}; rid = ids['Time Series of Agri Output']
    # students cannot verify; staff/mentors cannot either; only office/HOD
    for c in (s, s2, p, meena):
        assert c.get(f'/admin/verification/{rid}').status_code == 403 and c.post(f'/admin/verification/{rid}', data={'act': 'verify', '_csrf': 'x'}).status_code in (400, 403)
    # reject / correction require a reason
    t = tok(o, f'/admin/verification/{rid}'); o.post(f'/admin/verification/{rid}', data={'act': 'reject', 'remarks': '', '_csrf': t})
    with app.app_context(): assert db.session.get(DevRecord, rid).status == 'Pending Verification'
    o.post(f'/admin/verification/{rid}', data={'act': 'correction', 'remarks': 'Certificate date does not match.', '_csrf': t})
    with app.app_context(): assert db.session.get(DevRecord, rid).status == 'Requires Correction'
    assert 'Certificate date does not match' in s.get('/student/dev/research').get_data(as_text=True)
    # student edit -> pending again; cannot edit someone else's record
    t = tok(s, '/student/development'); assert s.post(f'/student/dev/record/{rid}/edit', data={'title': 'Time Series of Agri Output (revised)', 'organization': 'CUTN', '_csrf': t}, content_type='multipart/form-data').status_code == 302
    with app.app_context(): assert db.session.get(DevRecord, rid).status == 'Pending Verification' and db.session.get(DevRecord, rid).remarks is None
    assert s2.post(f'/student/dev/record/{rid}/edit', data={'title': 'hijack', '_csrf': tok(s2, '/student/development')}, content_type='multipart/form-data').status_code == 403
    # before verification: analytics (verified-only) counts nothing; after verification it counts
    with app.app_context(): assert D.snapshot(st.id)['cnt']['research']['verified'] == 0 and D.snapshot(st.id)['cnt']['research']['pending'] == 1
    for title in ('Time Series of Agri Output (revised)', 'R Workshop', 'r workshop', 'National Seminar', 'Old cert', 'Python'):
        with app.app_context(): i = DevRecord.query.filter_by(student_id=st.id, title=title).first().id
        o.post(f'/admin/verification/{i}', data={'act': 'verify', 'remarks': '', '_csrf': tok(o, '/admin/verification')})
    with app.app_context():
        sn = D.snapshot(st.id); assert sn['cnt']['research']['verified'] == 1
        assert sn['cnt']['workshop']['verified'] == 1                       # duplicate not double-counted
        assert sn['cnt']['certification']['verified'] == 0 and sn['cnt']['certification']['expired'] == 1   # expired excluded
        assert sn['presented'] == 1 and sn['attended'] == 0                 # presented vs attended distinguished
        dims = {d['name']: d for d in sn['dims']}
        assert dims['Research Engagement']['level'] == 'Emerging' and dims['Community Engagement']['level'] == 'Not reported'   # not "no activity"
        assert D.band(0) is None and D.band(2) == 'Active' and D.band(4) == 'Strong'
    # student tries to mark verified through crafted POST: status field ignored
    t = tok(s, '/student/development'); s.post('/student/dev/skill', data={'title': 'SPSS', 'status': 'Verified', '_csrf': t}, content_type='multipart/form-data')
    with app.app_context(): assert DevRecord.query.filter_by(title='SPSS').first().status == 'Pending Verification'
    # N/A is distinct from not reported
    s.post('/student/dev/sports/na', data={'_csrf': tok(s, '/student/development')})
    with app.app_context(): assert any(d['name'] == 'Extracurricular Engagement' for d in D.snapshot(st.id)['dims']); assert D.snapshot(st.id)['cnt']['sports']['na']
    pg = s.get('/student/development').get_data(as_text=True); assert 'Not reported' in pg and 'not applicable' in pg and 'Profile completeness' in pg and 'not a measure of performance' in pg.lower() or 'Completeness only shows' in pg
    # evidence access control
    with app.app_context(): eid = DevRecord.query.filter_by(student_id=st.id, category='research').first().evidence_id
    assert eid and s.get(f'/evidence/{eid}').status_code == 200 and p.get(f'/evidence/{eid}').status_code == 200 and o.get(f'/evidence/{eid}').status_code == 200
    assert s2.get(f'/evidence/{eid}').status_code == 403 and k.get(f'/evidence/{eid}').status_code == 403 and meena.get(f'/evidence/{eid}').status_code == 403
    # mentor snapshot: own mentee only; contextual note built only from verified data
    pg = p.get('/mentor/student/S2501/development'); assert pg.status_code == 200 and 'Student Development Snapshot' in pg.get_data(as_text=True)
    assert k.get('/mentor/student/S2501/development').status_code == 403 and meena.get('/mentor/student/S2501/development').status_code == 403
    with app.app_context(): sig = {'level': 'Monitor'}; assert D.holistic_note({'level': 'Stable'}, D.snapshot(st.id)) is None
    # reports: student own, mentor mentee, office without signals/interventions
    assert s.get('/student/report').status_code == 200 and p.get('/mentor/student/S2501/report').status_code == 200 and k.get('/mentor/student/S2501/report').status_code == 403
    off = o.get('/admin/students/S2501/report').get_data(as_text=True); assert 'not included in this view' in off and 'Early-support signal' not in off
    assert 'Early-support signal' in h.get('/admin/students/S2501/report').get_data(as_text=True)
    # HOD aggregate analytics (verified only), office sees verification but not analytics
    pg = h.get('/admin/development'); assert pg.status_code == 200 and 'Verified conference presentations' in pg.get_data(as_text=True) and o.get('/admin/development').status_code == 403
    assert o.get('/admin/verification?status=Verified').status_code == 200
    with app.app_context(): assert VerificationLog.query.filter_by(record_id=rid, action='correction requested').count() == 1 and AuditLog.query.filter_by(action='dev_verify').count() >= 1
    print('DEVELOPMENT OK')
if __name__ == '__main__': test_dev()
