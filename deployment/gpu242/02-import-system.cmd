@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Drag the downloaded iPad_10.2_16.5_20F66_Restore.ipsw onto this file.
  pause
  exit /b 2
)
"%~dp0host\python\python.exe" -X utf8 "%~dp0tools\import_system.py" --ipsw "%~1"
set "result=%errorlevel%"
pause
exit /b %result%
