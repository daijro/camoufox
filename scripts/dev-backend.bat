@echo off
REM Start Camoufox Console Local API (mock launch by default)
cd /d "%~dp0..\backend"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  call .venv\Scripts\pip install -r requirements.txt
)
set CAMOUFOX_REAL_LAUNCH=0
call .venv\Scripts\uvicorn.exe app.main:app --reload --host 127.0.0.1 --port 50325
