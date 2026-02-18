#!/usr/bin/env python3
"""
Backup script for user data.
Exports all users to a JSON file for backup purposes.
Run this script periodically to backup user data.
"""

import os
import json
import sys
from datetime import datetime

# Add the current directory to the path so we can import app modules
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from models import User

def backup_users():
    """Export all users to a JSON file."""
    with app.app_context():
        users = User.query.all()
        user_data = []

        for user in users:
            user_dict = {
                'id': user.id,
                'username': user.username,
                'role': user.role,
                'subject': user.subject,
                'classes': user.get_classes_list() if hasattr(user, 'get_classes_list') else [],
                'created_at': user.created_at.isoformat() if user.created_at else None
            }
            user_data.append(user_dict)

        # Create backups directory if it doesn't exist
        backup_dir = 'backups'
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'{backup_dir}/users_backup_{timestamp}.json'

        with open(filename, 'w') as f:
            json.dump(user_data, f, indent=2)

        print(f"Backup completed: {len(user_data)} users exported to {filename}")
        return filename

if __name__ == '__main__':
    backup_users()