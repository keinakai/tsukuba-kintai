@echo off
chcp 65001 >nul
rem 初回セットアップ（1回だけ実行）
rem 専用の隔離環境(venv)を作り、その中に Playwright とブラウザを導入します。

cd /d "%~dp0"
set "VENV=%cd%\.venv"

echo ==============================================
echo  出退勤打刻アプリ セットアップ (Windows)
echo ==============================================

where python >nul 2>nul
if errorlevel 1 (
    echo [エラー] Python が見つかりません。
    echo   https://www.python.org/downloads/ から Python 3 をインストールしてください。
    echo   インストール時、最初の画面で必ず
    echo   「Add python.exe to PATH」にチェックを入れてください。
    pause
    exit /b 1
)

echo ・専用環境(venv)を作成します…
if exist "%VENV%" rmdir /s /q "%VENV%"
python -m venv "%VENV%"

echo ・Playwright とログイン情報保管用ライブラリを導入します…
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install playwright keyring

echo ・ブラウザ本体を導入します（導入済みなら再利用）…
"%VENV%\Scripts\python.exe" -m playwright install chromium

"%VENV%\Scripts\python.exe" -c "import tkinter, playwright, keyring" >nul 2>nul
if errorlevel 1 (
    echo.
    echo [警告] 何かが不足しています。表示された内容をサポートに伝えてください。
) else (
    echo.
    echo [完了] セットアップ完了。
    echo   次回からは「出勤退勤アプリを起動.bat」をダブルクリックしてください。
)
pause
