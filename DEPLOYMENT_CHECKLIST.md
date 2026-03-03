# Quick Deployment Checklist & Commands

## Pre-Deployment Checklist ✓

Before you push to Render:

- [ ] All changes are committed locally
- [ ] You've reviewed all modified files
- [ ] `render.yaml` has correct database and disk configuration
- [ ] `build.sh` no longer runs database commands
- [ ] `config.py` uses `DATABASE_URL` environment variable
- [ ] `app.py` paths point to persistent disk
- [ ] `models.py` has retry logic for database
- [ ] `requirements.txt` has `psycopg2-binary`

---

## Deployment Commands

### Step 1: Commit Changes
```bash
cd c:\Users\HP\Documents\school_assess_app_EXPERIMENTAL_ver_1

git status  # See what files changed

git add render.yaml config.py app.py models.py build.sh

git commit -m "Configure PostgreSQL and persistent disk for data persistence"

git log --oneline -3  # Verify commit
```

### Step 2: Push to Remote
```bash
git push origin main
```

### Step 3: Wait for Render Deployment
- Go to: https://dashboard.render.com
- Click: **eduassess** (web service)
- Watch: **Events** tab during deployment

### Step 4: Monitor Build & Startup
Expected timeline:
- Build: 2-3 minutes (installs dependencies)
- Database setup: 5-10 minutes
- App ready: 10-15 minutes total

Watch for these messages in logs:
```
✓ Database tables created successfully
✓ Default settings created
Created default admin account
```

---

## Post-Deployment Testing

### Test 1: Database Persistence
```
1. Open your app: https://your-app.render.com
2. Log in: admin / Admin@123
3. Create a student
4. Add an assessment
5. Refresh browser (Ctrl+R or Cmd+R)
   ✓ Data should still be there
```

### Test 2: Restart Persistence
```
1. Go to Render Dashboard → eduassess
2. Click: "Manual" (deploy) button to restart
3. Wait for restart (1-2 minutes)
4. Open app again
   ✓ Data should still be there
```

### Test 3: File Upload Persistence
```
1. Go to: Question Bank → Import Questions
2. Upload an Excel file with questions
3. Refresh page
   ✓ Questions should be saved
4. Restart service (see Test 2)
   ✓ Questions should still be there
```

---

## Troubleshooting Quick Commands

### Check Render Logs
```bash
# In Render Dashboard, click on "Logs" tab for the web service
# Look for errors related to:
# - DATABASE_URL not found
# - Connection to PostgreSQL failed
# - Permission denied on persistent disk
```

### Verify Database Connection
```bash
# If you have psql installed locally:
psql postgresql://user:pass@your-render-db.com/dbname
SELECT * FROM users;  # Should see your data
```

### Reset Database (CAUTION: DELETES ALL DATA)
```
1. Go to Render Dashboard
2. Find: eduassess-db (PostgreSQL service)
3. Click: Settings → Delete Database
4. Click: Re-create database
5. Redeploy web service
# All data will be gone - only do this if needed!
```

---

## Performance Monitoring

### Check Database Size
```sql
SELECT pg_size_pretty(pg_database_size(current_database()));
```

### Check Persistent Disk Usage
```bash
# In Render logs, you might see disk space warnings
# Visit Render Dashboard → eduassess → Disks
# Shows: Used / Total space
```

### Monitor Query Performance
If app is slow:
1. Check Render dashboard for CPU/Memory usage
2. Consider upgrading from "Standard" to "Pro" plan
3. Add database indexes to frequently queried columns

---

## Important Configuration Values

Copy these to a safe place:

```yaml
# render.yaml settings:
DATABASE_URL: postgresql://eduassess_user:PASSWORD@your-db.render.com/eduassess
PERSISTENT_DIR: /app/instance

# Default credentials (CHANGE IMMEDIATELY):
Username: admin
Password: Admin@123

# Persistent disk:
Mount point: /app/instance
Size: 1 GB
Locations:
  - /app/instance/uploads
  - /app/instance/templates_excel
  - /app/instance/flask_sessions
```

---

## Common Issues & Quick Fixes

### Issue 1: "ModuleNotFoundError: No module named psycopg2"
**Fix**: Add to requirements.txt:
```
psycopg2-binary==2.9.9
```
Then redeploy.

### Issue 2: "DATABASE_URL environment variable not found"
**Fix**: In render.yaml, check:
```yaml
- key: DATABASE_URL
  fromDatabase:
    name: eduassess-db
    property: connectionString
```
Ensure `eduassess-db` service exists.

### Issue 3: "Permission denied" on persistent disk
**Fix**: Files created during build phase can't be written to. Ensure all file operations use `persistent_dir` path.

### Issue 4: Database still resetting
**Steps**:
1. Verify `DATABASE_URL` is being used (not SQLite)
2. Check logs: `Initializing database at: ...`
3. Should show PostgreSQL path, not SQLite path
4. Delete `.db` files locally if they exist

### Issue 5: Disk space full
**Fix**: 
1. Check what's in `/app/instance`
2. Delete old backups if needed
3. Upgrade disk size in render.yaml:
```yaml
disk:
  sizeGB: 5  # Increase from 1 to 5 GB
```

---

## Deployment Success Checklist

After deployment, verify:

- [ ] App loads without errors
- [ ] Can log in with admin/Admin@123
- [ ] Can create students
- [ ] Can add assessments
- [ ] Data persists after page refresh
- [ ] Data persists after service restart
- [ ] File uploads work
- [ ] Excel imports work
- [ ] No 502 or 500 errors in logs

---

## Rollback Plan (if needed)

If something goes wrong:

```bash
# Revert to previous commit
git revert HEAD
git push origin main

# Or go back to specific commit
git log --oneline  # Find the commit to revert to
git reset --hard <commit-hash>
git push origin main --force
```

Render will automatically redeploy with the previous version.

---

## Next Deployments

After this initial setup, future deployments are simple:

```bash
# Make code changes
git add .
git commit -m "Your changes"
git push origin main

# Render auto-deploys
# Data and files preserved automatically
```

No more manual database setup needed!

---

## Keep This Handy

Save these commands:
- **View logs**: Render Dashboard → Logs
- **Restart app**: Render Dashboard → Manual Deploy
- **Check disk**: Render Dashboard → Disks
- **Emergency reset**: Delete service and recreate

---

## Success! 🎉

Your app now:
✅ Persists data across all restarts
✅ Backs up PostgreSQL automatically  
✅ Stores files safely on persistent disk
✅ Handles service restarts gracefully
✅ No more data loss!

**Happy deploying!**
