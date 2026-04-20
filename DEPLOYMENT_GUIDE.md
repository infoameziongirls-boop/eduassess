# Deployment Guide: EduAssess to Render + Neon

This guide walks you through deploying your school assessment app to **Render** (web hosting) with **Neon PostgreSQL** (database).

---

## Prerequisites

Before you begin, ensure you have:
- ✅ A GitHub account with your code pushed
- ✅ A Neon account (free tier available at [neon.tech](https://neon.tech))
- ✅ A Render account (free tier available at [render.com](https://render.com))

---

## Step 1: Create a Neon PostgreSQL Database

1. **Go to [neon.tech](https://neon.tech)** and sign up/log in
2. **Create a new project** (e.g., "eduassess")
3. **Copy your connection string**:
   - It looks like: `postgresql://username:password@host/dbname?sslmode=require`
   - Click "Copy connection string" from your Neon dashboard
4. **Save this string** — you'll need it in Step 3

---

## Step 2: Push Your Code to GitHub

Make sure your project is on GitHub:

```bash
git add .
git commit -m "Prepare for Render deployment"
git push origin main
```

**Important:** Your `.gitignore` now protects:
- `.env` files (secrets won't leak)
- `*.db` files (database files)
- `backups/` folder
- Flask sessions

---

## Step 3: Connect Render to GitHub & Deploy

1. **Go to [render.com](https://render.com)** and sign in
2. **Click "New +"** → **"Web Service"**
3. **Connect your GitHub repository**:
   - Select your repo (e.g., `username/school_assess_app`)
   - Click "Connect"
4. **Configure the service**:
   - **Name**: `eduassess-app`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn wsgi:app --workers 2 --timeout 120 --bind 0.0.0.0:$PORT`
   - **Plan**: Choose your plan (Free available)

   *(Most of these are already in `render.yaml` — Render will auto-detect them)*

5. **Click "Create Web Service"**

---

## Step 4: Set Environment Variables in Render

After your service is created:

1. **Go to your service** on Render
2. **Click "Environment"** in the left sidebar
3. **Add the following environment variables**:

| Key | Value | Notes |
|-----|-------|-------|
| `FLASK_ENV` | `production` | Already set in render.yaml |
| `SECRET_KEY` | *(auto-generated)* | Render generates this automatically |
| `DATABASE_URL` | `postgresql://user:pass@host/db?sslmode=require` | **Paste your Neon connection string here** |
| `DEFAULT_ADMIN_USERNAME` | `admin` | Change after first login! |
| `DEFAULT_ADMIN_PASSWORD` | *(strong password)* | **Set a secure password** |

**Critical:** 
- ⚠️ **Never put real secrets in `render.yaml`** — always set them in the Render dashboard
- Your `wsgi.py` will automatically initialize the database and create the admin account

---

## Step 5: Deploy & Test

1. **Render auto-deploys** when you push to GitHub
2. **Monitor the deployment**:
   - Go to your service's "Logs" tab
   - Watch for: `"Deployed successfully"` ✅
3. **Visit your app**: Click the service URL (e.g., `https://eduassess-app.onrender.com`)

---

## Step 6: First Login

1. **Visit your app URL**
2. **Log in with**:
   - Username: `admin`
   - Password: *(the one you set in Step 4)*
3. **Change password immediately** (Security best practice)

---

## Key Changes Made for This Deployment

### ✅ `config.py` — 3 Critical Fixes

```python
# Fix 1: Converts postgres:// → postgresql:// (SQLAlchemy requirement)
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

# Fix 2: Adds SSL requirement for Neon
if DATABASE_URL and 'sslmode' not in DATABASE_URL:
    DATABASE_URL += '?sslmode=require'

# Fix 3: Connection pooling for Neon's free tier
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_pre_ping': True,       # Verify connection before use
    'pool_recycle': 300,         # Refresh connections every 5 min
    'pool_timeout': 30,          # Max 30 sec wait for connection
}
```

### ✅ `render.yaml` — Deployment Configuration

Tells Render:
- How to build your app (`pip install -r requirements.txt`)
- How to start it with 2 workers (`gunicorn wsgi:app --workers 2`)
- Health check endpoint (`/health`)
- Environment variables

### ✅ `wsgi.py` — Automatic Initialization

Runs `startup.py` on every deploy, ensuring:
- Database tables are created
- Admin account exists
- Settings are initialized

### ✅ `.gitignore` — Secrets Protection

Prevents accidental commits of:
- `.env` files
- Database files (`*.db`, `*.sqlite`)
- Backup files
- Flask sessions

---

## Troubleshooting

### "Connection refused" / "SSL error"

**Solution**: 
- Verify `DATABASE_URL` is correct in Render environment variables
- Check `sslmode=require` is in your connection string
- Restart the service: Render → "Manual Deploy"

### "Tables don't exist"

**Solution**: 
- `wsgi.py` should have auto-created them
- Check Render logs for `startup.py` output
- If not created, manually run in a terminal:
  ```bash
  python startup.py
  ```

### "Admin login fails"

**Solution**:
- Verify `DEFAULT_ADMIN_PASSWORD` is set in Render dashboard
- Check Render logs for password confirmation
- Reset in Render environment variables + restart

### Free tier timeout?

**Solution**: 
- Neon free tier may have connection limits
- Upgrade to paid tier if you hit limits
- Consider adding caching layer (Redis)

---

## Next Steps

1. ✅ **Verify deployment works** (log in, create assessments)
2. ✅ **Set up automated backups** (see `backup_scheduler.py`)
3. ✅ **Monitor performance** (Render dashboard → "Metrics")
4. ✅ **Update teacher docs** with your app URL

---

## Support

For issues:
- **Render**: https://render.com/docs
- **Neon**: https://neon.tech/docs
- **SQLAlchemy**: https://docs.sqlalchemy.org/

---

**Deployment date**: April 2026
**App**: EduAssess School Assessment System
**Version**: 1.0 (Render + Neon)
