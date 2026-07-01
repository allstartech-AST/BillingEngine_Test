@echo off
cd /d "%~dp0"
set PY=%LocalAppData%\Programs\Python\Python312\python.exe
if not exist "%PY%" (
  echo Python not found at %PY%
  pause
  exit /b 1
)
"%PY%" -m pip install -r requirements.txt -q
echo.
echo Billing Engine UI:  http://127.0.0.1:8000/prototype
echo API docs (Swagger): http://127.0.0.1:8000/docs
echo Press Ctrl+C to stop.
echo.
"%PY%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
