@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_decoder.ps1" %*
exit /b %ERRORLEVEL%
