@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
call "%~dp0scripts\windows\Ensure-Windows-Python.cmd"
if errorlevel 1 goto failed
rem Read-only CLI diagnostics must never provision or migrate a database.
if /I "%~1"=="--help" goto launch
if /I "%~1"=="--credential-status" goto launch
if /I "%~1"=="--setup" goto setup_only
if exist "%LOCALAPPDATA%\ActiveEcomBootcamp\postgres.json" goto launch
call "%~dp0scripts\windows\Setup-Windows.cmd" --from-start
if errorlevel 1 goto failed
if not exist "%LOCALAPPDATA%\ActiveEcomBootcamp\postgres.json" goto failed
:launch
"%ECOM_PY%" web_app.py %*
if errorlevel 1 goto failed
exit /b 0
:setup_only
call "%~dp0scripts\windows\Setup-Windows.cmd" --from-start
if errorlevel 1 goto failed
exit /b 0
:failed
echo Could not start the app. Review the message above.
pause
exit /b 1
