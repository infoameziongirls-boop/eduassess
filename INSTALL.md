# EduAssess patch: Learning-Area register + Offline mode

All changes are additive. Nothing existing is deleted.

## 1. Copy files
| File | Destination |
|---|---|
| offline_routes.py | project root (next to app.py) |
| static/sw.js | static/sw.js  (WhiteNoise serves it at /sw.js) |
| static/js/offline.js | static/js/offline.js |
| dashboard_roster.html | templates/ |

## 2. app.py - add after `csrf.exempt(api_bp)`
```python
from offline_routes import offline_bp
app.register_blueprint(offline_bp)
csrf.exempt(offline_bp)   # JSON-only + login required; avoids stale-CSRF failures on queued sync
```

## 3. base.html - just before `{% block extra_js %}{% endblock %}`
```html
{% if current_user.is_authenticated %}
<script src="{{ url_for('static', filename='js/offline.js') }}" data-user="{{ current_user.id }}" defer></script>
{% endif %}
```

## 4. dashboard.html
Right after `{% include 'dashboard_archive_panel.html' %}` add:
```html
{% include 'dashboard_roster.html' %}
```
Then wrap the old "STUDENTS BY FORM" card in `{% if false %} ... {% endif %}` (reversible).

## 5. Mark the two forms for offline
assessment_form.html:  `<form method="POST">`  ->
`<form method="POST" {% if not assessment %}data-offline="assessment"{% endif %}>`

take_quiz.html:  `<form method="POST" id="quizForm">`  ->
`<form method="POST" id="quizForm" data-offline="quiz" data-quiz-id="{{ quiz.id }}">`

## 6. Staged Render deployment

The application must be served over HTTPS for service workers to work. Before a production release:

1. Rehearse schema changes on a separate Neon staging branch and confirm the expected Alembic revision and schema.
2. Create and verify a retained production database backup branch. Do not use the schema-only staging branch as a backup.
3. Keep the Render persistent disk mounted at `/opt/render/project/src/instance` and set `PERSISTENT_DIR` to that exact path. Production filesystem sessions and uploads use this directory.
4. Configure the Render pre-deploy command:

   ```sh
   EDUASSESS_MIGRATION_MODE=1 python -m flask --app app db upgrade
   ```

   This prevents application startup queries from running before Alembic applies the schema.
5. Disable automatic deploys while preparing a release. Manually deploy the reviewed commit, then check `/health`, login, dashboards, `/sw.js`, and an authorized offline sync using synthetic accounts. Review Render logs and the database revision before enabling routine auto-deploys.

Do not run the migration against a production database until its backup and the required student credential rollout are ready. The authentication migration disables legacy student credentials and requires administrators to issue temporary passwords.

## 7. Rollback

If the new application fails its smoke tests, manually redeploy the last known-good application commit. The schema changes are additive; do not blindly run `flask db downgrade`. Restore the retained Neon backup only if database recovery is required and the owner has reviewed the risk of losing writes made after that backup. Keep automatic deploys off until the failure is resolved.
