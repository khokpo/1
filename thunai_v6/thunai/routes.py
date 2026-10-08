from datetime import date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, session, abort, flash, g, Response
from werkzeug.security import check_password_hash
import csv, io
from models import *
from security import roles_required, mentor_required, audit, notify, is_mentor, has_perm, setting
import mentorship as ms
from analytics import student_signal, before_after, intervention_outcome

auth = Blueprint('auth', __name__); admin = Blueprint('admin', __name__)
mentor = Blueprint('mentor', __name__); student = Blueprint('student', __name__)
ITYPES = ['Mentor Meeting','Follow-up Meeting','Academic Guidance','Study Planning','Remedial Class','Additional Tutorial',
          'Doubt-Clearing Session','Faculty Consultation','Study Material','Peer Learning','Assignment Reminder',
          'Attendance Discussion','Learning Activity Recommendation',
          'Assignment Support','Course Guidance','Peer Support','Resource Referral','Other']
# Stage 3 (Understand): the mentor records the need after talking with the student - the system never assumes it.
NEEDS = ['Difficulty with foundational concepts','Need for additional academic guidance','Attendance-related difficulty',
         'Assignment or workload difficulty','Language or learning difficulty','Time-management difficulty',
         'Need for peer learning','Need for additional faculty support','Other reason found while mentoring']
CATS = ['Academic Help','Attendance Issue','Assignment Difficulty','Course Difficulty',
        'Personal/General Academic Support','Mentor Discussion','Other']

@auth.route('/')
def home():
    if not g.user: return redirect(url_for('auth.login'))
    return redirect(url_for({'hod':'admin.dashboard','office':'admin.dashboard','staff':'portal.staff_dashboard','student':'student.dashboard'}[g.user.role]))

CATEGORIES = {'student': 'Student', 'teacher': 'Teacher', 'mentor': 'Mentor', 'staff': 'Staff', 'hod': 'HOD', 'office': 'Office'}

def role_matches(u, cat):
    """Teacher and Mentor are responsibilities of a Staff account, so they are checked, not stored as separate roles."""
    if cat in ('student', 'hod', 'office'): return u.role == cat
    if u.role != 'staff': return False
    if cat == 'teacher': return Course.query.filter_by(staff_id=u.id, active=True).first() is not None
    if cat == 'mentor': return is_mentor(u)
    return cat == 'staff'

@auth.route('/login', methods=['GET', 'POST'])
def login():
    if g.user: return redirect(url_for('auth.home'))
    cat = request.form.get('category') or request.args.get('category') or 'student'
    if request.method == 'POST':
        un = request.form.get('username', '').strip().lower(); pw = request.form.get('password', '')
        label = CATEGORIES.get(cat, 'selected')
        if cat not in CATEGORIES: flash('Choose the portal you want to sign in to.', 'error')
        elif not un: flash('Enter your user ID or username.', 'error')
        elif not pw: flash('Enter your password.', 'error')
        else:
            u = User.query.filter(db.func.lower(User.username) == un).first()
            if not (u and check_password_hash(u.pw_hash, pw)): flash('Incorrect user ID or password. Check both and try again.', 'error')
            elif u.active is False: flash('This account is not active. Contact the Office to have it reactivated.', 'error')
            elif not role_matches(u, cat): flash(f'This account cannot sign in to the {label} portal. Choose the portal that matches your role.', 'error')
            else:
                session.clear(); session['uid'] = u.id; session.permanent = True
                g.user = u; audit('login', f'{u.username} as {cat}'); db.session.commit()
                return redirect(url_for('mentor.dashboard') if cat == 'mentor' else url_for('auth.home'))
    demo = User.query.filter_by(is_demo=True).first() is not None
    return render_template('login.html', cat=cat, cats=CATEGORIES, demo=demo)

@auth.route('/forgot', methods=['GET', 'POST'])
def forgot():
    """No email service: the request goes to the Office, who verify the person and issue a temporary password.
    The reply is identical whether or not the username exists, so accounts cannot be probed."""
    done = False
    if request.method == 'POST':
        un = request.form.get('username', '').strip().lower()[:40]
        if un and ResetRequest.query.filter_by(username=un, status='Pending').count() < 3:
            db.session.add(ResetRequest(username=un, note=request.form.get('note', '').strip()[:200])); db.session.commit()
        done = True
    return render_template('forgot.html', done=done)

@auth.route('/logout', methods=['POST'])
def logout():
    session.clear(); return redirect(url_for('auth.login'))

@auth.route('/notifications')
def notifications():
    if not g.user: return redirect(url_for('auth.login'))
    items = Notification.query.filter_by(user_id=g.user.id).order_by(Notification.created.desc()).limit(50).all()
    for n in items: n.was_unread = not n.read
    for n in items: n.read = True
    db.session.commit()
    return render_template('notifications.html', items=items)

# ---------------- HOD / OFFICE STAFF ----------------
def status_counts(studs):
    c = {'Stable':0,'Monitor':0,'Attention Recommended':0,'Priority Support':0}
    for s in studs: c[student_signal(s.id)['level']] += 1
    return c

@admin.route('/admin')
@roles_required('hod','office')
def dashboard():
    studs = Student.query.all(); un = ms.unassigned()
    ctx = dict(total=len(studs), mentors=len({gr.mentor_id for gr in MentorGroup.query.filter_by(status='active')}),
               groups=MentorGroup.query.count(), un=un,
               open_req=SupportRequest.query.filter(~SupportRequest.status.in_(SUPPORT_CLOSED)).count(),
               fu_due=Intervention.query.filter(Intervention.follow_up_date <= date.today(), Intervention.follow_up_done==False).count())
    # Staff do not see sensitive analytics (spec: restricted for Office Staff)
    ctx['counts'] = status_counts(studs) if g.user.role == 'hod' else None
    return render_template('admin_dashboard.html', **ctx)

@admin.route('/admin/assign', methods=['GET','POST'])
@roles_required('hod','office')
def assign_page():
    mentors = User.query.filter_by(role='staff').order_by(User.name).all()
    groups = MentorGroup.query.all()
    if request.method == 'POST':
        ids = [int(x) for x in request.form.getlist('students')]
        m = db.session.get(User, int(request.form['mentor'])); grp = db.session.get(MentorGroup, int(request.form['group']))
        if not ids or not m or not grp or m.role != 'staff': flash('Select students, a mentor and a group.', 'error')
        elif request.form.get('confirmed') != '1':
            sel = Student.query.filter(Student.id.in_(ids)).all()
            return render_template('confirm_assign.html', sel=sel, m=m, grp=grp)
        else:
            reason = request.form.get('reason') or 'Allocation'
            n = ms.assign(ids, m.id, grp.id, g.user.id, reason)
            for sid in ids: pass
            notify(m.id, f'{n} student(s) assigned to you in {grp.name}.')
            audit('assign', f'{g.user.name} assigned {n} student(s) to {m.name} ({grp.name}): {reason}')
            db.session.commit(); flash(f'{n} students assigned to {m.name} under {grp.name}.', 'ok')
            return redirect(url_for('admin.assign_page'))
    studs = Student.query.order_by(Student.reg_no).all()
    cur = {s.id: ms.active_assignment(s.id) for s in studs}
    return render_template('assign.html', studs=studs, cur=cur, mentors=mentors, groups=groups)

@admin.route('/admin/groups', methods=['GET','POST'])
@roles_required('hod','office')
def groups():
    if request.method == 'POST':
        gr = MentorGroup(name=request.form['name'], programme=request.form['programme'], academic_year=request.form['year'],
                         semester=request.form['semester'], mentor_id=int(request.form['mentor']),
                         description=request.form.get('description',''))
        db.session.add(gr); audit('group_create', f'{g.user.name} created {gr.name}'); db.session.commit()
        flash('Mentor group created.', 'ok'); return redirect(url_for('admin.groups'))
    return render_template('groups.html', groups=MentorGroup.query.all(), mentors=User.query.filter_by(role='staff').order_by(User.name).all(),
                           size={gr.id: MentorAssignment.query.filter_by(group_id=gr.id, end_date=None).count() for gr in MentorGroup.query.all()})

@admin.route('/admin/workload')
@roles_required('hod','office')
def workload():
    rows = []
    for m in User.query.filter(User.id.in_([gr.mentor_id for gr in MentorGroup.query.filter_by(status='active')])).all():
        ss = ms.students_of(m.id)
        c = status_counts(ss) if g.user.role == 'hod' else {}
        due = Intervention.query.filter(Intervention.mentor_id==m.id, Intervention.follow_up_date<=date.today(), Intervention.follow_up_done==False).count()
        rows.append(dict(m=m, groups=MentorGroup.query.filter_by(mentor_id=m.id).count(), n=len(ss), c=c, due=due))
    key = request.args.get('sort', 'n'); rows.sort(key=lambda r: r.get(key, 0) if key in ('n','groups','due') else 0, reverse=True)
    return render_template('workload.html', rows=rows)

@admin.route('/admin/history/<reg>')
@roles_required('hod','office')
def history(reg):
    s = Student.query.filter_by(reg_no=reg).first_or_404()
    h = MentorAssignment.query.filter_by(student_id=s.id).order_by(MentorAssignment.start_date).all()
    return render_template('history.html', s=s, h=h, groups=MentorGroup.query.all())

@admin.route('/admin/reassign', methods=['POST'])
@roles_required('hod','office')
def reassign():
    s = Student.query.filter_by(reg_no=request.form['reg']).first_or_404()
    grp = db.session.get(MentorGroup, int(request.form['group']))
    eff = datetime.strptime(request.form['effective'], '%Y-%m-%d').date()
    old = ms.active_assignment(s.id)
    ms.assign([s.id], grp.mentor_id, grp.id, g.user.id, request.form.get('reason','Reassignment'), eff)
    notify(grp.mentor_id, f'{s.reg_no} transferred to you.'); notify(s.user_id, 'Your mentor has been updated.')
    audit('reassign', f'{s.reg_no}: {old.mentor.name if old else "none"} -> {grp.mentor.name} eff {eff} ({request.form.get("reason","")})')
    db.session.commit(); return redirect(url_for('admin.history', reg=s.reg_no))

@admin.route('/admin/outcomes')
@roles_required('hod')
def outcomes():
    return render_template('outcomes.html', r=before_after(Intervention.query.all()),
                           req=SupportRequest.query.count(), ivs=Intervention.query.count())

@admin.route('/admin/audit')
@roles_required('hod', 'office')
def audit_log():
    return render_template('audit.html', logs=AuditLog.query.order_by(AuditLog.created.desc()).limit(100).all())

@admin.route('/admin/export/students.csv')
@roles_required('hod')
def export_csv():
    out = io.StringIO(); w = csv.writer(out); w.writerow(['Reg No','Name','Programme','Semester','Status','AMI','Mentor'])
    for s in Student.query.order_by(Student.reg_no):
        sg = student_signal(s.id); a = ms.active_assignment(s.id)
        w.writerow([s.reg_no, s.name, s.programme, s.semester, sg['level'], sg['ami'], a.mentor.name if a else 'Unassigned'])
    audit('export', 'students.csv'); db.session.commit()
    return Response(out.getvalue(), mimetype='text/csv', headers={'Content-Disposition':'attachment; filename=students.csv'})

# ---------------- MENTOR ----------------
@mentor.route('/mentor')
@mentor_required
def dashboard():
    studs = ms.students_of(g.user.id); rows = [(s, student_signal(s.id)) for s in studs]
    q = request.args.get('q','').lower(); f = request.args.get('level','')
    rows = [r for r in rows if (q in r[0].name.lower() or q in r[0].reg_no.lower()) and (not f or r[1]['level']==f)]
    counts = status_counts(studs)
    today = date.today()
    fus = Intervention.query.filter_by(mentor_id=g.user.id, follow_up_done=False).filter(Intervention.follow_up_date.isnot(None)).order_by(Intervention.follow_up_date).all()
    fus = [x for x in fus if ms.mentor_owns(g.user.id, x.student_id)]
    reqs = [r for r in SupportRequest.query.filter(~SupportRequest.status.in_(SUPPORT_CLOSED)).all() if ms.mentor_owns(g.user.id, r.student_id)]
    return render_template('mentor_dashboard.html', rows=rows, counts=counts, n=len(studs), fus=fus, reqs=reqs, today=today)

@mentor.route('/mentor/student/<reg>', methods=['GET','POST'])
@mentor_required
def student_view(reg):
    s = Student.query.filter_by(reg_no=reg).first_or_404()
    if not ms.mentor_owns(g.user.id, s.id): abort(403)  # IDOR guard
    if request.method == 'POST':
        fu = request.form.get('follow_up')
        need = request.form.get('need', ''); need = need if need in NEEDS else ''
        iv = Intervention(student_id=s.id, mentor_id=g.user.id, itype=request.form['itype'] if request.form['itype'] in ITYPES else 'Other',
                          description=(f'[Support need: {need}] ' if need else '') + request.form['description'], action_taken=request.form.get('action',''), student_response=request.form.get('response',''), remarks=request.form.get('remarks',''),
                          follow_up_date=datetime.strptime(fu,'%Y-%m-%d').date() if fu else None, status=request.form.get('status','In Progress'))
        db.session.add(iv); notify(s.user_id, 'Your mentor has recorded a follow-up plan.' if fu else 'Your mentor recorded a support note.')
        audit('intervention', f'{g.user.name} recorded {iv.itype} for {s.reg_no}'); db.session.commit()
        flash('Intervention recorded.', 'ok'); return redirect(url_for('mentor.student_view', reg=reg))
    ivs = Intervention.query.filter_by(student_id=s.id).order_by(Intervention.on_date.desc()).all()
    reqs = SupportRequest.query.filter_by(student_id=s.id).order_by(SupportRequest.created.desc()).all()
    from academics import marks_cfgs, EXAMS; import charts
    sg = student_signal(s.id); by, cs, avgs, mcfg = marks_cfgs(s.id)
    trend = charts.line([f'P{x.period}' for x in sg['recs']], [('Attendance %', [x.attendance for x in sg['recs']]), ('Assessment %', [x.assessment for x in sg['recs']]),
                         ('Assignments %', [x.assignment_pct for x in sg['recs']])], 'Trend over periods') if sg['recs'] else None
    return render_template('student_profile.html', s=s, sg=sg, ivs=ivs, reqs=reqs, itypes=ITYPES, needs=NEEDS, a=ms.active_assignment(s.id),
                           by=by, cs=cs, mcfg=mcfg, trend=trend, EXAMS=EXAMS, outcome=intervention_outcome(s.id))

@mentor.route('/mentor/followup/<int:iid>/reschedule', methods=['POST'])
@mentor_required
def reschedule_followup(iid):
    iv = db.session.get(Intervention, iid) or abort(404)
    if not ms.mentor_owns(g.user.id, iv.student_id): abort(403)
    try: nd = datetime.strptime(request.form['new_date'], '%Y-%m-%d').date()
    except (KeyError, ValueError): flash('Choose a valid new follow-up date.', 'error'); return redirect(url_for('mentor.dashboard'))
    old = iv.follow_up_date; iv.follow_up_date = nd; iv.follow_up_status = 'Rescheduled'
    audit('followup_rescheduled', f'{iv.student.reg_no}: {old} -> {nd}'); db.session.commit(); flash('Follow-up rescheduled.', 'ok'); return redirect(url_for('mentor.dashboard'))

@mentor.route('/mentor/followup/<int:iid>', methods=['POST'])
@mentor_required
def complete_followup(iid):
    iv = db.session.get(Intervention, iid) or abort(404)
    if not ms.mentor_owns(g.user.id, iv.student_id): abort(403)
    iv.follow_up_done = True; iv.follow_up_status = 'Completed'; audit('followup_done', f'{iv.student.reg_no}'); db.session.commit()
    return redirect(url_for('mentor.dashboard'))

@mentor.route('/mentor/request/<int:rid>', methods=['POST'])
@mentor_required
def respond(rid):
    r = db.session.get(SupportRequest, rid) or abort(404)
    if not ms.mentor_owns(g.user.id, r.student_id): abort(403)
    r.response = request.form['response'].strip()[:1500]; set_support_status(r, request.form.get('status','In Progress'))
    notify(r.student.user_id, 'Your mentor responded to your support request.')
    audit('request_response', r.student.reg_no); db.session.commit(); return redirect(url_for('mentor.dashboard'))

# ---------------- STUDENT ----------------
def me_student():
    s = Student.query.filter_by(user_id=g.user.id).first() or abort(404); return s

@student.route('/student')
@roles_required('student')
def dashboard():
    s = me_student(); a = ms.active_assignment(s.id); sg = student_signal(s.id); import charts
    trend = charts.line([f'P{x.period}' for x in sg['recs']], [('Attendance %', [x.attendance for x in sg['recs']]), ('Assessment %', [x.assessment for x in sg['recs']]),
                         ('Assignments %', [x.assignment_pct for x in sg['recs']])], 'My recent progress') if sg['recs'] else None
    from portal import course_att
    crs = [dict(c=c, att=course_att(c.id, s.id), marks=Mark.query.filter_by(student_id=s.id, course_id=c.id).count()) for c in Course.query.filter_by(programme=s.programme, semester=s.semester, active=True).order_by(Course.code)]
    from portal import DAYS
    today_name = DAYS[date.today().weekday()] if date.today().weekday() < len(DAYS) else None
    slots = sorted(TimetableSlot.query.filter_by(programme=s.programme, semester=s.semester, day=today_name).all(), key=lambda x: x.start) if today_name else []
    notes = Notification.query.filter_by(user_id=g.user.id).order_by(Notification.created.desc()).limit(3).all()
    return render_template('student_dashboard.html', s=s, sg=sg, a=a, trend=trend, crs=crs, slots=slots, notes=notes, today_name=today_name,
                           reqs=SupportRequest.query.filter_by(student_id=s.id).order_by(SupportRequest.created.desc()).all())

@student.route('/student/request', methods=['GET','POST'])
@roles_required('student')
def request_support():
    s = me_student()
    if request.method == 'POST':
        msg = request.form.get('message','').strip(); subj = request.form.get('subject','').strip()[:120]
        if not subj: flash('Enter a short title for your request.', 'error')
        elif not msg: flash('Please describe what support you need.', 'error')
        else:
            db.session.add(SupportRequest(student_id=s.id, category=request.form.get('category') if request.form.get('category') in CATS else 'Other', subject=subj, message=msg, status='Submitted'))
            a = ms.active_assignment(s.id)
            if a: notify(a.mentor_id, f'New support request from {s.reg_no}.')
            notify(s.user_id, 'Your support request was received.')
            audit('support_request', s.reg_no); db.session.commit(); flash('Request submitted.', 'ok')
            return redirect(url_for('student.request_support') + '#my-requests')
    a = ms.active_assignment(s.id)
    return render_template('request.html', cats=CATS, a=a, reqs=SupportRequest.query.filter_by(student_id=s.id).order_by(SupportRequest.created.desc()).all())

@auth.route('/about')
def about():
    return render_template('about.html')

@auth.route('/responsible-use')
def responsible():
    return render_template('responsible.html')

# ---------------- STUDENT PROFILE, PHOTO, ACCOUNT ----------------
import os, uuid
from flask import current_app, send_from_directory
from werkzeug.security import generate_password_hash

def _photo_dir():
    d = os.path.join(current_app.instance_path, 'photos'); os.makedirs(d, exist_ok=True); return d

def _image_ext(head):
    if head.startswith(b'\xff\xd8\xff'): return 'jpg'
    if head.startswith(b'\x89PNG\r\n\x1a\n'): return 'png'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP': return 'webp'
    return None

@student.route('/student/profile', methods=['GET', 'POST'])
@roles_required('student')
def profile():
    s = me_student()
    if request.method == 'POST':
        s.bio = request.form.get('bio', '').strip()[:1000]
        f = request.files.get('photo')
        if f and f.filename:
            data = f.read(); ext = _image_ext(data[:16])
            if not ext or len(data) > 2 * 1024 * 1024: flash('Photo must be a JPG, PNG or WEBP image under 2 MB.', 'error'); return redirect(url_for('student.profile'))
            name = f'{uuid.uuid4().hex}.{ext}'; open(os.path.join(_photo_dir(), name), 'wb').write(data)
            if s.photo and os.path.exists(os.path.join(_photo_dir(), s.photo)): os.remove(os.path.join(_photo_dir(), s.photo))
            s.photo = name
        audit('profile_update', s.reg_no); db.session.commit(); flash('Profile saved.', 'ok'); return redirect(url_for('student.profile'))
    a_ = ms.active_assignment(s.id)
    return render_template('profile.html', s=s, mentor=a_.mentor if a_ else None, grp=a_.group if a_ else None)

@student.route('/student/requests')
@roles_required('student')
def my_requests():
    return redirect(url_for('student.request_support') + '#my-requests')   # My Requests now lives on the Request Support page

@auth.route('/photo/<reg>')
def photo(reg):
    """Authorised photo access: the student, their current mentor, or admin roles only."""
    if not g.user: abort(403)
    s = Student.query.filter_by(reg_no=reg).first_or_404()
    ok = (g.user.role in ('hod', 'office') or (g.user.role == 'student' and s.user_id == g.user.id)
          or (g.user.role == 'staff' and ms.mentor_owns(g.user.id, s.id)))
    if not ok or not s.photo: abort(404 if ok else 403)
    return send_from_directory(_photo_dir(), s.photo)

@auth.route('/account', methods=['GET', 'POST'])
def account():
    if not g.user: return redirect(url_for('auth.login'))
    if request.method == 'POST':
        new = request.form.get('new', '')
        if not check_password_hash(g.user.pw_hash, request.form.get('old', '')): flash('Current password is incorrect.', 'error')
        elif len(new) < 8 or new != request.form.get('again'): flash('New password must be at least 8 characters and match the confirmation.', 'error')
        else:
            g.user.pw_hash = generate_password_hash(new); g.user.must_change = False; audit('password_change', g.user.username); db.session.commit(); flash('Password changed.', 'ok')
    return render_template('account.html')


# ---------------- STUDENT: view office details, confirm, submit corrections ----------------
from datetime import datetime as _dt
from models import ProfileChange
from manage import CORRECTABLE

@student.route('/student/details', methods=['GET', 'POST'])
@roles_required('student')
def my_details():
    s = me_student()
    if request.method == 'POST':
        if request.form.get('act') == 'confirm':
            s.confirmed_by_student = _dt.utcnow(); audit('details_confirmed', s.reg_no); db.session.commit(); flash('Thank you. The office will verify your details.', 'ok')
        else:
            f, new = request.form.get('field'), request.form.get('new_value', '').strip()[:200]
            if f not in CORRECTABLE or not new: flash('Choose a field and enter the corrected value.', 'error')
            elif new == (getattr(s, f) or ''): flash('That is already the value on record.', 'error')
            elif ProfileChange.query.filter_by(student_id=s.id, field=f, status='Pending').first(): flash('You already have a pending correction for this field.', 'error')
            else:
                db.session.add(ProfileChange(student_id=s.id, field=f, old_value=getattr(s, f) or '', new_value=new, reason=request.form.get('reason', '')[:300]))
                for u in User.query.filter(User.role.in_(('office', 'hod'))): notify(u.id, f'Correction request from {s.reg_no} ({CORRECTABLE[f]}).')
                audit('correction_submitted', f'{s.reg_no} {f}'); db.session.commit(); flash('Correction sent to the office for approval.', 'ok')
        return redirect(url_for('student.my_details'))
    return render_template('my_details.html', s=s, F=CORRECTABLE, changes=ProfileChange.query.filter_by(student_id=s.id).order_by(ProfileChange.created.desc()).all())
