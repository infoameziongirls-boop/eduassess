@echo off
set DATABASE_URL=sqlite:///instance/assessment.db
call venv\Scripts\activate.bat
python app.py
pause