"""DEMO MODE: synthetic data only. Not real student information."""
import random
from datetime import date, timedelta, datetime
from werkzeug.security import generate_password_hash as H
from models import *
import mentorship as ms

def seed():
    rnd = random.Random(7); pw = H('demo123')
    def U(un, name, role): u = User(username=un, name=name, role=role, pw_hash=pw, is_demo=True); db.session.add(u); return u
    U('hod','Dr. Raman','hod'); U('office','Office Admin','office')
    mentors = [U('priya','Dr. Priya','staff'), U('kumar','Dr. Kumar','staff'), U('anitha','Dr. Anitha','staff')]
    cstaff = [U('meena','Dr. Meena','staff'), U('ravi','Dr. Ravi','staff'), mentors[0]]   # Dr. Priya is both Teacher and Mentor
    db.session.flush()
    spec = [('ST301','Statistical Inference','M.Sc Statistics',0),('ST302','Probability Theory','M.Sc Statistics',0),('ST303','Data Analysis','M.Sc Statistics',1),
            ('ST304','Regression Analysis','M.Sc Statistics',2),('AM301','Real Analysis','M.Sc Applied Mathematics',0),('AM302','Numerical Methods','M.Sc Applied Mathematics',1)]
    courses = []
    for code, nm, prog, k in spec:
        c = Course(code=code, name=nm, programme=prog, semester='III', staff_id=cstaff[k].id); db.session.add(c); courses.append(c); db.session.flush()
        for p in ('marks_upload', 'attendance_manage'): db.session.add(Permission(user_id=cstaff[k].id, perm=p, course_id=c.id))
    for i, c in enumerate(courses):
        db.session.add(TimetableSlot(day=['Monday','Tuesday','Wednesday','Thursday','Friday','Monday'][i], start=['09:00','10:00','11:00','09:00','14:00','11:00'][i], end=['10:00','11:00','12:00','10:00','15:00','12:00'][i],
                       course_id=c.id, staff_id=c.staff_id, room=f'R10{i+1}', class_name=f'{c.programme} Sem III', programme=c.programme, semester='III'))
    groups = []
    for m, nm in zip(mentors, ['M.Sc Statistics — Group A','M.Sc Statistics — Group B','M.Sc Applied Mathematics — Group A']):
        g = MentorGroup(name=nm, programme=nm.split(' — ')[0], academic_year='2026-27', semester='III', mentor_id=m.id); db.session.add(g); groups.append(g)
    db.session.flush()
    sizes = [15, 12, 8, 5]  # last 5 deliberately unassigned
    profiles = ['stable']*14 + ['decline']*10 + ['sharp']*5 + ['improve']*11
    rnd.shuffle(profiles); i = 0; today = date.today()
    for gi, sz in enumerate(sizes):
        for _ in range(sz):
            i += 1; reg = f'S25{i:02d}'
            u = U(f's{i:02d}', f'Student {i}', 'student'); db.session.flush()
            s = Student(user_id=u.id, reg_no=reg, name=f'Student {i}', programme='M.Sc Applied Mathematics' if gi==2 else 'M.Sc Statistics', semester='III', is_demo=True)
            db.session.add(s); db.session.flush()
            att, ass, asg = rnd.uniform(75,92), rnd.uniform(62,85), rnd.uniform(80,98); p = profiles[i-1]
            for per in range(1, 6):
                k = {'stable':0, 'decline':-3.2, 'sharp':-5.5, 'improve':2.5}[p]
                if p == 'improve' and per <= 2: k = -3
                att, ass = min(98, max(35, att + k + rnd.uniform(-1,1))), min(98, max(30, ass + k*0.9 + rnd.uniform(-1,1)))
                late = 0 if k >= 0 else rnd.choice([1,2,3])
                db.session.add(AcademicRecord(student_id=s.id, period=per, period_date=today - timedelta(days=(5-per)*21),
                                attendance=round(att,1), assessment=round(ass,1), assignment_pct=round(max(40,asg+k*1.5),1), late_submissions=late))
            s.verified_at = datetime.utcnow(); s.father_name = f'Father of {s.name}'; s.parent_phone = '9000000000'
            base = ass  # marks follow the student's assessment trajectory (synthetic)
            for c in courses:
                if c.programme != s.programme: continue
                for sess in range(6):
                    db.session.add(CourseAttendance(course_id=c.id, student_id=s.id, on_date=today - timedelta(days=7 * (6 - sess)), present=rnd.random() < att / 100, marked_by=c.staff_id))
                for ex, off in (('Internal 1', 4), ('Internal 2', 0)):
                    sc = max(8, min(50, round((base + off + rnd.uniform(-9, 9)) / 2, 1)))
                    db.session.add(Mark(student_id=s.id, course_id=c.id, exam_type=ex, score=sc, max_score=50, uploaded_by=c.staff_id))
            if gi < 3:
                db.session.add(MentorAssignment(student_id=s.id, mentor_id=mentors[gi].id, group_id=groups[gi].id, start_date=today-timedelta(days=110), reason='Initial allocation'))
                if p in ('improve','decline') and rnd.random() < .7:
                    db.session.add(Intervention(student_id=s.id, mentor_id=mentors[gi].id, itype='Study Planning', description='Discussed study plan.',
                                    action_taken='Weekly plan agreed.', on_date=today-timedelta(days=50), follow_up_date=today+timedelta(days=rnd.choice([-2,0,3])), status='Follow-up Required'))
                if p == 'sharp':
                    db.session.add(SupportRequest(student_id=s.id, category='Course Difficulty', message='Finding Statistical Inference difficult.'))
    db.session.commit()
