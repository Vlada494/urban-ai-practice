@echo off
set "PATH=%LOCALAPPDATA%\Programs\node-v24.22.1-win-x64;%LOCALAPPDATA%\Microsoft\WinGet\Packages\ezwinports.make_Microsoft.Winget.Source_8wekyb3d8bbwe\bin;%PATH%"
start "" "%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe" --new-window --locale ru "%~dp0."
