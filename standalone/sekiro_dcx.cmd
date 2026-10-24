@echo off
setlocal
set "BRIDGE_PYTHON=%LOCALAPPDATA%\SekiroAnimationBridge\writer-env\Scripts\python.exe"
if not exist "%BRIDGE_PYTHON%" (
  echo Conversion Python is missing. Run tools\setup_writer.cmd once.
  exit /b 1
)
"%BRIDGE_PYTHON%" -E -X utf8 "%~dp0dcx_codec.py" %*
exit /b %ERRORLEVEL%
