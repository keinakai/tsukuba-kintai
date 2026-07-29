@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" kintai_app.py
) else (
    echo Please run setup.bat first.
    pause
)
