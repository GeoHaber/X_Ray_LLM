@echo off
title X-Ray Scanner - Web UI

echo.
echo  +--------------------------------------------------------+
echo  :         X-Ray Scanner  v0.2.0                          :
echo  :              Starting Web UI...                        :
echo  +--------------------------------------------------------+
echo.
echo Server: http://127.0.0.1:8077
echo Press Ctrl+C to stop
echo.

cd /d "%~dp0"
start "" http://127.0.0.1:8077
python ui_server.py

pause
