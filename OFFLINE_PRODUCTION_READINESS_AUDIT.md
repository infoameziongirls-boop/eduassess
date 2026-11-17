# EduAssess Offline Assessment and Quiz Readiness Audit

**Audit date:** 2026-11-17
**Environment:** Local application and isolated SQLite test databases; browser tests used `127.0.0.1`.
**Current verdict:** **Not production-ready for real student use.** The offline quiz/assessment baseline and the authentication hardening described in the phase update below have local isolated-test evidence; scheduled offline examinations, staff monitoring, production-domain validation, and physical-device coverage remain incomplete.

## Executive summary

The offline assessment and quiz workflows now retain drafts and queued submissions across refreshes, synchronize after connectivity returns, and prevent a repeated request with the same submission ID from creating another result. Offline assessment and quiz synchronization, student association, retry behavior, and relevant regressions were verified against isolated databases.

At the initial audit stage, release was blocked by identifier-only student login, plaintext browser storage, and unverified deployment conditions. Student credential hardening has since been implemented in source and tested against isolated SQLite databases, but its migration has not been applied to either local school database or production. Plaintext browser storage and unverified deployment/device conditions remain blockers. No school or production database records were changed during the phase update.

## Scope and evidence

The review covered `offline_routes.py`, the offline browser client and service worker, related models and migration, login/session configuration, offline form templates, dashboards, and existing tests.

Evidence gathered:

- The live SQLite database was backed up using SQLite's backup API before audit-driven changes. The backup passed `PRAGMA integrity_check` (`ok`) and contained 53 assessment rows at backup time. No live database writes or cleanup were performed.
- An isolated browser database was used for browser testing. It contains two QA students, two completed quiz attempts, one offline assessment result, and corresponding submission receipts. It is not the school's live database.
- The test suite completed with **12 passing tests**: offline route tests plus template, static-asset, and health-endpoint regressions. Python compilation, JavaScript syntax checks, and `git diff --check` also passed.
- Browser testing used localhost, not a deployed HTTPS domain.

## System findings

### Browser persistence, caching, and synchronization

- Assessment form drafts are stored in user-scoped `localStorage`; the offline submission queue is stored in IndexedDB. Quiz answers and queued attempts were restored after refresh and an offline reload.
- The service worker caches authenticated pages in per-user page caches and clears that user's page cache during logout. A second account, tested offline in the same browser context, saw its own dashboard rather than the previous account's page.
- Synchronization runs on page load, on the browser `online` event, and periodically while an eligible page remains open. Network errors, server errors, and expired sessions leave queued records available for retry. A 401 prompts the user to sign in again when manually syncing.
- The browser's `navigator.onLine` value remained true during one simulated network disconnection, but the failed request was still queued safely.
- Local drafts, queued data, and cached pages are not encrypted. Browser-profile separation and user-scoped cache keys reduce accidental cross-account exposure but do not protect data from local device access, DevTools, or same-origin script execution.

### Server-side validation, authorization, and duplicate protection

- Assessment sync requires an authenticated administrator or teacher. Teachers cannot override their assigned subject and are checked against the student's class/subject access. Quiz sync requires an authenticated student and resolves the student record from the authenticated account, rather than trusting a client-supplied student ID.
- The endpoints validate assessment category, subject, score bounds and finiteness, term, academic year, session, and text lengths. Quiz sync validates quiz availability, question IDs, answer keys and answer sizes, then grades on the server.
- `OfflineSubmission` receipts associate each submission ID with its authenticated user, submission kind, payload hash, and result. Repeating the same ID and payload returns duplicate success; reusing an ID with different data is rejected. Conflicting assessment results are not overwritten.
- A direct browser retry of the synchronized assessment returned HTTP 200 with `status: duplicate`. The isolated database still had one matching result and one receipt.
- The offline assessment endpoint is intentionally limited to staff; it does not let a student submit a score for another student.

### Dashboard and online-flow checks

- The administrator dashboard rendered the archive panel and class register. Student cache partitioning was checked with two accounts.
- An earlier audit browser run exposed a server error when the quiz list encountered an in-progress attempt. The list now provides a resume action, covered by a regression test.
- The report does **not** claim a full review of every student, teacher, and administrator report or result-publishing screen. Full online grading, publishing, and reporting workflows were not exhaustively exercised.

## Executed tests

### Assessment draft, offline submission, and retry

In the isolated browser test:

1. Entered a synthetic assessment for `OFFLINE-BROWSER-QA-2`: Mathematics, Form 1, ICA1, 23.5/50, term1, academic year 2024-2025.
2. Refreshed while connected and verified the student, score, and comments were restored. The displayed percentage was 47.0%.
3. Simulated disconnection, reloaded the cached form, and verified the draft was still present.
4. Submitted offline. IndexedDB contained one assessment payload with the exact student, subject, class, score, academic year, and unique submission ID; the local draft was cleared.
5. Reconnected and verified synchronization emptied the queue. The isolated database contained exactly one matching assessment for student ID 2 and one receipt for that submission ID.
6. Reposted the same payload. The endpoint returned `200`, `status: duplicate`; the database did not gain a second result.

The restore path was corrected to dispatch input/change events so dependent form UI recalculates after restoring values. The assessment percentage now resets to 0.0% when the entry fields are cleared after a save or queue operation.

### Quiz persistence, retry, and student association

- A one-question quiz was answered offline, refreshed/reloaded while offline, then synchronized after connectivity returned. The isolated database recorded one completed 1/1 attempt and one question result.
- A second student's offline quiz synchronized automatically after connectivity returned, without a manual page reload. The isolated database recorded a separate completed 1/1 attempt and one question result for that student.
- Route tests repeat quiz synchronization and verify only one attempt and one question result are recorded. They also supply a forged `student_id` and verify the attempt remains associated with the authenticated student's record.
- The test suite verifies unauthenticated assessment and quiz sync requests receive HTTP 401.

### Concurrency

Two concurrent assessment submissions for different students completed successfully against the isolated SQLite test database. This is not a substitute for testing concurrent transactions on the production PostgreSQL service; PostgreSQL concurrency has not been exercised.

## Identified issues and corrections

| Finding | Status |
|---|---|
| An in-progress quiz attempt could break the quiz-list page. | Fixed by rendering a resume action; regression test passes. |
| Assessment synchronization could fail when the configured cache backend was not the expected object shape. | Corrected to invalidate configured cache backends; endpoint and retry were verified in isolated testing. |
| Repeated syncs could create duplicate records or overwrite a conflicting result. | Added unique submission receipts, payload matching, idempotent retry handling, and conflict rejection. Isolated tests and a browser retry pass. |
| Invalid scores, subjects, terms, quiz questions, or answer keys could be accepted by offline sync. | Added server-side validation; invalid score and access-control tests pass. |
| Restored assessment values did not trigger dependent UI recalculation. | Fixed by dispatching input/change events during restoration; browser test displays 47.0% for 23.5/50. |
| Clearing an assessment after submission left a stale percentage displayed. | Fixed; browser test showed 0.0% after synchronization. |
| Authenticated cache content could be reused across accounts. | Added user-specific page cache partitioning, response cache scope headers, and logout cache clearing; checked with two accounts in the browser. |
| Student login accepts an identifier without a distinct secret and can provision/use a password derived from the student identifier. | Replaced in source by password login, administrator-issued one-use temporary passwords, forced password change, versioned session invalidation, and removal of identifier-derived account provisioning. Migration and production rollout remain pending; do not enable student access until the migration is applied and administrators are ready to issue credentials. |

## Outstanding production risks

1. **Credential migration and rollout are pending.** Source now requires student passwords and disables legacy student credentials in the new migration. Applying it will lock existing student accounts until an administrator issues a temporary password. Plan credential distribution and recovery before migration; the root and `instance` SQLite databases and production were not migrated.
2. **Offline data is plaintext on the device.** Shared or lost devices can expose drafts, queued answers, and cached student pages. Provide managed individual browser profiles/devices or implement a deliberate shared-device cleanup and retention policy before using this with real student data.
3. **Production domain and device coverage are unverified.** No Render-hosted test was performed, and physical Android, tablet, laptop, and supported-browser testing was unavailable. Service worker HTTPS behavior on the deployed domain is therefore not verified.
4. **PostgreSQL concurrency is unverified.** The concurrent test used SQLite. Validate row locking, transaction behavior, and uniqueness under the actual production PostgreSQL configuration.
5. **Session persistence needs a deployment decision.** Production configuration uses Redis when configured; otherwise it falls back to filesystem sessions. `render.yaml` sets `PERSISTENT_DIR=/var/data` but does not declare a persistent disk. Multi-instance deployment or an ephemeral filesystem can invalidate sessions. Configure Redis or a correctly mounted persistent disk, and test expiry/re-authentication.
6. **Dashboard/report coverage is partial.** Confirm synchronized scores appear correctly in each student, teacher, and administrator view, including result publishing, exports, analytics, and archived records.
7. **Migration/deployment sequencing needs explicit verification.** The offline-receipt and student-auth migrations have not been run against school or production databases. Back up each target database, apply migrations through a controlled release, verify schema and legacy-account state, and issue student credentials before enabling access.
8. **Service-worker cache lifetime and device storage remain operational risks.** Define cache invalidation, storage-quota handling, device-loss response, logout behavior when queued submissions exist, and a policy for retaining unsynchronized submissions.

## QA database records and cleanup recommendation

The live database inspection identified student rows with `OFFLINE-QA...` identifiers, including IDs 6, 7, and 8. ID 8 corresponds to the previously verified 37.5/50 offline assessment and one completed QA quiz attempt. IDs 6 and 7 are associated with older assessment rows (18 and 9) that predate those student rows. The provenance of those older associations is uncertain.

No records were deleted or modified. Keep the pre-audit backup. Before any cleanup:

1. Have the school data owner confirm whether each `OFFLINE-QA...` student, quiz, question, attempt, and linked assessment is test data.
2. Export the candidate rows and foreign-key relationships for review.
3. Preserve assessment history whose purpose or ownership is uncertain; do not cascade-delete rows 18 or 9 based only on the QA identifiers.
4. After written confirmation, remove only confirmed test data using a reviewed, backed-up cleanup script, then verify counts and foreign-key integrity.

## HTTPS deployment checklist

1. Keep the service behind Render's HTTPS endpoint and confirm the public/custom domain redirects HTTP to HTTPS. Service workers require HTTPS except on localhost.
2. Set a strong, unique `SECRET_KEY`; use the production PostgreSQL `DATABASE_URL`; configure Redis for sessions if using multiple instances, or provision and mount persistent storage at `/var/data` for the filesystem-session fallback.
3. Take a production database backup, then run the repository's migration step (for example, `flask --app app db upgrade`) as a controlled release/deploy operation. Verify `offline_submissions` and its unique key before enabling clients.
4. Deploy and verify `/sw.js` is served from the site root with an appropriate JavaScript content type and that the browser reports an active service worker with scope `/`.
5. Use a test account on the deployed domain to verify: login, first online load, offline form and quiz caching, refresh while offline, queued submission, reconnection/re-authentication, idempotent retry, queue clearing, logout cache clearing, and a second account on the same device.
6. Repeat on supported Android and desktop browsers, including low-storage and expired-session cases. Review logs and database rows after each test; use synthetic accounts only.
7. Keep student/offline access disabled until the student-auth migration is applied, temporary credentials are issued through a controlled process, and shared-device handling is approved.

## Final production-readiness assessment

**Current state: NOT READY for production student use.** The locally verified offline assessment/quiz queue and the new student credential controls are useful progress, but they do not establish that the unfinished examination workflow, production domain, or supported devices are ready. The credential migration and credential rollout remain pending; browser storage is plaintext; PostgreSQL concurrency, HTTPS deployment, and physical-device behavior are unverified.

## Phase update: PWA shell and student authentication

This update records the subsequent source changes and the exact local verification performed. Automated tests used fresh, isolated SQLite databases under the Copilot session files directory. The active root `assessment.db` had no Alembic revision marker, so applying the whole migration chain would have been unsafe. It was backed up with SQLite's backup API (`integrity_check=ok`), and the root and `instance\\assessment.db` were not migrated or otherwise changed.

To honor the restart request, the backed-up root database was copied to a disposable test database, the student-auth migration was applied to that copy, and port 5000 was restarted against the copy. A synthetic administrator and student were seeded only in that copy. The browser then verified staff login, admin-issued temporary password, forced first-login password change, and the student dashboard offline panel. `/health` returned `200`, the copied database passed `integrity_check`, and the service worker was active with scope `/`. The server remains running on `http://127.0.0.1:5000` against the disposable copy; it is not connected to the school database. The native app-install prompt was not verified.

### Implemented and locally verified

- Added optional PWA install metadata, icons, install prompt, and root service-worker registration. Manifest and local-asset tests passed. After restart, a browser verified the worker was activated, controlled the page, and had root scope on localhost. The install prompt itself was not verified.
- Added a student dashboard offline-status panel with connection state, cached quiz count, pending queue count, last-sync time, manual sync, and confirmed queue clearing. This is not a full authorized-examination management interface.
- Added password-required student login, bcrypt-backed temporary password issuance for administrators, forced change to a 12-character-minimum password, and atomic one-use consumption of temporary credentials. The credential page and change-password response use `Cache-Control: no-store`; the response hook and service worker preserve/obey that directive.
- Added a monotonic student `auth_version` check to invalidate old sessions after reset/credential rotation; stale student sessions route back to the student login page. Students are prevented from viewing another student's profile through the shared profile route.
- Removed broadcast-time auto-provisioning with student-number-derived passwords. Student accounts must now be activated by an administrator-issued credential.
- Added an additive migration that defaults new accounts safely and disables/forces a password change for legacy student accounts. The migration was executed against a synthetic SQLite users table in a focused test, not against a school database.

Focused evidence:

- `test_student_credential_auth.py`, `test_student_endpoints.py`, and `test_local_static_assets.py`: **24 passed**. Coverage includes legacy-account lockout, temporary-password issue and one-use behavior, forced change, stale-session invalidation, admin-only issuance, cross-student profile denial, migration data changes, student route regressions, and local PWA metadata/assets.
- `test_offline_routes.py`: **6 passed** on a separate isolated database, including idempotent retry, student association, and unauthorized API access.
- `test_admin_reset_login_flow.py`: **1 passed** on an isolated database.
- Python compilation and Node syntax checks for the modified application/static scripts passed.
- The restarted localhost browser run verified student login, the one-use temporary credential, forced password change, dashboard rendering, and an active service worker. No production HTTPS, Render, Android, tablet, or physical laptop/browser matrix test was executed.

## Requirement-by-requirement production status

| Requirement | Status | Evidence / remaining work |
|---|---|---|
| Preserve existing framework, models, UI and workflows | **PASSED (scope-limited)** | Changes are additive except for removing insecure automatic student-account provisioning. Full application regression remains incomplete. |
| Installable PWA shell and service-worker metadata | **PARTIAL** | Manifest, icons, install metadata and local assets are implemented/tested; after restart, localhost worker activation, control and root scope were verified. Installation prompt, updates on production, and HTTPS-domain behavior remain untested. |
| Downloadable authorized scheduled examinations | **FAILED / NOT IMPLEMENTED** | The repository has no separate Examination model, schedule, assignment, or offline authorization workflow. |
| Offline examination answering and recovery | **FAILED / NOT IMPLEMENTED** | No examination answer/draft package or exam submission endpoint exists. Existing offline assessment-entry drafts are not student examinations. |
| Offline quizzes | **PARTIAL** | Existing quiz page caching, answer restoration, server grading and idempotent synchronization have local evidence. Per-student assignment, schedule authorization, production timing integrity, and broader attempt-policy tests remain incomplete. |
| Retryable, idempotent synchronization | **PARTIAL** | Assessment/quiz retry and duplicate protection pass isolated tests; production database concurrency, interrupted-session recovery, and end-to-end network/device matrix remain untested. |
| Student offline management dashboard | **PARTIAL** | Connection, cached quiz count, pending count, sync, last-sync and clear controls exist. No examination inventory or download authorization is available. |
| Teacher/admin offline monitoring | **FAILED / NOT IMPLEMENTED** | No remote download/pending-client monitoring dashboard exists. Disconnected clients cannot be observed until they reconnect; server-confirmed receipts are available only after sync. |
| Student authentication and record isolation | **PARTIAL** | Source hardening and isolated tests pass; localhost browser verified admin-issued credentials and forced change on the disposable copy. The school-database migration/credential rollout is pending; full route/API authorization audit is incomplete. |
| Shared-device local-data protection | **FAILED / RISK REMAINS** | IndexedDB, localStorage and cached pages are plaintext. Logout cache clearing is best-effort; do not use on unmanaged shared devices with real student data without an approved policy. |
| HTTPS deployment and production configuration | **NOT TESTED** | No deployed domain test, TLS redirect check, production migration, Redis/persistent-session verification, or monitoring check was performed. |
| Chrome, Edge, Android, tablets and laptops | **NOT TESTED** | Only prior localhost browser testing and automated isolated tests are evidenced; no physical-device/browser matrix was executed. |
| Online grading, publishing, reports and dashboards | **PARTIAL** | Targeted student endpoints and password-reset regression passed; full online workflow/report regression was not run. |
| Backup, migration and QA data handling | **PARTIAL** | Local SQLite backups exist. A new migration-rehearsal copy was created from the local pre-auth backup; production backup/schema/revision state is not verified. QA-record cleanup remains subject to data-owner confirmation. |

### Deployment gate

Do not treat this branch as production-ready. Before rollout, take fresh backups of the actual deployment database, apply migrations in order, verify legacy student accounts are disabled, issue temporary credentials in person or through an approved secure channel, and confirm first-login password changes. Configure Redis or a verified persistent session store for the deployed topology. Then test on the deployed HTTPS origin with synthetic accounts and a representative device matrix. Do not use real high-stakes examinations offline: a student-controlled browser cannot prevent local answer inspection, clock manipulation, or client tampering.

### Release rehearsal — 2026-11-17

- Created `assessment-deploy-rehearsal-2026-11-17.db` as a separate copy of the local pre-auth backup. SQLite integrity check returned `ok`. This is a local school-database copy, **not** a Render production snapshot.
- The copy has no `alembic_version` table; its `users` table lacks the four new authentication columns. Running `flask --app app db upgrade` against the copy failed during app import, before Alembic ran: import-time initialization queries `users.must_change_password` before the migration can add it. This reproduces a deployment-order blocker.
- Neon production was inspected read-only: PostgreSQL 17.12; `alembic_version` exists but has zero rows; the legacy schema is partially migrated (including `api_keys`, `users.last_activity`, `students.student_id_code`, and only some legacy indexes). The offline receipt table and four student-auth columns were absent. This means the full migration chain must reconcile existing objects rather than assume a clean baseline.
- Created the full-data/schema Neon branch `pre-offline-release-backup-20261117` from production and retained it without auto-expiry. Created the schema-only branch `offline-release-stage-20261117`, expiring 2026-11-24; it contained zero users and students before rehearsal.
- The production HTTPS `/health` check returned `status=ok`. No production schema migration or application deployment was performed.

### Migration and deployment hardening — 2026-11-17

- Added `EDUASSESS_MIGRATION_MODE=1` support. The migration CLI still initializes Flask-SQLAlchemy and Flask-Migrate but skips `db.create_all()`, default-admin lookup, session-store initialization, and startup data queries until after Alembic completes.
- Made the legacy index/table migrations and the new offline/auth migrations tolerate already-existing objects, matching the inspected partial production schema.
- The isolated SQLite rehearsal database migrated through `8f2d4a6c1b90` successfully. A second `flask db upgrade` returned cleanly at head. Integrity check was `ok`; the expected auth columns, `api_keys`, `offline_submissions`, and indexes were present.
- On the confirmed schema-only Neon staging branch, the migration-equivalent PostgreSQL DDL completed in one transaction. Follow-up verification returned revision `8f2d4a6c1b90`, four auth columns, `offline_submissions`, all nine expected indexes, and zero users/students. **This used the Neon SQL editor, not the Flask-Alembic CLI**, so a direct Alembic execution against PostgreSQL remains unverified.
- Focused regression tests on a fresh isolated SQLite database: `16 passed, 6 skipped`. A separate initial collection attempt against the stale root `assessment.db` failed because that local database lacks the new auth columns; a read-only schema comparison to its preserved backup showed no changes, and its timestamp was unchanged.
- Render's live service settings were verified: direct Gunicorn start command, auto-deploy on commit, empty pre-deploy command, persistent disk mounted at `/opt/render/project/src/instance`, and `PERSISTENT_DIR` already set to that mount. Auto-deploy has now been switched **off** to prevent an unreviewed deployment. The pre-deploy command is configured as `EDUASSESS_MIGRATION_MODE=1 python -m flask --app app db upgrade`. Production `SESSION_TYPE` and secret values were not revealed. No `REDIS_URL` environment key was listed; application configuration therefore selects filesystem sessions, stored under the verified persistent disk path.
- `render.yaml` now declares the matching 1-GB disk, persistent path, and migration pre-deploy command. The live Render service is manually configured and does not automatically consume this file.
- **Still not deployed:** production remains at its original schema/revision state and original application commit. Production migration, credential issuance, post-deploy smoke tests, rollback rehearsal, and production offline/PWA routes remain untested. Auto-deploy must remain off until a deliberate manual deployment succeeds.
- The first manual deployment attempt stopped in pre-deploy before Alembic connected to PostgreSQL: the Render Python 3.14 environment selected the SQLAlchemy `psycopg` dialect, while `requirements.txt` supplies `psycopg2-binary` only. Render reported `ModuleNotFoundError: No module named 'psycopg'`; the existing production `/health` continued returning `status=ok`. No production schema migration or app replacement occurred.
- Corrected PostgreSQL URL normalization to explicitly select the already-declared `postgresql+psycopg2` driver and added regression tests. The change passed locally; the deployment retry and production schema check are pending.
