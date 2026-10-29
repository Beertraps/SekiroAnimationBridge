@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare_dotnet_runtime.ps1" %*
exit /b %ERRORLEVEL%
