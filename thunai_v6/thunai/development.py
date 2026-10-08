"""Student Development Profile: self-declared records, Office verification, evidence, snapshot, analytics, report.
Rules: students cannot verify; only VERIFIED (and de-duplicated, non-expired) records count in official analytics;
'Not reported' is never shown as 'No activity'; there is NO single combined score."""
import os, json, uuid
from datetime import date, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, current_app, send_from_directory
from models import *
from security import roles_required, audit, notify
import mentorship as ms, charts
from analytics import student_signal
from devconfig import *

dev = Blueprint('dev', __name__)
MAX_DOC = 3 * 1024 * 1024

def _d(v):
    try: return date.fromisoformat(v.strip()[:10]) if v and v.strip() else None
    except ValueError: return None

def eff_status(r):
    if r.status == 'Verified' and r.category == 'certification':
        e = _d(r.extras.get('expiry_date'))
        if e and e < date.today(): return 'Expired / Outdated'
    return r.status

def _dedupe(rs):
    seen, out = set(), []
    for r in sorted(rs, key=lambda x: x.id):
        k = (r.category, (r.title or '').strip().lower(), r.start_date)
        if k not in seen: seen.add(k); out.append(r)
    return out

def skill_label(r): return 'Verified' if r.status == 'Verified' else ('Evidence Submitted' if r.evidence_id else 'Self-Declared')

@dev.app_context_processor
def _ctx(): return dict(skill_label=skill_label, eff_status=eff_status, DCATS=CATS)

def band(v):
    for n, name in BANDS:
        if v >= n: return name
    return None

def snapshot(sid):
    recs = DevRecord.query.filter_by(student_id=sid).all(); na = {x.category for x in CategoryNA.query.filter_by(student_id=sid)}
    ver = [r for r in _dedupe([r for r in recs if eff_status(r) == 'Verified'])]
    cnt = {}
    for c in CATS:
        rc = [r for r in recs if r.category == c]
        cnt[c] = dict(verified=sum(1 for r in ver if r.category == c), pending=sum(1 for r in rc if r.status == 'Pending Verification'),
                      attention=sum(1 for r in rc if r.status in ('Rejected', 'Requires Correction')), expired=sum(1 for r in rc if eff_status(r) == 'Expired / Outdated'),
                      total=len(rc), na=c in na)
    dims = []
    for d in DIMS:
        cs = [c for c in CATS if CATS[c]['dim'] == d]; v = sum(cnt[c]['verified'] for c in cs); p = sum(cnt[c]['pending'] for c in cs)
        lvl = band(v) or ('Self-declared only' if p else ('Not applicable' if all(cnt[c]['na'] for c in cs) else 'Not reported'))
        dims.append(dict(name=d, verified=v, pending=p, level=lvl))
    conf = [r for r in ver if r.category == 'conference']
    tl = sorted([r for r in recs if r.category != 'academic'], key=lambda r: r.start_date or r.end_date or r.submitted_at.date())
    return dict(cnt=cnt, dims=dims, recs=recs, ver=ver, tl=tl, achievements=cnt['achievement']['verified'],
                presented=sum(1 for r in conf if 'Presenter' in (r.role or '')), attended=sum(1 for r in conf if 'Presenter' not in (r.role or '')))

def completeness(sid, sn):
    items = [('Basic profile', bool(db.session.get(Student, sid).confirmed_by_student))]
    for c in CATS: items.append((CATS[c]['label'], sn['cnt'][c]['total'] > 0 or sn['cnt'][c]['na']))
    done = sum(1 for _, ok in items if ok); return dict(items=items, pct=round(100 * done / len(items)))

def holistic_note(sig, sn):
    """Contextual prompt built only from real data. Not a conclusion about the student."""
    if sig['level'] == 'Stable': return None
    parts = [f"{x['verified']} verified {k}" for k, x in (('research', sn['cnt']['research']), ('internship', sn['cnt']['internship']), ('certification', sn['cnt']['certification']),
             ('leadership', sn['cnt']['leadership']), ('workshop', sn['cnt']['workshop'])) if x['verified']]
    if sn['presented']: parts.append(f"{sn['presented']} verified conference presentation(s)")
    if sum(x['verified'] for x in sn['cnt'].values()) < 3 or not parts: return None
    return ("Academic indicators currently show an early-support signal (" + sig['level'] + "), while verified records include " + ', '.join(parts) +
            ". Consider exploring workload, time management and course-specific difficulties with the student rather than assuming low engagement. This is a prompt for conversation, not a conclusion.")

# ---------------- evidence ----------------
def _edir():
    d = os.path.join(current_app.instance_path, 'evidence'); os.makedirs(d, exist_ok=True); return d

def _ext_ok(name, head):
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    ok = {'pdf': head.startswith(b'%PDF'), 'jpg': head.startswith(b'\xff\xd8\xff'), 'jpeg': head.startswith(b'\xff\xd8\xff'),
          'png': head.startswith(b'\x89PNG\r\n\x1a\n'), 'docx': head.startswith(b'PK\x03\x04')}
    return ext if ok.get(ext) else None

def save_evidence(s, rec, f, dtype):
    data = f.read()
    ext = _ext_ok(f.filename, data[:8])
    if not ext or len(data) > MAX_DOC: return 'Evidence must be a PDF, JPG, PNG or DOCX file under 3 MB.'
    name = f'{uuid.uuid4().hex}.{ext}'; open(os.path.join(_edir(), name), 'wb').write(data)
    doc = DevDocument(student_id=s.id, record_id=rec.id, doc_type=dtype if dtype in DOC_TYPES else 'Certificate', stored_name=name, original_name=os.path.basename(f.filename)[:120], uploaded_by=g.user.id)
    db.session.add(doc); db.session.flush(); rec.evidence_id = doc.id; return None

def can_see_student(s):
    r = g.user.role
    return r in ('hod', 'office') or (r == 'student' and s.user_id == g.user.id) or (r == 'staff' and ms.mentor_owns(g.user.id, s.id))

@dev.route('/evidence/<int:did>')
def evidence(did):
    if not g.user: abort(403)
    d = db.session.get(DevDocument, did) or abort(404); s = db.session.get(Student, d.student_id)
    if not can_see_student(s): abort(403)   # students: own only; mentors: assigned only
    return send_from_directory(_edir(), d.stored_name, as_attachment=True, download_name=d.original_name)

# ---------------- student ----------------
def me():
    return Student.query.filter_by(user_id=g.user.id).first() or abort(404)

@dev.route('/student/development')
@roles_required('student')
def home():
    s = me(); sn = snapshot(s.id); cats = list(CATS)
    cfg = charts.bar([CATS[c]['label'] for c in cats], [('Verified', [sn['cnt'][c]['verified'] for c in cats]), ('Pending', [sn['cnt'][c]['pending'] for c in cats]),
                      ('Needs attention', [sn['cnt'][c]['attention'] for c in cats])], 'My records by section', stacked=True, horizontal=True)
    fix = [r for r in sn['recs'] if r.status in ('Rejected', 'Requires Correction')]
    return render_template('dev_home.html', s=s, sn=sn, comp=completeness(s.id, sn), cfg=cfg, fix=fix, CATS=CATS)

def _form_to_record(cat, rec, s):
    c = CATS[cat]; f = request.form
    rec.title = 'Academic profile' if c['single'] and cat == 'academic' else f.get('title', '').strip()[:200]
    if not rec.title: return 'A title is required.'
    rec.description = f.get('description', '').strip()[:2000]
    rec.organization = f.get('organization', '').strip()[:200] if c['org'] else None
    ro = f.get('role', '').strip()[:80]; rec.role = (ro if (not c['role_opts'] or ro in c['role_opts']) else None) if c['role'] else None
    lv = f.get('level', '').strip(); rec.level = lv if c['level_opts'] and lv in c['level_opts'] else None
    if c['dates']:
        rec.start_date = _d(f.get('start_date')); rec.end_date = _d(f.get('end_date')) if c['dates'] == 'range' else None
        if rec.start_date and rec.end_date and rec.end_date < rec.start_date: return 'End date cannot be before the start date.'
    ex = {}
    for k, _, opts in c['extra']:
        v = f.get(k, '').strip()[:300]
        if opts and v not in opts: v = ''
        ex[k] = v
    rec.extra = json.dumps(ex); return None

def _resubmit(rec, who, note):
    rec.status = 'Pending Verification'; rec.verified_by = rec.verified_at = None; rec.remarks = None
    db.session.add(VerificationLog(record_id=rec.id, action=note, by_user=who))

@dev.route('/student/dev/<cat>', methods=['GET', 'POST'])
@roles_required('student')
def category(cat):
    if cat not in CATS: abort(404)
    s = me(); c = CATS[cat]
    if request.method == 'POST':
        if c['single'] and cat == 'academic' and DevRecord.query.filter_by(student_id=s.id, category='academic').first(): flash('You already have an academic profile — edit it below.', 'error'); return redirect(url_for('dev.category', cat=cat))
        r = DevRecord(student_id=s.id, category=cat, submitted_by=g.user.id); err = _form_to_record(cat, r, s)
        if not err:
            db.session.add(r); db.session.flush(); fl = request.files.get('evidence')
            if fl and fl.filename: err = save_evidence(s, r, fl, request.form.get('doc_type'))
        if err: db.session.rollback(); flash(err, 'error')
        else:
            db.session.add(VerificationLog(record_id=r.id, action='submitted', by_user=g.user.id))
            for u in User.query.filter(User.role.in_(('office', 'hod'))): notify(u.id, f'New {c["label"].lower()} record from {s.reg_no} awaiting verification.')
            audit('dev_submit', f'{s.reg_no} {cat}: {r.title}'); db.session.commit(); flash('Saved. It is now Pending Verification until the office verifies it.', 'ok')
        return redirect(url_for('dev.category', cat=cat))
    recs = DevRecord.query.filter_by(student_id=s.id, category=cat).order_by(DevRecord.submitted_at.desc()).all()
    docs = {d.id: d for d in DevDocument.query.filter_by(student_id=s.id)}
    na = CategoryNA.query.filter_by(student_id=s.id, category=cat).first() is not None
    return render_template('dev_category.html', s=s, cat=cat, c=c, recs=recs, docs=docs, na=na, DOC_TYPES=DOC_TYPES, show_form=not (cat == 'academic' and recs))

@dev.route('/student/dev/record/<int:rid>/edit', methods=['POST'])
@roles_required('student')
def record_edit(rid):
    r = db.session.get(DevRecord, rid) or abort(404); s = me()
    if r.student_id != s.id: abort(403)
    err = _form_to_record(r.category, r, s)
    fl = request.files.get('evidence')
    if not err and fl and fl.filename: err = save_evidence(s, r, fl, request.form.get('doc_type'))
    if err: db.session.rollback(); flash(err, 'error')
    else:
        was = r.status; _resubmit(r, g.user.id, 'resubmitted' if was != 'Pending Verification' else 'edited')   # edits always need (re-)verification
        audit('dev_edit', f'{s.reg_no} {r.category}: {r.title}'); db.session.commit(); flash('Updated and sent for verification.', 'ok')
    return redirect(url_for('dev.category', cat=r.category))

@dev.route('/student/dev/record/<int:rid>/delete', methods=['POST'])
@roles_required('student')
def record_delete(rid):
    r = db.session.get(DevRecord, rid) or abort(404)
    if r.student_id != me().id: abort(403)
    if r.status == 'Verified': flash('Verified records can only be removed by the office.', 'error')
    else: audit('dev_delete', f'{r.student.reg_no} {r.category}: {r.title}'); db.session.delete(r); db.session.commit(); flash('Record deleted.', 'ok')
    return redirect(url_for('dev.category', cat=r.category))

@dev.route('/student/dev/<cat>/na', methods=['POST'])
@roles_required('student')
def toggle_na(cat):
    if cat not in CATS: abort(404)
    s = me(); x = CategoryNA.query.filter_by(student_id=s.id, category=cat).first()
    if x: db.session.delete(x)
    else: db.session.add(CategoryNA(student_id=s.id, category=cat))
    db.session.commit(); return redirect(url_for('dev.category', cat=cat))

# ---------------- Office / HOD: Verification Center ----------------
@dev.route('/admin/verification')
@roles_required('hod', 'office')
def verification():
    a = request.args; q = DevRecord.query.join(Student, Student.id == DevRecord.student_id)
    if a.get('cat') in CATS: q = q.filter(DevRecord.category == a['cat'])
    st = a.get('status', 'Pending Verification')
    if st in STATUSES: q = q.filter(DevRecord.status == st)
    if a.get('programme'): q = q.filter(Student.programme == a['programme'])
    if a.get('semester'): q = q.filter(Student.semester == a['semester'])
    if a.get('q'): q = q.filter(db.or_(Student.name.ilike(f"%{a['q']}%"), Student.reg_no.ilike(f"%{a['q']}%")))
    p = q.order_by(DevRecord.submitted_at).paginate(page=max(1, a.get('page', 1, type=int)), per_page=25, error_out=False)
    today = datetime.utcnow().date()
    stats = dict(pending=DevRecord.query.filter_by(status='Pending Verification').count(), today=VerificationLog.query.filter(VerificationLog.action == 'verified', db.func.date(VerificationLog.at) == today.isoformat()).count(),
                 rejected=DevRecord.query.filter_by(status='Rejected').count(), correction=DevRecord.query.filter_by(status='Requires Correction').count(), total=DevRecord.query.count())
    dup = {r.id: DevRecord.query.filter(DevRecord.student_id == r.student_id, DevRecord.category == r.category, DevRecord.id < r.id, db.func.lower(DevRecord.title) == (r.title or '').strip().lower(), DevRecord.start_date == r.start_date).count() > 0 for r in p.items}
    progs = [x[0] for x in db.session.query(Student.programme).distinct()]
    return render_template('verification.html', p=p, stats=stats, dup=dup, progs=progs, st=st, STATUSES=STATUSES, a=a)

@dev.route('/admin/verification/<int:rid>', methods=['GET', 'POST'])
@roles_required('hod', 'office')
def verify_record(rid):
    r = db.session.get(DevRecord, rid) or abort(404)
    if request.method == 'POST':
        act, rem = request.form.get('act'), request.form.get('remarks', '').strip()[:300]
        m = {'verify': 'Verified', 'reject': 'Rejected', 'correction': 'Requires Correction', 'outdated': 'Expired / Outdated'}
        if act not in m: abort(400)
        if act in ('reject', 'correction') and not rem: flash('A reason / correction message is required.', 'error'); return redirect(url_for('dev.verify_record', rid=rid))
        r.status = m[act]; r.verified_by, r.verified_at, r.remarks = g.user.id, datetime.utcnow(), rem or None
        db.session.add(VerificationLog(record_id=r.id, action={'verify': 'verified', 'reject': 'rejected', 'correction': 'correction requested', 'outdated': 'marked outdated'}[act], by_user=g.user.id, remarks=rem))
        notify(r.student.user_id, f'Your {CATS[r.category]["label"].lower()} record "{r.title}" is now: {r.status}.')
        audit('dev_' + act, f'{g.user.name}: {r.student.reg_no} {r.category}: {r.title}'); db.session.commit(); flash(f'Record marked {r.status}.', 'ok')
        return redirect(url_for('dev.verification'))
    logs = VerificationLog.query.filter_by(record_id=r.id).order_by(VerificationLog.at).all()
    doc = db.session.get(DevDocument, r.evidence_id) if r.evidence_id else None
    return render_template('verification_detail.html', r=r, c=CATS[r.category], logs=logs, doc=doc, users={u.id: u.name for u in User.query})

# ---------------- HOD analytics (verified data only) ----------------
@dev.route('/admin/development')
@roles_required('hod')
def analytics():
    studs = Student.query.all(); progs = sorted({s.programme for s in studs}); recs = DevRecord.query.all()
    byst = {}
    for r in recs:
        if eff_status(r) == 'Verified': byst.setdefault(r.student_id, []).append(r)
    ver = [x for v in byst.values() for x in _dedupe(v)]
    have = lambda cat, st_: sum(1 for s in st_ if any(r.category == cat for r in _dedupe(byst.get(s.id, []))))
    n = lambda cat: sum(1 for r in ver if r.category == cat)
    pres = sum(1 for r in ver if r.category == 'conference' and 'Presenter' in (r.role or ''))
    tiles = [('Students with a verified internship', have('internship', studs)), ('Verified research records', n('research')), ('Verified conference presentations', pres),
             ('Students with a verified workshop', have('workshop', studs)), ('Students with a verified certification', have('certification', studs)),
             ('Students with verified sports participation', have('sports', studs)), ('Students with verified cultural participation', have('cultural', studs)),
             ('Students with a verified leadership role', have('leadership', studs)), ('Verified achievements', n('achievement'))]
    cats = ['research', 'internship', 'workshop', 'conference', 'certification', 'sports', 'cultural', 'leadership', 'volunteering']
    rows, sets = [], []
    for p in progs:
        ps = [s for s in studs if s.programme == p]; pct = [round(100 * have(c, ps) / len(ps), 1) for c in cats]; rows.append((p, len(ps), pct)); sets.append((p, pct))
    cfg = charts.bar([CATS[c]['label'] for c in cats], sets, '% of students with at least one verified record, by programme', ymax=100) if sets else None
    pend = DevRecord.query.filter_by(status='Pending Verification').count()
    return render_template('dev_analytics.html', tiles=tiles, rows=rows, cats=cats, cfg=cfg, pend=pend, total=len(studs), CATS=CATS)

# ---------------- Mentor / Office view and printable report ----------------
def _student_for_view(reg):
    s = Student.query.filter_by(reg_no=reg).first_or_404()
    if g.user.role == 'staff' and not ms.mentor_owns(g.user.id, s.id): abort(403)
    return s

@dev.route('/mentor/student/<reg>/development')
@dev.route('/admin/students/<reg>/development')
@roles_required('staff', 'hod', 'office')
def student_dev(reg):
    s = _student_for_view(reg); sn = snapshot(s.id); sig = student_signal(s.id)
    return render_template('dev_student.html', s=s, sn=sn, sig=sig, note=holistic_note(sig, sn) if g.user.role in ('staff', 'hod') else None, comp=completeness(s.id, sn), mentor_view=g.user.role == 'staff')

@dev.route('/student/report', defaults={'reg': None})
@dev.route('/mentor/student/<reg>/report')
@dev.route('/admin/students/<reg>/report')
@roles_required('student', 'staff', 'hod', 'office')
def report(reg):
    s = me() if g.user.role == 'student' else _student_for_view(reg)
    sn = snapshot(s.id); sig = student_signal(s.id); full = g.user.role in ('staff', 'hod')   # Office: no signals/interventions
    ivs = Intervention.query.filter_by(student_id=s.id).order_by(Intervention.on_date).all() if full else []
    from academics import marks_cfgs
    by, cs, _, _ = marks_cfgs(s.id)
    docs = {d.id: d for d in DevDocument.query.filter_by(student_id=s.id)}
    audit('report_view', f'{g.user.name} viewed report for {s.reg_no}'); db.session.commit()
    return render_template('dev_report.html', s=s, sn=sn, sig=sig, ivs=ivs, full=full, by=by, cs=cs, CATS=CATS, docs=docs, a=ms.active_assignment(s.id), today=date.today())
