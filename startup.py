#!/usr/bin/env python3
"""
Application startup script for Render deployment.
Performs database initialization and health checks before starting the app.
"""

import os
import sys
import subprocess
from pathlib import Path
from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, os.path.dirname(__file__))

def ensure_required_schema():
    """Add columns required by the current model before importing the app."""
    database_url = os.environ.get('DATABASE_URL', 'sqlite:///assessment.db')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            inspector = inspect(connection)
            if not inspector.has_table('users'):
                return
            columns = {
                column['name']
                for column in inspector.get_columns('users')
            }
            if 'last_activity' not in columns:
                connection.execute(text(
                    'ALTER TABLE users ADD COLUMN last_activity TIMESTAMP'
                ))
                print('[OK] Added users.last_activity column')
    finally:
        engine.dispose()

def initialize_database():
    """Initialize the database if needed."""
    print("\n" + "="*60)
    print("INITIALIZING APPLICATION")
    print("="*60)
    
    try:
        from app import app, db, bcrypt
        from models import User, Setting, ensure_default_admin_user
        
        with app.app_context():
            print("\nChecking database connection...")
            
            # Create all tables
            db.create_all()
            print("[OK] Database tables initialized")
            
            # Ensure the default admin exists and is usable for login.
            admin = ensure_default_admin_user(app, bcrypt)
            admin_count = User.query.filter_by(role='admin').count()
            if admin is not None:
                print(f"[OK] Admin account ready: {admin.username}")
                print(f"[OK] Found {admin_count} admin user(s)")
            
            # Check if settings exist
            settings = Setting.query.first()
            if not settings:
                print("[OK] Creating default settings...")
                default_settings = Setting(
                    current_term='term1',
                    current_academic_year='2025-2026',
                    current_session='First Term'
                )
                db.session.add(default_settings)
                db.session.commit()
            else:
                print("[OK] Settings already configured")
            
            # Get data summary
            user_count = User.query.count()
            print(f"\n[DATA SUMMARY]")
            print(f"   Users: {user_count}")
            
            try:
                from models import Student, Assessment
                student_count = Student.query.count()
                assessment_count = Assessment.query.count()
                print(f"   Students: {student_count}")
                print(f"   Assessments: {assessment_count}")
            except:
                pass
        
        print("\n[OK] Database initialization completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n[FAIL] Database initialization failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def run_health_check():
    """Run the database health check."""
    print("\n" + "="*60)
    print("RUNNING HEALTH CHECK")
    print("="*60)
    
    try:
        from db_health_check import check_database_health
        check_database_health()
        return True
    except Exception as e:
        print(f"✗ Health check failed: {str(e)}")
        return False

def main():
    """Main startup routine."""
    print("\n" + "="*60)
    print("EDUASSESS - APPLICATION STARTUP")
    print("="*60)
    
    # Print environment info
    db_uri = os.environ.get('DATABASE_URL', 'Not set')
    print(f"\nEnvironment:")
    print(f"  Flask Env: {os.environ.get('FLASK_ENV', 'production')}")
    print(f"  Database: {'PostgreSQL (Render)' if 'postgres' in db_uri else 'SQLite (Local)'}")

    try:
        ensure_required_schema()
    except Exception as e:
        print(f"\n[FAIL] Required schema check failed: {str(e)}")
        return 1
    
    # Initialize database
    if not initialize_database():
        print("\n⚠️  Warning: Database initialization had issues, but continuing...")
    
    # Run health check
    if not run_health_check():
        print("\n⚠️  Warning: Health check failed, but continuing...")
    
    print("\n✓ Application startup complete!")
    print("="*60 + "\n")
    return 0

if __name__ == '__main__':
    sys.exit(main())
