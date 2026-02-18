@echo off
call venv\Scripts\activate.bat
python backup_users.py
echo Backup completed. Check backups/ directory.
pause