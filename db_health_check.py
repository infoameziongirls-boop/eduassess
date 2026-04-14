#!/usr/bin/env python3
"""
Database health check script - Linux/Render compatible version.
Checks database configuration and file existence.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

def check_database_health():
    """Check the health of the database configuration."""
    from app import app
    
    with app.app_context():
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', 'Not configured')
        print("\n" + "="*60)
        print("DATABASE HEALTH CHECK")
        print("="*60)
        print(f"Database URI: {db_uri}\n")
        
        # Check if using SQLite
        if 'sqlite' in db_uri.lower():
            db_path = db_uri.replace('sqlite:///', '')
            db_exists = os.path.exists(db_path)
            print(f"Database Type: SQLite (Local)")
            print(f"Database Path: {db_path}")
            print(f"Database Exists: {'[YES]' if db_exists else '[NO] - New database will be created'}")
            
            if db_exists:
                db_size = os.path.getsize(db_path)
                print(f"Database Size: {db_size:,} bytes ({db_size / (1024*1024):.2f} MB)")
        
        # Check if using PostgreSQL (Render)
        elif 'postgres' in db_uri.lower():
            print(f"Database Type: PostgreSQL (Cloud - Render)")
            print("[OK] Using persistent cloud database")
            print("[OK] Data will persist across deployments")
        
        # Try to connect and check tables
        try:
            from db import db
            from models import User, Student, Assessment
            
            with app.app_context():
                user_count = User.query.count()
                student_count = Student.query.count()
                assessment_count = Assessment.query.count()
                
                print(f"\nData Summary:")
                print(f"  Users: {user_count}")
                print(f"  Students: {student_count}")
                print(f"  Assessments: {assessment_count}")
                print(f"\n[OK] Database connection successful!")
                
        except Exception as e:
            print(f"\n[FAIL] Database connection failed: {str(e)}")
            print("This usually means the database hasn't been initialized yet.")
            print("The app will create the database on first run.")
        
        print("="*60 + "\n")

if __name__ == '__main__':
    check_database_health()
