@echo off
title QuizLens Overlay
cd /d "%~dp0"

echo Starting QuizLens Overlay...
python app.py
if errorlevel 1 (
    echo.
    echo Application exited with an error.
    pause
)
