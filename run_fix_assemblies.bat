@echo off
title Fix Empty Assembly Documents
echo ============================================================
echo   Fix Empty Assembly Documents
echo ============================================================
echo.
echo This will upload BV-ASM-222-100.stp and Tower Assm.stp
echo to your Onshape account using your Chrome browser session.
echo.
echo IMPORTANT: Make sure you are logged into Onshape in Chrome
echo            before running this script!
echo.
pause

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Please install Python first.
    pause
    exit /b
)

echo Installing required packages...
pip install requests browser-cookie3 --quiet

echo.
echo Running fix...
echo.
python "%~dp0fix_empty_assemblies.py"
