@echo off
setlocal

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found. Install Python 3.10 or newer and add it to PATH.
    exit /b 1
)

where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv was not found. Install uv and add it to PATH.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] Creating virtual environment: .venv
    uv venv
    if errorlevel 1 exit /b 1
)

echo [INFO] Installing/updating dependencies
uv pip install -e .
if errorlevel 1 exit /b 1

echo [INFO] Starting Robotrace Course CAD
".venv\Scripts\robotrace-course-cad.exe" %*

