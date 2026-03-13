@echo off
title X-Ray Code Analysis ^& Refactoring Tool

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║         X-Ray Code Analysis Tool  v8.0                  ║
echo ║                  Starting Flet UI...                     ║
echo ╚══════════════════════════════════════════════════════════╝
echo.
echo Launching X-Ray (native desktop window)
echo.

cd /d "%~dp0"
python x_ray_flet.py

pause
