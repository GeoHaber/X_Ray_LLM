@echo off
title X-Ray Code Analysis UI

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║         X-Ray Code Analysis & Refactoring Tool          ║
echo ║                  Starting Flet UI...                     ║
echo ╚══════════════════════════════════════════════════════════╝
echo.
echo Launching X-Ray at: http://localhost:8550
echo.

cd /d "%~dp0"
python x_ray_flet.py

pause
