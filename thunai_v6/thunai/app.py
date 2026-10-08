import os
from datetime import timedelta
from flask import Flask, render_template
from models import db
from security import init_security
from routes import auth, admin, mentor, student
from manage import manage
from academics import acad
from development import dev
from portal import portal

def ensure_columns():
    """Add columns introduced after a database was first created (SQLite, non-destructive)."""
    from sqlalchemy import text
    want = {'student': {'email':'VARCHAR(120)','phone':'VARCHAR(20)','address':'VARCHAR(200)','bio':'TEXT','photo':'VARCHAR(80)','is_demo':'BOOLEAN DEFAULT 0',
                        'father_name':'VARCHAR(80)','mother_name':'VARCHAR(80)','parent_phone':'VARCHAR(20)','dob':'VARCHAR(12)','guardian_name':'VARCHAR(80)','guardian_phone':'VARCHAR(20)','confirmed_by_student':'DATETIME','verified_at':'DATETIME','verified_by':'INTEGER'},
            'user': {'email':'VARCHAR(120)','is_demo':'BOOLEAN DEFAULT 0','must_change':'BOOLEAN DEFAULT 0','active':'BOOLEAN DEFAULT 1','designation':'VARCHAR(80)','department':'VARCHAR(80)','qualifications':'VARCHAR(200)','expertise':'VARCHAR(200)','research':'VARCHAR(200)','contact':'VARCHAR(120)','links':'VARCHAR(300)'}}
    want['supportrequest'] = {'subject': 'VARCHAR(120)', 'resolved_at': 'DATETIME'}
    want['notification'] = {'priority': "VARCHAR(10) DEFAULT 'Normal'", 'sender': 'VARCHAR(80)', 'action_url': 'VARCHAR(120)'}
    want['intervention'] = {'follow_up_status': "VARCHAR(12) DEFAULT 'Pending'", 'remarks': 'TEXT'}
    for t, cols in want.items():
        have = {r[1] for r in db.session.execute(text(f'PRAGMA table_info("{t}")'))}
        for c, typ in cols.items():
            if c not in have: db.session.execute(text(f'ALTER TABLE "{t}" ADD COLUMN {c} {typ}'))
    db.session.commit()

def migrate_roles():
    """v2 role model: old 'staff' (office) -> 'office'; old 'mentor'/'course' -> 'staff' (faculty with responsibilities)."""
    from sqlalchemy import text
    from models import User, Course, Permission
    if (db.session.execute(text('PRAGMA user_version')).scalar() or 0) >= 2: return
    db.session.execute(text("UPDATE user SET role='office' WHERE role='staff'"))
    db.session.execute(text("UPDATE user SET role='staff' WHERE role IN ('mentor','course')"))
    for c in Course.query.filter(Course.staff_id.isnot(None)):       # keep old course-staff behaviour via explicit grants
        for p in ('marks_upload', 'attendance_manage'):
            if not Permission.query.filter_by(user_id=c.staff_id, perm=p, course_id=c.id).first(): db.session.add(Permission(user_id=c.staff_id, perm=p, course_id=c.id))
    db.session.execute(text('PRAGMA user_version = 2')); db.session.commit()

def create_app(db_uri=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-only-change-me'),
                      SQLALCHEMY_DATABASE_URI=db_uri or 'sqlite:///campus_saathi.db',
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.environ.get('HTTPS') == '1', MAX_CONTENT_LENGTH=6*1024*1024, PERMANENT_SESSION_LIFETIME=timedelta(minutes=30))
    db.init_app(app); init_security(app)
    for bp in (auth, admin, mentor, student, manage, acad, dev, portal): app.register_blueprint(bp)
    @app.errorhandler(403)
    def _403(e): return render_template('error.html', code=403, msg='You do not have access to this page.'), 403
    @app.errorhandler(404)
    def _404(e): return render_template('error.html', code=404, msg='Page not found.'), 404
    with app.app_context():
        db.create_all(); ensure_columns(); migrate_roles()
        from models import User
        if not User.query.first():
            if os.environ.get('NO_DEMO') == '1':
                from werkzeug.security import generate_password_hash as H
                db.session.add(User(username='hod', name='HOD', role='hod', pw_hash=H(os.environ.get('HOD_PASSWORD','ChangeMe@123')))); db.session.commit()
            else:
                from seed import seed; seed()
    return app

if __name__ == '__main__':
    create_app().run(debug=False)
