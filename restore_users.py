#!/usr/bin/env python3
"""
Restore users from a JSON backup produced by `backup_users.py` or `backup_all_data.py`.

Behavior:
- If a user exists, update fields but DO NOT overwrite `password_hash` when the
  backup record does not contain a `password_hash` value.
- If a user does not exist, create them. If the backup has no `password_hash`,
  a temporary password is generated and shown on stdout so an admin can communicate it.

Usage:
  python restore_users.py --file backups/users_backup_YYYYMMDD_HHMMSS.json
"""
import argparse
import json
import os
import secrets
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db, bcrypt
from models import User


def parse_args():
    p = argparse.ArgumentParser(description='Restore users from JSON backup')
    p.add_argument('--file', '-f', required=True, help='Path to users backup JSON')
    p.add_argument('--dry-run', action='store_true', help='Show actions without committing')
    return p.parse_args()


def coerce_str(obj):
    if isinstance(obj, (bytes, bytearray)):
        try:
            return obj.decode('utf-8')
        except Exception:
            return None
    return obj


def restore(filepath, dry_run=False):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return 1

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    created = 0
    updated = 0
    skipped = 0
    generated_credentials = []

    with app.app_context():
        for rec in data:
            username = (rec.get('username') or '').strip()
            if not username:
                skipped += 1
                continue

            role = rec.get('role') or 'teacher'
            subject = rec.get('subject')
            class_name = rec.get('class_name')
            classes = rec.get('classes') or []
            ph = coerce_str(rec.get('password_hash'))
            created_at = rec.get('created_at')

            user = User.query.filter_by(username=username).first()
            if user:
                changed = False
                if user.role != role:
                    user.role = role; changed = True
                if getattr(user, 'subject', None) != subject:
                    user.subject = subject; changed = True
                if getattr(user, 'class_name', None) != class_name:
                    user.class_name = class_name; changed = True
                # classes stored as JSON; set if different
                try:
                    existing_classes = user.get_classes_list() if hasattr(user, 'get_classes_list') else []
                except Exception:
                    existing_classes = []
                if classes and sorted(existing_classes) != sorted(classes):
                    user.set_classes_list(classes); changed = True

                # Only overwrite password_hash if the backup contains one
                if ph:
                    user.password_hash = ph; changed = True

                if created_at and not getattr(user, 'created_at', None):
                    try:
                        user.created_at = datetime.fromisoformat(created_at)
                        changed = True
                    except Exception:
                        pass

                if changed:
                    if not dry_run:
                        db.session.add(user)
                    updated += 1

            else:
                # New user
                if ph:
                    password_hash = ph
                    generated_pw = None
                else:
                    # generate a temporary password for new user
                    generated_pw = secrets.token_urlsafe(8)
                    password_hash = bcrypt.generate_password_hash(generated_pw).decode('utf-8')

                new_user = User(
                    username=username,
                    password_hash=password_hash,
                    role=role,
                    subject=subject,
                    class_name=class_name,
                )
                if classes and isinstance(classes, list):
                    new_user.set_classes_list(classes)
                if created_at:
                    try:
                        new_user.created_at = datetime.fromisoformat(created_at)
                    except Exception:
                        pass

                if not dry_run:
                    db.session.add(new_user)
                created += 1
                if generated_pw:
                    generated_credentials.append((username, generated_pw))

        if not dry_run:
            db.session.commit()

    print(f"Restore complete: created={created}, updated={updated}, skipped={skipped}")
    if generated_credentials:
        print("\nGenerated temporary credentials for new users (share securely):")
        for u, pw in generated_credentials:
            print(f"  {u}: {pw}")

    return 0


if __name__ == '__main__':
    args = parse_args()
    exit(restore(args.file, dry_run=args.dry_run))
