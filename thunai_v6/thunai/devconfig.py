"""Student Development Profile configuration: categories, their fields, and analytics dimensions."""
LEVELS6 = ['Department', 'University', 'District', 'State', 'National', 'International']
PART = ['Participant', 'Paper Presenter', 'Poster Presenter', 'Session Chair', 'Volunteer', 'Organizer']
DOC_TYPES = ['Certificate', 'Letter', 'Offer Letter', 'Completion Letter', 'Publication', 'Conference Proof', 'Project Report', 'Award Proof', 'Participation Proof']
STATUSES = ['Pending Verification', 'Verified', 'Rejected', 'Requires Correction', 'Expired / Outdated']

def C(label, dim, title='Title', org=None, role=None, role_opts=None, level_opts=None, dates='range', extra=(), single=False, doc='Certificate'):
    return dict(label=label, dim=dim, title=title, org=org, role=role, role_opts=role_opts, level_opts=level_opts, dates=dates, extra=list(extra), single=single, doc=doc)

CATS = {
 'academic': C('Academic profile', None, single=True, dates=None, doc='Certificate', extra=[
     ('previous_qualification', 'Previous qualification', None), ('previous_institution', 'Previous institution', None), ('ug_degree', 'UG degree', None), ('pg_degree', 'PG degree', None),
     ('percentage_cgpa', 'Percentage / CGPA', None), ('semester_cgpa', 'Semester-wise CGPA', None), ('scholarships', 'Scholarships', None), ('academic_awards', 'Academic awards / distinctions', None),
     ('subject_interests', 'Subject interests', None), ('specialization', 'Areas of specialization', None), ('dissertation', 'Dissertation / project', None)]),
 'research': C('Research & innovation', 'Research Engagement', 'Research title', 'Institution', 'Role', doc='Publication', extra=[
     ('rtype', 'Type', ['Research project', 'Research paper', 'Journal publication', 'Conference paper', 'Poster presentation', 'Preprint', 'Research internship', 'Software / data science project', 'Patent / copyright', 'Hackathon / innovation competition', 'Other']),
     ('supervisor', 'Supervisor', None), ('venue', 'Journal / conference', None), ('doi_url', 'DOI / URL', None)]),
 'internship': C('Internships', 'Professional Development', 'Internship title', 'Organization', 'Role', doc='Completion Letter', extra=[
     ('department', 'Department / unit', None), ('mode', 'Mode', ['On-site', 'Online', 'Hybrid']), ('location', 'Location', None), ('supervisor', 'Supervisor', None), ('skills_learned', 'Skills learned', None)]),
 'workshop': C('Workshops', 'Co-curricular Engagement', 'Workshop title', 'Organizer', 'Role', doc='Participation Proof', extra=[
     ('topic', 'Topic', None), ('mode', 'Mode', ['On-site', 'Online', 'Hybrid']), ('duration', 'Duration', None), ('skills_learned', 'Learning outcomes', None)]),
 'conference': C('Conferences & seminars', 'Co-curricular Engagement', 'Conference / seminar name', 'Organizer / institution', 'Participation type', PART, ['National', 'International'], 'single', doc='Conference Proof', extra=[
     ('paper_title', 'Paper / poster title', None), ('abstract', 'Abstract', None)]),
 'sports': C('Sports', 'Extracurricular Engagement', 'Sport', 'Institution', 'Position / role', None, LEVELS6, 'single', doc='Award Proof', extra=[
     ('team', 'Individual / team', ['Individual', 'Team']), ('tournament', 'Tournament', None), ('achievement', 'Achievement / medal', None)]),
 'cultural': C('Cultural activities', 'Extracurricular Engagement', 'Activity', 'Event / institution', 'Role', None, LEVELS6, 'single', doc='Participation Proof', extra=[('achievement', 'Achievement', None)]),
 'club': C('Clubs & organizations', 'Extracurricular Engagement', 'Club / organization', None, 'Role', ['Member', 'Volunteer', 'Coordinator', 'Secretary', 'Treasurer', 'Documentation Secretary', 'Media Secretary', 'President', 'Vice President', 'Other'], doc='Letter', extra=[
     ('academic_year', 'Academic year', None), ('responsibilities', 'Responsibilities', None), ('achievements', 'Achievements', None)]),
 'leadership': C('Leadership & engagement', 'Leadership', 'Position', 'Organization', None, doc='Letter', extra=[('academic_year', 'Academic year', None), ('responsibilities', 'Responsibilities', None), ('achievement', 'Achievement', None)]),
 'volunteering': C('Community service', 'Community Engagement', 'Activity', 'Organization', 'Role', doc='Participation Proof', extra=[
     ('kind', 'Kind', ['NSS', 'NCC', 'Volunteering', 'Community service', 'Awareness programme', 'Blood donation', 'Environmental activity', 'Rural outreach', 'Other']), ('duration', 'Duration', None)]),
 'certification': C('Certifications', 'Professional Development', 'Certificate name', 'Provider', None, dates='single', doc='Certificate', extra=[
     ('cert_type', 'Type', ['Course certificate', 'Professional certification', 'Participation certificate', 'Training certificate', 'Achievement certificate']), ('course_skill', 'Course / skill', None),
     ('expiry_date', 'Expiry date (YYYY-MM-DD)', None), ('credential_id', 'Credential ID', None), ('credential_url', 'Credential URL', None), ('duration', 'Duration', None)]),
 'skill': C('Skills', 'Skill Development', 'Skill', None, None, dates=None, doc='Certificate', extra=[
     ('skill_category', 'Category', ['Programming', 'Statistics', 'Mathematics', 'Data Analysis', 'Data Visualization', 'Research', 'Communication', 'Leadership', 'Software', 'Technical Tools', 'Domain Knowledge']),
     ('proficiency', 'Level', ['Beginner', 'Intermediate', 'Advanced'])]),
 'achievement': C('Achievements & awards', None, 'Award', 'Organization', None, None, LEVELS6, 'single', doc='Award Proof', extra=[
     ('acat', 'Category', ['Academic', 'Sports', 'Cultural', 'Research', 'Competition', 'Hackathon', 'Scholarship', 'Leadership', 'Innovation', 'Institutional recognition'])]),
}
DIMS = ['Research Engagement', 'Professional Development', 'Co-curricular Engagement', 'Extracurricular Engagement', 'Leadership', 'Skill Development', 'Community Engagement']
# Prototype engagement bands from VERIFIED record counts — not validated; thresholds are configurable here.
BANDS = [(4, 'Strong'), (2, 'Active'), (1, 'Emerging')]
