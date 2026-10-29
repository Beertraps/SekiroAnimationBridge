@echo off
setlocal
rem Check a game package with the bridge's conversion Python: tools\check_package.cmd <package folder> [options]
set "PYTHON=%LOCALAPPDATA%\SekiroAnimationBridge\writer-env\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo The conversion Python is missing. Run tools\setup_writer.cmd first.
  exit /b 1
)
"%PYTHON%" -X utf8 "%~dp0check_package.py" %*
exit /b %ERRORLEVEL%
