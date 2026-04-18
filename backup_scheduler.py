#!/usr/bin/env python3
"""
Scheduled backup job for production deployments.
Can be run as a separate service or cron job on Render.
Backs up all data at regular intervals.
"""

import os
import sys
import time
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

# Try to use APScheduler if available, otherwise use simple loop
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    print("Note: APScheduler not installed. Using simple interval-based backup.")

from app import app
from backup_all_data import backup_all_data
from db_health_check import check_database_health

def run_backup_job():
    """Execute a backup job."""
    try:
        print(f"\n[{datetime.now().isoformat()}] Running scheduled backup...")
        backup_all_data()
        print(f"[{datetime.now().isoformat()}] Backup job completed successfully!")
        return True
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] Backup job failed: {str(e)}")
        return False

def run_backup_job_sync():
    """Synchronous version of backup job for Celery."""
    with app.app_context():
        return run_backup_job()

def run_health_check_job():
    """Execute a health check job."""
    try:
        print(f"\n[{datetime.now().isoformat()}] Running health check...")
        check_database_health()
        print(f"[{datetime.now().isoformat()}] Health check completed!")
        return True
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] Health check failed: {str(e)}")
        return False

def start_scheduler_apscheduler():
    """Start backup scheduler using APScheduler."""
    print("\n" + "="*60)
    print("STARTING SCHEDULED BACKUP SERVICE (APScheduler)")
    print("="*60)
    
    scheduler = BackgroundScheduler()
    
    # Schedule backup every 6 hours
    scheduler.add_job(
        run_backup_job,
        'interval',
        hours=6,
        id='backup_job',
        name='Full Data Backup Every 6 Hours'
    )
    
    # Schedule health check every 12 hours
    scheduler.add_job(
        run_health_check_job,
        'interval',
        hours=12,
        id='health_check_job',
        name='Database Health Check Every 12 Hours'
    )
    
    scheduler.start()
    
    print("\n[OK] Scheduler started with jobs:")
    print("  - Full backup every 6 hours")
    print("  - Health check every 12 hours")
    print("="*60 + "\n")
    
    # Keep scheduler running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down scheduler...")
        scheduler.shutdown()

def start_scheduler_simple():
    """Start backup scheduler using simple interval loop."""
    print("\n" + "="*60)
    print("STARTING SCHEDULED BACKUP SERVICE (Simple Loop)")
    print("="*60)
    
    backup_interval_hours = int(os.environ.get('BACKUP_INTERVAL_HOURS', '6'))
    health_check_interval_hours = int(os.environ.get('HEALTH_CHECK_INTERVAL_HOURS', '12'))
    
    last_backup = datetime.now()
    last_health_check = datetime.now()
    
    print(f"\n[OK] Scheduler configured with:")
    print(f"  - Backup interval: {backup_interval_hours} hours")
    print(f"  - Health check interval: {health_check_interval_hours} hours")
    print("="*60 + "\n")
    
    try:
        while True:
            now = datetime.now()
            
            # Check if backup is due
            if (now - last_backup).total_seconds() >= (backup_interval_hours * 3600):
                run_backup_job()
                last_backup = now
            
            # Check if health check is due
            if (now - last_health_check).total_seconds() >= (health_check_interval_hours * 3600):
                run_health_check_job()
                last_health_check = now
            
            # Sleep for 1 minute before checking again
            time.sleep(60)
    
    except KeyboardInterrupt:
        print("\nScheduler stopped by user")
    except Exception as e:
        print(f"\nScheduler error: {str(e)}")

def main():
    """Start the backup scheduler."""
    print("\n" + "="*60)
    print("EDUASSESS - BACKUP SCHEDULER SERVICE")
    print("="*60)
    print(f"Started at: {datetime.now().isoformat()}")
    
    # Run initial backup
    print("\nRunning initial backup...")
    run_backup_job()
    
    # Start continuous scheduler
    print("\nStarting continuous backup service...")
    
    if HAS_APSCHEDULER:
        start_scheduler_apscheduler()
    else:
        start_scheduler_simple()

if __name__ == '__main__':
    main()
