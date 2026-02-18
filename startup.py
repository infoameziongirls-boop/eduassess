#!/usr/bin/env python3
"""
Application startup script for Render deployment.
Performs database initialization and health checks before starting the app.
"""

import os
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

def initialize_database():
    """Initialize the database if needed."""
    print("\n" + "="*60)
    print("INITIALIZING APPLICATION")
    print("="*60)
    
    try:
        from app import app, db, bcrypt
        from models import User, Setting
        
        with app.app_context():
            print("\nChecking database connection...")
            
            # Create all tables
            db.create_all()
            print("✓ Database tables initialized")
            
            # Check if default admin exists
            admin_count = User.query.filter_by(role='admin').count()
            if admin_count == 0:
                print("✓ Creating default admin user...")
                
                default_username = os.environ.get('DEFAULT_ADMIN_USERNAME', 'admin')
                default_password = os.environ.get('DEFAULT_ADMIN_PASSWORD', 'Admin@123')
                
                hashed = bcrypt.generate_password_hash(default_password).decode('utf-8')
                admin = User(
                    username=default_username,
                    password_hash=hashed,
                    role='admin'
                )
                db.session.add(admin)
                db.session.commit()
                
                print(f"  Username: {default_username}")
                print(f"  ** CHANGE THIS PASSWORD IMMEDIATELY **")
            else:
                print(f"✓ Found {admin_count} admin user(s)")
            
            # Check if settings exist
            settings = Setting.query.first()
            if not settings:
                print("✓ Creating default settings...")
                default_settings = Setting(
                    current_term='term1',
                    current_academic_year='2025-2026',
                    current_session='First Term'
                )
                db.session.add(default_settings)
                db.session.commit()
            else:
                print("✓ Settings already configured")
            
            # Get data summary
            user_count = User.query.count()
            print(f"\n📊 Data Summary:")
            print(f"   Users: {user_count}")
            
            try:
                from models import Student, Assessment
                student_count = Student.query.count()
                assessment_count = Assessment.query.count()
                print(f"   Students: {student_count}")
                print(f"   Assessments: {assessment_count}")
            except:
                pass
        
        print("\n✓ Database initialization completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n✗ Database initialization failed: {str(e)}")
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
    
    # Initialize database
    if not initialize_database():
        print("\n⚠️  Warning: Database initialization had issues, but continuing...")
    
    # Run health check
    if not run_health_check():
        print("\n⚠️  Warning: Health check failed, but continuing...")
    
    print("\n✓ Application startup complete!")
    print("="*60 + "\n")

if __name__ == '__main__':
    main()
