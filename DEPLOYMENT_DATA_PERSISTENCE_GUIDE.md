# Data Persistence Setup Guide - Render Deployment

## Overview
This guide explains how your Flask assessment app now prevents data loss on Render by using:
- **PostgreSQL Database** for all application data (users, students, assessments, etc.)
- **Persistent Disk** for file uploads, Excel templates, and session data

---

## Changes Made

### 1. **render.yaml** ✓
Added environment variables to connect to PostgreSQL:
```yaml
- key: DATABASE_URL
  fromDatabase:
    name: eduassess-db
    property: connectionString
- key: PERSISTENT_DIR
  value: /app/instance
- key: DEFAULT_ADMIN_PASSWORD
  value: Admin@123
```

**What this does:**
- `DATABASE_URL`: Render automatically injects the PostgreSQL connection string
- `PERSISTENT_DIR`: Points to the mounted disk for file storage
- `DEFAULT_ADMIN_PASSWORD`: Allows automated admin account creation

### 2. **config.py** ✓
Updated to use PostgreSQL in production:
```python
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    # Fix postgres:// to postgresql:// for SQLAlchemy 1.4+
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

SQLALCHEMY_DATABASE_URI = DATABASE_URL or 'sqlite:///assessment.db'
```

**What this does:**
- Uses PostgreSQL on Render (via DATABASE_URL)
- Falls back to SQLite locally for development

### 3. **app.py** ✓
Updated folder paths to use persistent disk:
```python
persistent_dir = os.environ.get('PERSISTENT_DIR', os.path.join(os.path.dirname(__file__), 'instance'))

app.config['UPLOAD_FOLDER'] = os.path.join(persistent_dir, 'uploads')
app.config['TEMPLATE_FOLDER'] = os.path.join(persistent_dir, 'templates_excel')
app.config['SESSION_FILE_DIR'] = os.path.join(persistent_dir, 'flask_sessions')
```

**What this does:**
- All file uploads stored on persistent disk (survives restarts)
- Excel templates stored on persistent disk
- Session data stored on persistent disk

### 4. **models.py** ✓
Added retry logic for database connection:
```python
max_retries = 5
for attempt in range(max_retries):
    try:
        db.create_all()
        break
    except OperationalError as e:
        if attempt == max_retries - 1:
            raise
        print(f"⚠ Database not ready, retrying in 2 seconds...")
        time.sleep(2)
```

**What this does:**
- Waits up to 10 seconds for PostgreSQL to be ready
- Prevents crash if database is still starting
- Creates tables safely on first deployment

### 5. **build.sh** ✓
Simplified to only install dependencies:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**What this does:**
- Build phase now only handles dependencies (no database access needed)
- Database initialization happens automatically when Gunicorn starts
- Faster, more reliable deployments

### 6. **requirements.txt** ✓
Already includes PostgreSQL support:
```
psycopg2-binary==2.9.7
```

---

## Data Persistence Architecture

### Before (Causing Data Loss)
```
Flask App → SQLite Database (local disk)
            ↓
       RESTARTED/REFRESHED
            ↓
       Database reset to empty
       Data lost!
```

### After (No Data Loss)
```
Flask App → PostgreSQL (managed by Render)
            ↓ (persists across restarts)
       
       Persistent Disk (/app/instance)
            ↓ (survives restarts)
       - /uploads (student work, Excel files)
       - /templates_excel (Excel templates)
       - /flask_sessions (user sessions)
```

---

## Deployment Steps

### Step 1: Update Your Git Repository
```bash
git add render.yaml config.py app.py models.py build.sh
git commit -m "Configure PostgreSQL and persistent disk for data persistence"
git push origin main
```

### Step 2: Wait for Render Deployment
Render will automatically deploy when you push:
1. **Build Phase**: Installs Python dependencies
2. **PostgreSQL Service**: Starts (or connects to existing)
3. **Web Service**: Starts with disk mounted at /app/instance
4. **Database Initialization**: 
   - Creates all tables
   - Sets up default admin account
   - Creates necessary folders

### Step 3: Verify Deployment
1. Go to your Render dashboard
2. Click on **eduassess** (web service)
3. Check the **Logs** tab:
   - Look for `✓ Database tables created successfully`
   - Look for `✓ Default settings created`
   - Should see Flask app starting on port

### Step 4: Test Your App
1. Log in with default admin credentials:
   - **Username**: `admin`
   - **Password**: `Admin@123` (from render.yaml)
2. Create a student and add assessments
3. **Refresh the browser** - data should remain!
4. Check the Render dashboard - restart the service manually
5. **Data should still be there!**

---

## Troubleshooting

### Issue: "Database not ready" errors
**Solution**: This is normal during first deployment. The retry logic will handle it. If it persists:
- Check Render dashboard for PostgreSQL service status
- Ensure `eduassess-db` is listed and running

### Issue: File uploads disappear
**Ensure your persistent disk is properly mounted:**

In render.yaml, check:
```yaml
disk:
  name: data
  mountPath: /app/instance
  sizeGB: 1
```

### Issue: Default admin account not created
**Ensure DEFAULT_ADMIN_PASSWORD is set in render.yaml:**
```yaml
- key: DEFAULT_ADMIN_PASSWORD
  value: Admin@123
```

### Issue: Still losing data
1. Check Render logs for database connection errors
2. Verify PostgreSQL service is running and not restarting
3. Ensure app.py is using `persistent_dir` for all file paths
4. Check that persistent disk is mounted (1 GB)

---

## Important Security Notes

### Before Production:
1. **Change the default admin password immediately**
   - Log in with admin/Admin@123
   - Go to User Settings
   - Change password

2. **Set SECRET_KEY in Render:**
   - Add to render.yaml:
   ```yaml
   - key: SECRET_KEY
     value: <your-random-secret-key>
   ```
   - Generate with: `python -c "import secrets; print(secrets.token_hex(32))"`

3. **Database Backups:**
   - Render PostgreSQL automatically backs up
   - You can also enable automated backups in Render dashboard

---

## What Persists Now

### ✓ Always Persists
- Student data
- Assessment scores
- User accounts
- Quiz attempts
- Activity logs
- File uploads
- Excel templates
- Session data
- Settings

### ✓ Survives Restarts
- Manual service restart in Render
- Automatic daily restart (if enabled)
- App crashes and redeployments

### ⚠ Only Lost On
- Manual database deletion in Render
- Disk deletion in Render
- Account deletion (if you delete the resource)

---

## Performance Notes

### Database Queries
PostgreSQL is managed by Render and optimized for production use. No local tuning needed.

### File Storage
Persistent disk is 1 GB by default. Upgrade in render.yaml if needed:
```yaml
disk:
  sizeGB: 5  # Increase to 5 GB for more file storage
```

### Expected Performance
- First deployment: 5-10 minutes (database setup + app start)
- Subsequent restarts: 30-60 seconds
- API responses: Same as before (now with persistent data!)

---

## Next Steps

1. **Push changes to Git and monitor deployment**
2. **Test thoroughly - add data and restart service**
3. **Change default admin password**
4. **Set up your own SECRET_KEY**
5. **Monitor logs for any errors**
6. **Plan regular backups if needed**

---

## Summary

Your app now uses:
- ✓ PostgreSQL for all data (managed by Render)
- ✓ Persistent Disk for files and sessions
- ✓ Automatic database initialization
- ✓ Retry logic for reliability
- ✓ No data loss on restarts

**You can now deploy with confidence that your data is safe!**

For questions or issues, refer to:
- Render documentation: https://render.com/docs
- Flask-SQLAlchemy docs: https://flask-sqlalchemy.palletsprojects.com/
- PostgreSQL native tutorials for advanced usage
