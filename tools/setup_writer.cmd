@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_writer.ps1" %*
exit /b %ERRORLEVEL%
