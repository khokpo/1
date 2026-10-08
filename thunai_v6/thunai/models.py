from datetime import date, datetime
from flask_sqlalchemy import SQLAlchemy
db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # hod|staff|mentor|student
    pw_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(120)); is_demo = db.Column(db.Boolean, default=False)
    must_change = db.Column(db.Boolean, default=False)  # temp password issued by office
    active = db.Column(db.Boolean, default=True)        # inactive accounts cannot sign in
    # teacher profile (edited by Office/HOD only)
    designation = db.Column(db.String(80)); department = db.Column(db.String(80)); qualifications = db.Column(db.String(200))
    expertise = db.Column(db.String(200)); research = db.Column(db.String(200)); contact = db.Column(db.String(120)); links = db.Column(db.String(300))

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    reg_no = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(80), nullable=False)
    programme = db.Column(db.String(60), nullable=False)
    semester = db.Column(db.String(5), nullable=False)
    created = db.Column(db.Date, default=date.today)
    email = db.Column(db.String(120)); phone = db.Column(db.String(20))
    address = db.Column(db.String(200)); bio = db.Column(db.Text); photo = db.Column(db.String(80))
    is_demo = db.Column(db.Boolean, default=False)
    dob = db.Column(db.String(12)); guardian_name = db.Column(db.String(80)); guardian_phone = db.Column(db.String(20))
    confirmed_by_student = db.Column(db.DateTime)   # student says "my details are correct"
    verified_at = db.Column(db.DateTime); verified_by = db.Column(db.Integer)  # only Office/HOD can verify
    father_name = db.Column(db.String(80)); mother_name = db.Column(db.String(80)); parent_phone = db.Column(db.String(20))

class MentorGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    programme = db.Column(db.String(60)); academic_year = db.Column(db.String(10))
    semester = db.Column(db.String(5)); description = db.Column(db.String(200))
    mentor_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    status = db.Column(db.String(10), default='active')
    mentor = db.relationship('User')

class MentorAssignment(db.Model):
    """Historical allocation: a row is never overwritten, only closed (end_date set)."""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), index=True)
    mentor_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    group_id = db.Column(db.Integer, db.ForeignKey('mentor_group.id'))
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    reason = db.Column(db.String(200)); by_user = db.Column(db.Integer, db.ForeignKey('user.id'))
    student = db.relationship('Student'); mentor = db.relationship('User', foreign_keys=[mentor_id])
    group = db.relationship('MentorGroup')

class AcademicRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), index=True)
    period = db.Column(db.Integer, nullable=False)  # 1..n
    period_date = db.Column(db.Date)
    attendance = db.Column(db.Float); assessment = db.Column(db.Float)
    assignment_pct = db.Column(db.Float); late_submissions = db.Column(db.Integer, default=0)

class SupportRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), index=True)
    category = db.Column(db.String(40)); message = db.Column(db.Text)
    status = db.Column(db.String(20), default='Submitted')
    response = db.Column(db.Text); created = db.Column(db.DateTime, default=datetime.utcnow)
    subject = db.Column(db.String(120)); resolved_at = db.Column(db.DateTime)
    student = db.relationship('Student')

SUPPORT_STATUSES = ['Submitted', 'Under Review', 'In Progress', 'Resolved', 'Rejected', 'Closed']
SUPPORT_CLOSED = ('Resolved', 'Rejected', 'Closed')

def set_support_status(r, status):
    """Single place where a request's status changes; stamps the resolution date."""
    if status not in SUPPORT_STATUSES and status not in ('Assigned', 'Follow-up'): status = 'In Progress'
    r.status = status; r.resolved_at = datetime.utcnow() if status in SUPPORT_CLOSED else None

class Intervention(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), index=True)
    mentor_id = db.Column(db.Integer, db.ForeignKey('user.id'))  # mentor at time of record
    itype = db.Column(db.String(40)); description = db.Column(db.Text)
    action_taken = db.Column(db.Text); student_response = db.Column(db.Text)
    on_date = db.Column(db.Date, default=date.today)
    follow_up_date = db.Column(db.Date); follow_up_done = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='In Progress')
    follow_up_status = db.Column(db.String(12), default='Pending')  # Pending | Completed | Rescheduled
    remarks = db.Column(db.Text)
    student = db.relationship('Student'); mentor = db.relationship('User')

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    text = db.Column(db.String(200)); created = db.Column(db.DateTime, default=datetime.utcnow)
    read = db.Column(db.Boolean, default=False)
    priority = db.Column(db.String(10), default='Normal'); sender = db.Column(db.String(80)); action_url = db.Column(db.String(120))

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer); action = db.Column(db.String(60))
    detail = db.Column(db.String(300)); created = db.Column(db.DateTime, default=datetime.utcnow)


class ProfileChange(db.Model):
    """Student-submitted correction to an office-entered detail. Applied only after Office/HOD approval."""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), index=True)
    field = db.Column(db.String(30)); old_value = db.Column(db.String(200)); new_value = db.Column(db.String(200))
    reason = db.Column(db.String(300)); status = db.Column(db.String(10), default='Pending')
    decided_by = db.Column(db.Integer); decided_at = db.Column(db.DateTime); decision_note = db.Column(db.String(200))
    created = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('Student')

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), nullable=False); name = db.Column(db.String(100), nullable=False)
    programme = db.Column(db.String(60)); semester = db.Column(db.String(5))
    staff_id = db.Column(db.Integer, db.ForeignKey('user.id')); active = db.Column(db.Boolean, default=True)
    staff = db.relationship('User')

class Mark(db.Model):
    """One score per student per course per exam type (re-upload overwrites)."""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), index=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), index=True)
    exam_type = db.Column(db.String(20), nullable=False)
    score = db.Column(db.Float, nullable=False); max_score = db.Column(db.Float, nullable=False, default=100)
    uploaded_by = db.Column(db.Integer); updated = db.Column(db.DateTime, default=datetime.utcnow)
    student = db.relationship('Student'); course = db.relationship('Course')
    @property
    def pct(self): return round(100 * self.score / self.max_score, 1) if self.max_score else 0


class DevRecord(db.Model):
    """Student development record (research, internship, workshop, ...). One table keyed by category.
    Student-submitted; only Office/HOD can set status to Verified."""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), index=True)
    category = db.Column(db.String(20), index=True)
    title = db.Column(db.String(200)); description = db.Column(db.Text)
    start_date = db.Column(db.Date); end_date = db.Column(db.Date)
    organization = db.Column(db.String(200)); role = db.Column(db.String(80)); level = db.Column(db.String(40))
    extra = db.Column(db.Text, default='{}')            # category-specific fields (JSON)
    evidence_id = db.Column(db.Integer)
    status = db.Column(db.String(24), default='Pending Verification')
    submitted_by = db.Column(db.Integer); submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    verified_by = db.Column(db.Integer); verified_at = db.Column(db.DateTime); remarks = db.Column(db.String(300))
    student = db.relationship('Student')
    @property
    def extras(self):
        import json
        try: return json.loads(self.extra or '{}')
        except ValueError: return {}

class DevDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), index=True); record_id = db.Column(db.Integer)
    doc_type = db.Column(db.String(30)); stored_name = db.Column(db.String(80)); original_name = db.Column(db.String(120))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow); uploaded_by = db.Column(db.Integer)

class VerificationLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.Integer, index=True); action = db.Column(db.String(30)); by_user = db.Column(db.Integer)
    at = db.Column(db.DateTime, default=datetime.utcnow); remarks = db.Column(db.String(300))

class CategoryNA(db.Model):
    """Student declares a category 'not applicable' — distinct from 'not reported'."""
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), index=True); category = db.Column(db.String(20))


class Permission(db.Model):
    """Office/HOD-granted permission to a Staff account. course_id/scope NULL = any course / any exam."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True); perm = db.Column(db.String(30), index=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id')); scope = db.Column(db.String(30))
    granted_by = db.Column(db.Integer); granted_at = db.Column(db.DateTime, default=datetime.utcnow); active = db.Column(db.Boolean, default=True)
    user = db.relationship('User', foreign_keys=[user_id]); course = db.relationship('Course')

class Responsibility(db.Model):
    """Coordinator / other responsibilities. Teacher = Course.staff_id; Mentor = active MentorGroup.mentor_id."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True); kind = db.Column(db.String(20)); course_id = db.Column(db.Integer, db.ForeignKey('course.id'))
    note = db.Column(db.String(120)); assigned_by = db.Column(db.Integer); created = db.Column(db.DateTime, default=datetime.utcnow)
    course = db.relationship('Course')

class StaffRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_user = db.Column(db.Integer, db.ForeignKey('user.id')); to_role = db.Column(db.String(10)); kind = db.Column(db.String(40)); message = db.Column(db.Text)
    status = db.Column(db.String(12), default='Pending'); response = db.Column(db.Text); created = db.Column(db.DateTime, default=datetime.utcnow)
    decided_by = db.Column(db.Integer); decided_at = db.Column(db.DateTime); sender = db.relationship('User', foreign_keys=[from_user])

class ResetRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40)); note = db.Column(db.String(200)); status = db.Column(db.String(12), default='Pending')
    created = db.Column(db.DateTime, default=datetime.utcnow); handled_by = db.Column(db.Integer)

class TimetableSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    day = db.Column(db.String(10)); start = db.Column(db.String(5)); end = db.Column(db.String(5))
    course_id = db.Column(db.Integer, db.ForeignKey('course.id')); staff_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    room = db.Column(db.String(20)); class_name = db.Column(db.String(40)); programme = db.Column(db.String(60)); semester = db.Column(db.String(5))
    course = db.relationship('Course'); staff = db.relationship('User')

class CourseAttendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), index=True); student_id = db.Column(db.Integer, db.ForeignKey('student.id'), index=True)
    on_date = db.Column(db.Date, nullable=False); present = db.Column(db.Boolean, default=True); marked_by = db.Column(db.Integer)

class Setting(db.Model):
    key = db.Column(db.String(40), primary_key=True); value = db.Column(db.String(200))
