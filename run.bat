@echo off
set DATABASE_URL=sqlite:///persistent.db
call venv\Scripts\activate.bat
python app.py
pause