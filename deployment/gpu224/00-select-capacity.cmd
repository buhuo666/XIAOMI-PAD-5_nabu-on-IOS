@echo off
cd /d "%~dp0"
host\python\python.exe -X utf8 tools\select_nabu_capacity.py
if errorlevel 1 goto finish
host\python\python.exe -X utf8 tools\prepare_selected_data.py
:finish
pause
