from datetime import date
from models import db, MentorAssignment, Student, User

def active_assignment(student_id):
    return MentorAssignment.query.filter_by(student_id=student_id, end_date=None).first()

def assign(student_ids, mentor_id, group_id, by_user, reason='Initial allocation', effective=None):
    """Close the current assignment (keeps history) and open a new one."""
    effective = effective or date.today(); n = 0
    for sid in student_ids:
        cur = active_assignment(sid)
        if cur and cur.mentor_id == mentor_id and cur.group_id == group_id: continue
        if cur: cur.end_date = effective
        db.session.add(MentorAssignment(student_id=sid, mentor_id=mentor_id, group_id=group_id,
                       start_date=effective, reason=reason, by_user=by_user)); n += 1
    return n

def students_of(mentor_id):
    return (Student.query.join(MentorAssignment, MentorAssignment.student_id == Student.id)
            .filter(MentorAssignment.mentor_id == mentor_id, MentorAssignment.end_date.is_(None)).all())

def unassigned():
    ids = db.session.query(MentorAssignment.student_id).filter(MentorAssignment.end_date.is_(None))
    return Student.query.filter(~Student.id.in_(ids)).all()

def mentor_owns(mentor_id, student_id):
    a = active_assignment(student_id)
    return bool(a and a.mentor_id == mentor_id)
