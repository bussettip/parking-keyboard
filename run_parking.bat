@echo off
cd /d "%~dp0"
echo Iniciando Parking Dashboard en http://localhost:5100
echo.
python dashboard_server.py
pause
