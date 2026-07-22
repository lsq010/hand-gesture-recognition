@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting Gesture Recognition GUI...
"D:\Desk\test\v1\Scripts\python.exe" "main.py"
if errorlevel 1 pause
