@echo off
echo Checking database setup...
echo.

if exist "instance\assessment.db" (
    echo ✓ Database file exists: instance\assessment.db
    for %%A in ("instance\assessment.db") do echo File size: %%~zA bytes
) else (
    echo ✗ Database file NOT found: instance\assessment.db
    echo This may cause data loss!
)

echo.
echo Current database URI setting:
python -c "from app import app; print('Database URI:', app.config['SQLALCHEMY_DATABASE_URI'])"

echo.
echo To start the app with persistent database, use: run.bat
echo.
pause