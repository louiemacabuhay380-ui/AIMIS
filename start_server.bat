@echo off
REM Double-click to start AIMIS as a server on this PC. Keep the window open; close it (or Ctrl+C) to stop.
cd /d "%~dp0"
if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat
python serve.py
pause
