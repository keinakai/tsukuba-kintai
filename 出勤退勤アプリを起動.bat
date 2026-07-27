@echo off
chcp 65001 >nul
rem アプリを起動します（毎回これをダブルクリック）
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" kintai_app.py
) else (
    echo 先に setup.bat を実行してください。
    pause
)
