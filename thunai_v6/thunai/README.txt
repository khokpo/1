THUNAI - Timely Help & Unified Nurturing for Academic Improvement
Every Student. Every Step. Supported.
Observe -> Identify -> Understand -> Intervene -> Follow up -> Measure -> Improve

Run:   pip install -r requirements.txt   then   python app.py   -> http://127.0.0.1:5000
Tests: python tests/test_smoke.py ; test_manage.py ; test_academics.py ; test_roles.py ; test_development.py

Support status wording (no 'fail' labels): Stable | Monitor | Attention Recommended | Priority Support
Login categories: Student | Staff | HOD | Office  (Mentor/Teacher/Coordinator are RESPONSIBILITIES of a Staff account, assigned by Office)
Demo logins (password demo123; demo data only): s01 (Student), priya (Staff: teacher + mentor), meena / ravi (Staff: teachers), hod (HOD), office (Office)
Fresh start without demo data: delete the instance folder, set NO_DEMO=1 and HOD_PASSWORD=..., then run.
Upgrading from Campus Saathi v4: unzip over the old folder, KEEP instance/ and venv/. The database file keeps its old name (campus_saathi.db) so existing data carries over.
Production: set SECRET_KEY and HTTPS=1; sessions expire after 30 minutes idle.

v6 changes: portals Student/Teacher/Mentor/Staff/HOD (+Office); Student nav = Dashboard, My Profile, Request Support; Staff nav = Dashboard, Students, Detail Corrections, Courses, Support & Requests, Data Upload.
Support requests: title, 6 statuses, request number, resolution date (new columns are added automatically on start). Timetable: teachers edit own courses, HOD/Office, staff only with the 'Timetable management' permission.
Teacher profile details are edited by Office/HOD on Staff & Workload > staff member. New test file: tests/test_ui_roles.py
