@echo off
cd /d "%~dp0"

where pythonw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw.exe app.py
) else (
    start "" python.exe app.py
)
