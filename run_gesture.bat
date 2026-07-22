@echo off
chcp 65001 >nul
REM 切换到脚本所在目录（兼容双击或从其他目录调用）
cd /d "%~dp0"
echo Starting Gesture Recognition in %CD%
"D:\Desk\test\v1\Scripts\python.exe" "gesture_recognition.py"
if errorlevel 1 pause
