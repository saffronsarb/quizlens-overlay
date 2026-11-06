@echo off
cd /d "%~dp0"

:: Start Ollama in background if offline
curl.exe -s http://127.0.0.1:11434 >nul 2>&1
if %errorlevel% neq 0 (
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" (
        start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
    ) else (
        where ollama >nul 2>&1
        if %errorlevel% equ 0 (
            start /b "" ollama serve >nul 2>&1
        )
    )
)

where pythonw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw.exe app.py
) else (
    start "" python.exe app.py
)
