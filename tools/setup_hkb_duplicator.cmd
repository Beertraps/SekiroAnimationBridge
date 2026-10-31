@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_hkb_duplicator.ps1" %*
exit /b %ERRORLEVEL%
