@echo off
setlocal
cd /d "%~dp0"
set "VENV=%cd%\.venv"

echo ==============================================
echo   Tsukuba Kintai App - Setup (Windows)
echo ==============================================
echo.

set "PY="
where python >nul 2>nul
if not errorlevel 1 set "PY=python"

if not defined PY (
    where py >nul 2>nul
    if not errorlevel 1 set "PY=py"
)

if not defined PY (
    echo [ERROR] Python was not found.
    echo.
    echo Please install Python 3 from https://www.python.org/downloads/
    echo IMPORTANT: On the very first install screen, check the box
    echo "Add python.exe to PATH" before clicking "Install Now".
    echo.
    echo After installing, RESTART YOUR COMPUTER once ^(this is required for
    echo Windows to notice the change^), then run this setup.bat again.
    pause
    exit /b 1
)

echo Using Python command: %PY%
%PY% --version
echo.

echo Step 1/3: Creating a private environment for this app...
if exist "%VENV%" rmdir /s /q "%VENV%"
%PY% -m venv "%VENV%"

if not exist "%VENV%\Scripts\python.exe" (
    echo.
    echo [ERROR] Failed to create the environment. Please copy everything
    echo shown above and share it for help.
    pause
    exit /b 1
)

echo Step 2/3: Installing Playwright and keyring...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install playwright keyring

echo Step 3/3: Installing the browser engine ^(Chromium^)...
"%VENV%\Scripts\python.exe" -m playwright install chromium

"%VENV%\Scripts\python.exe" -c "import tkinter, playwright, keyring" >nul 2>nul
if errorlevel 1 (
    echo.
    echo [WARNING] Something may still be missing. Please copy everything
    echo shown above and share it for help.
) else (
    echo.
    echo [DONE] Setup complete.
    echo Next time, just double-click the launch .bat file to start the app.
)
echo.
pause
