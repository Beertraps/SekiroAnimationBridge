@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\create_shortcut.ps1"
set "shortcutExit=%ERRORLEVEL%"
if not "%shortcutExit%"=="0" pause
exit /b %shortcutExit%
