@echo off
setlocal
powershell.exe -NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0sekiro_animation_gui.ps1" %*
exit /b %ERRORLEVEL%
