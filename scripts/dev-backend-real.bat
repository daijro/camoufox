@echo off
REM Start Local API with real Camoufox launch (needs pythonlib + downloaded binary)
cd /d "%~dp0..\backend"
set CAMOUFOX_REAL_LAUNCH=1
set PYTHONPATH=%~dp0..\pythonlib;%PYTHONPATH%
echo CAMOUFOX_REAL_LAUNCH=1 PYTHONPATH includes pythonlib
python -m uvicorn app.main:app --host 127.0.0.1 --port 50325
