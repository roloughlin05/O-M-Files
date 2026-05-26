@echo off
title Onshape Bulk Import
echo ============================================================
echo   Onshape Bulk Import - Setting up...
echo ============================================================
echo.

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Installing via winget...
    winget install Python.Python.3.12 -e --silent
    echo.
    echo Please close and reopen this window after Python installs, then run again.
    pause
    exit /b
)

echo Python found. Installing required packages...
pip install requests --quiet

echo.
echo Starting import...
echo.
python "%~dp0onshape_import.py"
