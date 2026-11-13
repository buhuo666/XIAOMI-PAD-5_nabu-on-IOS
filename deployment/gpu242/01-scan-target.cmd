@echo off
setlocal
cd /d "%~dp0"
"%~dp0host\python\python.exe" -X utf8 "%~dp0tools\scan_target.py" %*
set "result=%errorlevel%"
echo.
echo Scan finished with exit code %result%. No tablet partitions were changed.
pause
exit /b %result%
