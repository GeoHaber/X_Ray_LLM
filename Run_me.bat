@echo off
title X-Ray Scanner - Web UI

:: Global llama.cpp defaults (shared across repos)
if "%ZENAI_LLAMA_SERVER%"=="" set "ZENAI_LLAMA_SERVER=C:\Ai\_bin\llama-server.exe"
if "%SWARM_MODELS_DIR%"=="" set "SWARM_MODELS_DIR=C:\Ai\Models"
if "%PATH:C:\Ai\_bin;=%"=="%PATH%" set "PATH=C:\Ai\_bin;%PATH%"

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
