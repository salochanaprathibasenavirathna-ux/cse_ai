@echo off
setlocal
set "APP_DIR=%~dp0"
if not exist "%APP_DIR%CSE AI Alpha Terminal.exe" (
    echo CSE AI Alpha Terminal.exe was not found. Extract the complete download ZIP first.
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$app = $env:APP_DIR; $target = Join-Path $app 'CSE AI Alpha Terminal.exe'; $desktop = [Environment]::GetFolderPath('Desktop'); $shell = New-Object -ComObject WScript.Shell; $shortcut = $shell.CreateShortcut((Join-Path $desktop 'CSE AI Alpha Terminal.lnk')); $shortcut.TargetPath = $target; $shortcut.WorkingDirectory = $app; $shortcut.IconLocation = $target + ',0'; $shortcut.Description = 'Launch CSE AI Alpha Terminal'; $shortcut.Save()"
if errorlevel 1 (
    echo Could not create the desktop shortcut.
    pause
    exit /b 1
)
echo Desktop shortcut created. Double-click CSE AI Alpha Terminal on your desktop.
pause
endlocal
