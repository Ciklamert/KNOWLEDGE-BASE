@echo off
rem AI-BRAIN launcher: brain serve | doctor | sync | search | ask | enhance | drift | connect
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Not installed yet. Run:  powershell -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0brain.py" %*
