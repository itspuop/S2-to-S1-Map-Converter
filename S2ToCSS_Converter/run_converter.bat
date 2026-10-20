@echo off
cd /d "%~dp0"
title S2ToCSS Converter - live progress
echo Starting S2ToCSS Converter. Progress messages will appear here while the GUI is running.
py -3 main.py
if errorlevel 1 (
  echo.
  echo S2ToCSS exited with an error. Review the message above.
  pause
)
