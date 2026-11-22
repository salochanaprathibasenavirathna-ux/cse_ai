@echo off
setlocal
cd /d "%~dp0"
if not exist "venv\Scripts\pythonw.exe" (
    echo Run run.bat once first (it creates the venv and installs packages).
    pause
    exit /b 1
)
call venv\Scripts\activate
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed. Auto-start was not changed.
    pause
    exit /b 1
)
set "VBS=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\CSE_AI_Agent.vbs"
> "%VBS%" echo CreateObject("WScript.Shell").Run """%~dp0venv\Scripts\pythonw.exe"" ""%~dp0agent_service.py""", 0, False
start "" wscript "%VBS%"
echo.
echo Background AI Agent installed. It starts automatically when you log in to Windows
echo and works even when the app window is closed. Use stop_agent.bat to stop it.
pause
endlocal
