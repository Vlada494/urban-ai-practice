@echo off
cd /d "%~dp0"
set "PATH=%~dp0.venv\Scripts;%LOCALAPPDATA%\Programs\node-v24.22.1-win-x64;%LOCALAPPDATA%\Microsoft\WinGet\Packages\ezwinports.make_Microsoft.Winget.Source_8wekyb3d8bbwe\bin;%PATH%"
set "VIRTUAL_ENV=%~dp0.venv"
set "SHELL=powershell.exe"
set "PYTHONUTF8=1"
set "PSModulePath=%ProgramFiles%\WindowsPowerShell\Modules;%SystemRoot%\System32\WindowsPowerShell\v1.0\Modules;%USERPROFILE%\Documents\WindowsPowerShell\Modules"
call "%LOCALAPPDATA%\Programs\node-v24.22.1-win-x64\opencode.cmd" "%~dp0."
