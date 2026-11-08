@echo off
title PARKIQ - Intelligent Parking System
echo ===================================================
echo   Starting PARKIQ AI Parking Backend Server...
echo ===================================================

cd /d "%~dp0"
if exist "backend\venv\Scripts\python.exe" (
    "backend\venv\Scripts\python.exe" run_backend.py
) else (
    python run_backend.py
)
pause
