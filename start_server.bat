@echo off
chcp 65001 > nul
cls
echo ==================================================
echo   SmartStore Order Management System
echo   Web Server Running...
echo   Open Browser at: http://localhost:5000
echo ==================================================
python server.py
pause
