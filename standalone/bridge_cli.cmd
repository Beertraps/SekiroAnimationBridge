@echo off
setlocal
rem The bridge's JSON command line for scripts and agents: standalone\bridge_cli.cmd <command> [options]
set "PYTHON=%LOCALAPPDATA%\SekiroAnimationBridge\writer-env\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo {"ok": false, "error": "The conversion Python is missing. Start the bridge once or run tools\\setup_writer.cmd."}
  exit /b 1
)
"%PYTHON%" -E -X utf8 "%~dp0bridge_cli.py" %*
exit /b %ERRORLEVEL%
