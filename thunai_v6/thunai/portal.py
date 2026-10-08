"""Staff portal (teacher/faculty with responsibilities), Office permission & staff management,
requests, routine/timetable and the HOD impact dashboard."""
from datetime import date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from werkzeug.security import generate_password_hash as H
from models import *
from security import roles_required, mentor_required, audit, notify, is_mentor, has_perm, setting, temp_password
import mentorship as ms, charts
from analytics import student_signal, ami, intervention_outcome
from academics import EXAMS, cohort, marks_cfgs
from manage import CORRECTABLE, decide_correction

portal = Blueprint('portal', __name__)
PERMS = {'marks_upload': 'Marks upload', 'attendance_manage': 'Attendance management', 'detail_correction': 'Student-detail correction',
         'course_manage': 'Course management', 'routine_manage': 'Timetable management', 'assignment_manage': 'Assignment management', 'workload_manage': 'Workload management'}
PROFILE_FIELDS = ('designation', 'department', 'qualifications', 'expertise', 'research', 'contact', 'links')
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

# ---------- scope helpers (server-side) ----------
def teaching(u): return Course.query.filter_by(staff_id=u.id, active=True).order_by(Course.code).all()

def scope_students(u):
    """Students a Staff member may see: cohorts of courses they teach + their assigned mentees. Never the whole university."""
    out = {s.id: s for c in teaching(u) for s in cohort(c)}
    for s in ms.students_of(u.id): out[s.id] = s
    return out

def course_att(cid, sid):
    rows = CourseAttendance.query.filter_by(course_id=cid, student_id=sid).all()
    return round(100 * sum(1 for r in rows if r.present) / len(rows), 1) if rows else None

def _own_course(cid):
    c = db.session.get(Course, cid) or abort(404)
    if c.staff_id != g.user.id: abort(403)
    return c

# ---------- STAFF ----------
@portal.route('/staff')
@roles_required('staff')
def staff_dashboard():
    cs = teaching(g.user); rows = []; allst = scope_students(g.user)
    for c in cs:
        co = cohort(c); sess = {r[0] for r in db.session.query(CourseAttendance.on_date).filter_by(course_id=c.id)}
        att = db.session.query(db.func.avg(db.case((CourseAttendance.present == True, 100.0), else_=0.0))).filter(CourseAttendance.course_id == c.id).scalar()
        ex = [(e, Mark.query.filter_by(course_id=c.id, exam_type=e).count()) for e in EXAMS]
        rows.append(dict(c=c, n=len(co), sessions=len(sess), att=round(att, 1) if att is not None else None, ex=ex,
                         pending_asg=len(co) - dict(ex)['Assignment']))
    notes = Notification.query.filter_by(user_id=g.user.id).order_by(Notification.read, Notification.created.desc()).limit(8).all()
    mentees = len(ms.students_of(g.user.id)) if is_mentor(g.user) else None
    by_class = {}
    for c in cs: by_class[f'{c.programme} · Semester {c.semester}'] = max(by_class.get(f'{c.programme} · Semester {c.semester}', 0), len(cohort(c)))
    pending_req = SupportRequest.query.filter(SupportRequest.student_id.in_(list(allst) or [0]), ~SupportRequest.status.in_(SUPPORT_CLOSED)).count()
    return render_template('staff_dashboard.html', by_class=sorted(by_class.items()), pending_req=pending_req, rows=rows, total=len(allst), classes=len({(c.programme, c.semester) for c in cs}), notes=notes, mentees=mentees)

@portal.route('/staff/students')
@roles_required('staff')
def staff_students():
    sc = scope_students(g.user); q = request.args.get('q', '').lower(); mine = {s.id for s in ms.students_of(g.user.id)}
    rows = [s for s in sorted(sc.values(), key=lambda s: s.reg_no) if q in s.name.lower() or q in s.reg_no.lower()]
    return render_template('staff_students.html', rows=rows, mine=mine, q=request.args.get('q', ''))

@portal.route('/staff/student/<reg>')
@roles_required('staff')
def staff_student(reg):
    s = Student.query.filter_by(reg_no=reg).first_or_404()
    if s.id not in scope_students(g.user): abort(403)
    if ms.mentor_owns(g.user.id, s.id): return redirect(url_for('mentor.student_view', reg=reg))
    mine = teaching(g.user); cs = [c for c in mine if (c.programme, c.semester) == (s.programme, s.semester)]
    marks = {(m.course_id, m.exam_type): m for m in Mark.query.filter_by(student_id=s.id) if m.course_id in {c.id for c in cs}}
    sig = student_signal(s.id)
    trend = charts.line([f'P{r.period}' for r in sig['recs']], [('Attendance %', [r.attendance for r in sig['recs']]), ('Assessment %', [r.assessment for r in sig['recs']]), ('Assignments %', [r.assignment_pct for r in sig['recs']])], 'Academic journey') if sig['recs'] else None
    return render_template('staff_student.html', s=s, cs=cs, marks=marks, EXAMS=EXAMS, att={c.id: course_att(c.id, s.id) for c in cs}, recs=sig['recs'], trend=trend)

@portal.route('/staff/attendance-sheet')
@roles_required('staff')
def attendance_sheet():
    cs = teaching(g.user); cid = request.args.get('course', type=int)
    c = _own_course(cid) if cid else None; d = request.args.get('date') or date.today().isoformat()
    return render_template('attendance_sheet.html', cs=cs, c=c, d=d, studs=cohort(c) if c else [])

@portal.route('/staff/attendance', methods=['GET', 'POST'])
@roles_required('staff')
def attendance_entry():
    cid = request.values.get('course', type=int); c = _own_course(cid) if cid else None
    if c and not has_perm(g.user, 'attendance_manage', c.id): abort(403)
    try: d = date.fromisoformat(request.values.get('date') or date.today().isoformat())
    except ValueError: d = date.today()
    if c and request.method == 'POST':
        if d > date.today(): flash('The date cannot be in the future.', 'error'); return redirect(url_for('portal.attendance_entry', course=c.id))
        present = set(request.form.getlist('present')); n = 0
        for s in cohort(c):
            r = CourseAttendance.query.filter_by(course_id=c.id, student_id=s.id, on_date=d).first() or CourseAttendance(course_id=c.id, student_id=s.id, on_date=d)
            r.present = s.reg_no in present; r.marked_by = g.user.id; db.session.add(r); n += 1
        audit('attendance_entry', f'{g.user.name} {c.code} {d}: {len(present)}/{n} present'); db.session.commit(); flash(f'Attendance saved for {d.strftime("%d %b %Y")}.', 'ok')
        return redirect(url_for('portal.attendance_entry', course=c.id, date=d.isoformat()))
    allowed = [x for x in teaching(g.user) if has_perm(g.user, 'attendance_manage', x.id)]
    ex = {r.student_id: r.present for r in CourseAttendance.query.filter_by(course_id=c.id, on_date=d)} if c else {}
    return render_template('attendance_entry.html', cs=allowed, c=c, d=d, studs=cohort(c) if c else [], ex=ex)

@portal.route('/staff/academic-data')
@roles_required('staff')
def academic_data():
    rows = [dict(c=c, marks=has_perm(g.user, 'marks_upload', c.id), att=has_perm(g.user, 'attendance_manage', c.id), asg=has_perm(g.user, 'assignment_manage', c.id),
                 scopes=[p.scope or 'all exams' for p in Permission.query.filter_by(user_id=g.user.id, perm='marks_upload', active=True) if p.course_id in (None, c.id)]) for c in teaching(g.user)]
    return render_template('academic_data.html', rows=rows)

@portal.route('/staff/upload')
@roles_required('staff')
def staff_upload():
    return render_template('staff_upload.html', rows=[c for c in teaching(g.user) if has_perm(g.user, 'marks_upload', c.id)], any_course=bool(teaching(g.user)))

@portal.route('/staff/corrections', methods=['GET', 'POST'])
@roles_required('staff')
def staff_corrections():
    if not has_perm(g.user, 'detail_correction'): abort(403)
    sc = scope_students(g.user)
    if request.method == 'POST':
        c = db.session.get(ProfileChange, int(request.form['cid'])) or abort(404)
        if c.student_id not in sc: abort(403)
        if c.status == 'Pending': decide_correction(c, request.form['act'], request.form.get('note'))
        return redirect(url_for('portal.staff_corrections'))
    q = ProfileChange.query.filter(ProfileChange.student_id.in_(list(sc) or [0]))
    return render_template('corrections.html', pend=q.filter_by(status='Pending').all(), done=q.filter(ProfileChange.status != 'Pending').order_by(ProfileChange.decided_at.desc()).limit(30).all(), F=CORRECTABLE, action='/staff/corrections')

@portal.route('/staff/requests', methods=['GET', 'POST'])
@roles_required('staff')
def staff_requests():
    sc = scope_students(g.user)
    if request.method == 'POST':
        to, kind, msg = request.form.get('to_role'), request.form.get('kind', '')[:40], request.form.get('message', '').strip()[:1500]
        if to in ('hod', 'office') and msg:
            db.session.add(StaffRequest(from_user=g.user.id, to_role=to, kind=kind, message=msg))
            for u in User.query.filter_by(role=to): notify(u.id, f'Request from {g.user.name}: {kind}', 'High', '/admin/staff-requests')
            audit('staff_request', f'{g.user.name} -> {to}: {kind}'); db.session.commit(); flash('Request sent.', 'ok')
        else: flash('Choose HOD or Office and write your request.', 'error')
        return redirect(url_for('portal.staff_requests'))
    reqs = SupportRequest.query.filter(SupportRequest.student_id.in_(list(sc) or [0])).order_by(SupportRequest.created.desc()).limit(60).all()
    mine = StaffRequest.query.filter_by(from_user=g.user.id).order_by(StaffRequest.created.desc()).all()
    return render_template('staff_requests.html', reqs=reqs, mine=mine)

@portal.route('/staff/requests/<int:rid>', methods=['POST'])
@roles_required('staff')
def staff_respond(rid):
    r = db.session.get(SupportRequest, rid) or abort(404)
    if r.student_id not in scope_students(g.user): abort(403)
    if request.form.get('act') == 'forward':
        to = request.form.get('to_role')
        if to in ('hod', 'office'):
            db.session.add(StaffRequest(from_user=g.user.id, to_role=to, kind='Forwarded student request', message=f'{r.student.reg_no} ({r.category}): {r.message}'))
            for u in User.query.filter_by(role=to): notify(u.id, f'Forwarded student request from {g.user.name}', 'High', '/admin/staff-requests')
            flash('Forwarded.', 'ok')
    else:
        r.response = request.form.get('response', '').strip()[:1500]; set_support_status(r, request.form.get('status', 'In Progress'))
        notify(r.student.user_id, 'Your support request has a response.', 'Normal', '/student/request')
    audit('staff_respond', f'{g.user.name} {r.student.reg_no}'); db.session.commit(); return redirect(url_for('portal.staff_requests'))

@portal.route('/staff/profile')
@roles_required('staff')
def staff_profile():
    return render_template('staff_profile.html', u=g.user, **responsibilities(g.user))

def responsibilities(u):
    return dict(teach=teaching(u), groups=MentorGroup.query.filter_by(mentor_id=u.id, status='active').all(),
                other=Responsibility.query.filter_by(user_id=u.id).all(), perms=Permission.query.filter_by(user_id=u.id, active=True).all())

# ---------- OFFICE / HOD: staff management, permissions, requests ----------
@portal.route('/admin/staff')
@roles_required('hod', 'office')
def admin_staff():
    rows = [dict(u=u, **responsibilities(u)) for u in User.query.filter_by(role='staff').order_by(User.name)]
    return render_template('admin_staff.html', rows=rows)

def _grant(u, perm, cid, scope):
    if perm not in PERMS: abort(400)
    c = db.session.get(Course, cid) if cid else None
    if scope and scope not in EXAMS: abort(400)
    if Permission.query.filter_by(user_id=u.id, perm=perm, course_id=cid, scope=scope or None, active=True).first(): return False
    db.session.add(Permission(user_id=u.id, perm=perm, course_id=cid, scope=scope or None, granted_by=g.user.id))
    notify(u.id, f'Permission granted: you are authorized for {PERMS[perm].lower()}' + (f' — {c.code}' if c else '') + (f' ({scope})' if scope else '') + '.', 'High', '/staff/academic-data')
    audit('permission_grant', f'{g.user.name} -> {u.username}: {perm} {c.code if c else "all"} {scope or ""}'); return True

@portal.route('/admin/staff/<int:uid>', methods=['GET', 'POST'])
@roles_required('hod', 'office')
def admin_staff_view(uid):
    u = db.session.get(User, uid) or abort(404)
    if u.role != 'staff': abort(404)
    if request.method == 'POST':
        act, f = request.form.get('act'), request.form; cid = int(f['course_id']) if f.get('course_id') else None
        if act == 'profile':
            old = {k: getattr(u, k) for k in PROFILE_FIELDS}
            for k in PROFILE_FIELDS: setattr(u, k, f.get(k, '').strip()[:300] or None)
            audit('teacher_profile_edit', f'{g.user.name} -> {u.username}: ' + ', '.join(f'{k}: {old[k]!r}->{getattr(u, k)!r}' for k in PROFILE_FIELDS if old[k] != getattr(u, k))); flash('Teacher profile saved.', 'ok')
        elif act == 'grant': flash('Permission granted.' if _grant(u, f.get('perm'), cid, f.get('scope')) else 'Already granted.', 'ok')
        elif act == 'revoke':
            p = db.session.get(Permission, int(f['pid']));
            if p and p.user_id == u.id: p.active = False; audit('permission_revoke', f'{g.user.name} -> {u.username}: {p.perm}'); notify(u.id, f'Permission removed: {PERMS.get(p.perm, p.perm)}.', 'Normal')
        elif act == 'assign_course' and cid:
            c = db.session.get(Course, cid) or abort(404); old = c.staff_id; c.staff_id = u.id
            notify(u.id, f'You are assigned as teacher for {c.code} {c.name}.', 'High', '/acad'); audit('course_assign', f'{g.user.name}: {c.code} {old} -> {u.id}')
        elif act == 'unassign_course' and cid:
            c = db.session.get(Course, cid); 
            if c and c.staff_id == u.id: c.staff_id = None; audit('course_unassign', f'{g.user.name}: {c.code} from {u.username}')
        elif act == 'add_resp' and f.get('kind') in ('coordinator', 'other'):
            db.session.add(Responsibility(user_id=u.id, kind=f['kind'], course_id=cid, note=f.get('note', '')[:120], assigned_by=g.user.id)); audit('responsibility_add', f'{g.user.name} -> {u.username}: {f["kind"]}')
        elif act == 'remove_resp':
            x = db.session.get(Responsibility, int(f['rid']))
            if x and x.user_id == u.id: db.session.delete(x)
        db.session.commit(); return redirect(url_for('portal.admin_staff_view', uid=uid))
    return render_template('admin_staff_view.html', u=u, PERMS=PERMS, EXAMS=EXAMS, allc=Course.query.order_by(Course.code).all(), mentee_n=len(ms.students_of(u.id)), **responsibilities(u))

@portal.route('/admin/permissions', methods=['GET', 'POST'])
@roles_required('hod', 'office')
def permissions():
    if request.method == 'POST':
        u = db.session.get(User, int(request.form['user'])) or abort(404)
        if u.role != 'staff': abort(400)
        cid = int(request.form['course_id']) if request.form.get('course_id') else None
        flash('Permission granted.' if _grant(u, request.form.get('perm'), cid, request.form.get('scope')) else 'Already granted.', 'ok'); db.session.commit(); return redirect(url_for('portal.permissions'))
    return render_template('permissions.html', grants=Permission.query.filter_by(active=True).order_by(Permission.granted_at.desc()).all(), staff=User.query.filter_by(role='staff').order_by(User.name).all(),
                           allc=Course.query.order_by(Course.code).all(), PERMS=PERMS, EXAMS=EXAMS)

@portal.route('/admin/staff-requests', methods=['GET', 'POST'])
@roles_required('hod', 'office')
def staff_requests_admin():
    if request.method == 'POST':
        if request.form.get('kind') == 'reset':
            if g.user.role != 'office': abort(403)
            rr = db.session.get(ResetRequest, int(request.form['rid'])) or abort(404); u = User.query.filter_by(username=rr.username).first()
            if u and u.role != 'hod' or (u and g.user.role == 'hod'):
                pw = temp_password(); u.pw_hash = H(pw); u.must_change = True; rr.status = 'Done'; rr.handled_by = g.user.id
                audit('password_reset_issued', f'{g.user.name} -> {u.username}'); flash(f'Temporary password for {u.username} (shown only once): {pw}', 'ok')
            else: rr.status = 'Not found'; rr.handled_by = g.user.id; flash('No matching account (or the HOD must handle this one).', 'error')
        else:
            q = db.session.get(StaffRequest, int(request.form['rid'])) or abort(404)
            if q.to_role != g.user.role: abort(403)
            st = request.form.get('status')
            if st in ('Approved', 'Rejected', 'Resolved'):
                q.status, q.response, q.decided_by, q.decided_at = st, request.form.get('response', '')[:1000], g.user.id, datetime.utcnow()
                notify(q.from_user, f'Your request "{q.kind}" was {st.lower()}.', 'High', '/staff/requests'); audit('staff_request_decision', f'{g.user.name}: {q.kind} -> {st}')
        db.session.commit(); return redirect(url_for('portal.staff_requests_admin'))
    return render_template('staff_requests_admin.html', reqs=StaffRequest.query.filter_by(to_role=g.user.role).order_by(StaffRequest.status, StaffRequest.created.desc()).all(),
                           resets=ResetRequest.query.filter_by(status='Pending').all() if g.user.role == 'office' else [])

# ---------- Routine / timetable ----------
def routine_editor():
    """Full timetable management: HOD / Office (if enabled in Settings)."""
    return (g.user.role == 'hod' and setting('routine_hod', '1') == '1') or (g.user.role == 'office' and setting('routine_office', '1') == '1')

def routine_courses():
    """Courses whose slots the current user may change. Teachers: their own courses. Staff: only with an explicit 'routine_manage' grant."""
    if routine_editor(): return Course.query.order_by(Course.code).all()
    if g.user.role != 'staff': return []
    own = teaching(g.user)
    extra = [c for c in Course.query.order_by(Course.code) if c not in own and has_perm(g.user, 'routine_manage', c.id)]
    return sorted(own + extra, key=lambda c: c.code)

@portal.route('/routine', methods=['GET', 'POST'])
@roles_required('student', 'staff', 'hod', 'office')
def routine():
    allowed = {c.id for c in routine_courses()}
    if request.method == 'POST':
        f = request.form
        if f.get('act') == 'delete':
            x = db.session.get(TimetableSlot, int(f['sid'])) or abort(404)
            if x.course_id not in allowed: abort(403)
            audit('routine_delete', f'{g.user.name} ({g.user.role}): {x.course.code} {x.day} {x.start}-{x.end} room {x.room}'); db.session.delete(x)
        else:
            c = db.session.get(Course, int(f['course_id'])) or abort(404)
            if c.id not in allowed: abort(403)
            if f.get('day') not in DAYS or not f.get('start') or not f.get('end') or f['end'] <= f['start']: flash('Choose a day and a valid start and end time (end after start).', 'error'); return redirect(url_for('portal.routine'))
            db.session.add(TimetableSlot(day=f['day'], start=f['start'], end=f['end'], course_id=c.id, staff_id=c.staff_id, room=f.get('room', '')[:20], class_name=f.get('class_name', '')[:40] or f"{c.programme} Sem {c.semester}", programme=c.programme, semester=c.semester))
            audit('routine_add', f'{g.user.name} ({g.user.role}): {c.code} {f["day"]} {f["start"]}-{f["end"]} room {f.get("room", "")}')
        db.session.commit(); return redirect(url_for('portal.routine'))
    q = TimetableSlot.query
    if g.user.role == 'student':
        s = Student.query.filter_by(user_id=g.user.id).first_or_404(); q = q.filter_by(programme=s.programme, semester=s.semester)
    elif g.user.role == 'staff':
        q = q.filter(db.or_(TimetableSlot.staff_id == g.user.id, TimetableSlot.course_id.in_([c.id for c in teaching(g.user)] + list(allowed) or [0])))
    slots = sorted(q.all(), key=lambda x: (DAYS.index(x.day) if x.day in DAYS else 9, x.start))
    return render_template('routine.html', slots=slots, DAYS=DAYS, edit=bool(allowed), allowed=allowed, courses=routine_courses())

# ---------- HOD: THUNAI Impact ----------
@portal.route('/admin/impact')
@roles_required('hod')
def impact():
    studs = Student.query.all(); sigs = {s.id: student_signal(s.id) for s in studs}
    ids = {i.student_id for i in Intervention.query}; outs = [o for o in (intervention_outcome(i) for i in ids) if o and o.get('ready')]
    mean = lambda v: round(sum(v) / len(v), 1) if v else None
    imp = sum(1 for o in outs if o['improved'])
    d = dict(monitored=len(studs), identified=sum(1 for x in sigs.values() if x['level'] in ('Attention Recommended', 'Priority Support')), watch=sum(1 for x in sigs.values() if x['level'] == 'Monitor'),
             interventions=Intervention.query.count(), supported=len(ids), followups_done=Intervention.query.filter_by(follow_up_status='Completed').count(),
             followups_pending=Intervention.query.filter(Intervention.follow_up_status != 'Completed', Intervention.follow_up_date.isnot(None)).count(),
             n=len(outs), improved=imp, same=len(outs) - imp, pending=len(ids) - len(outs),
             rate=round(100 * imp / len(outs)) if outs else None, att=(mean([o['att'][0] for o in outs]), mean([o['att'][1] for o in outs])),
             ass=(mean([o['ass'][0] for o in outs]), mean([o['ass'][1] for o in outs])), ami=(mean([o['ami'][0] for o in outs]), mean([o['ami'][1] for o in outs])))
    cfg = charts.bar(['Attendance %', 'Assessment %', 'Academic Momentum'], [('Before', [d['att'][0], d['ass'][0], d['ami'][0]]), ('After', [d['att'][1], d['ass'][1], d['ami'][1]])], 'Average before vs after (students with interventions)', ymax=100) if outs else None
    return render_template('impact.html', d=d, cfg=cfg)
