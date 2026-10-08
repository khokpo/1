import secrets
from functools import wraps
from flask import session, abort, request, redirect, url_for, g
from models import db, User, Notification, AuditLog, MentorGroup, Permission, Setting

def csrf_token():
    if '_csrf' not in session: session['_csrf'] = secrets.token_hex(16)
    return session['_csrf']

def init_security(app):
    app.jinja_env.globals['csrf_token'] = csrf_token
    @app.before_request
    def _guard():
        session.permanent = True      # idle timeout via PERMANENT_SESSION_LIFETIME
        g.user = db.session.get(User, session['uid']) if 'uid' in session else None
        # Office-issued temporary password must be changed before anything else
        if g.user and g.user.must_change and request.endpoint not in ('auth.account', 'auth.logout', 'static'):
            return redirect(url_for('auth.account'))
        if request.method == 'POST' and request.form.get('_csrf') != session.get('_csrf'):
            abort(400, 'Invalid CSRF token')
    @app.context_processor
    def _ctx():
        n = Notification.query.filter_by(user_id=g.user.id, read=False).count() if g.user else 0
        return dict(me=g.user, unread=n, is_mentor=bool(g.user and is_mentor(g.user)), can=lambda p, c=None, sc=None: bool(g.user and has_perm(g.user, p, c, sc)))

def roles_required(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if not g.user: return redirect(url_for('auth.login'))
            if g.user.role not in roles: abort(403)  # enforced server-side, not just hidden menus
            return f(*a, **k)
        return w
    return deco

def audit(action, detail):
    db.session.add(AuditLog(user_id=g.user.id if g.get('user') else None, action=action, detail=detail[:300]))

def notify(user_id, text, priority='Normal', url=None):
    if user_id: db.session.add(Notification(user_id=user_id, text=text[:200], priority=priority, action_url=url, sender=(g.user.name if g.get('user') else 'System')))

def is_mentor(user):
    """Mentor is a responsibility of a Staff account (assigned by Office): an active mentor group exists for them."""
    if user.role != 'staff': return False
    return MentorGroup.query.filter_by(mentor_id=user.id, status='active').first() is not None

def mentor_required(f):
    @wraps(f)
    def w(*a, **k):
        if not g.user: return redirect(url_for('auth.login'))
        if not is_mentor(g.user): abort(403)    # no mentorship functions unless Office assigned the responsibility
        return f(*a, **k)
    return w

def has_perm(user, perm, course_id=None, scope=None):
    """Staff need an explicit grant. course_id/scope None on the grant = any course/any exam."""
    if user.role != 'staff': return False
    q = Permission.query.filter_by(user_id=user.id, perm=perm, active=True)
    for p in q:
        if course_id is not None and p.course_id not in (None, course_id): continue
        if scope is not None and p.scope not in (None, scope): continue
        return True
    return False

def setting(key, default=''):
    x = db.session.get(Setting, key); return x.value if x else default

import string
def temp_password():
    """Random one-time password, e.g. 'Kx7-mQ4pRt2'. Shown once to Office; user must change it at first login."""
    a = string.ascii_letters.replace('l', '').replace('I', '').replace('O', '') + '23456789'
    return ''.join(secrets.choice(a) for _ in range(3)) + '-' + ''.join(secrets.choice(a) for _ in range(8))
