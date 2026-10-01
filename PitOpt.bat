@echo off
rem PitOpt - double-click to start the UI (project lives in WSL).
rem Server runs in WSL; this window stays open while it runs. Close it to stop.
setlocal
set PORT=8765
set DISTRO=Ubuntu-24.04

rem Convert this folder to a Linux path. cmd cannot cd into a UNC path, so
rem strip the WSL UNC prefix by hand instead of calling wslpath.
set "P=%~dp0"
set "LINUXDIR="
if /i "%P:~0,5%"=="\\wsl" call :unc
if not defined LINUXDIR (
  for /f "usebackq delims=" %%i in (`wsl.exe -d %DISTRO% wslpath -a "%~dp0"`) do set "LINUXDIR=%%i"
)
if not defined LINUXDIR (
  echo Tidak bisa menemukan folder di WSL distro %DISTRO%. Ubah DISTRO di file ini.
  pause & exit /b 1
)
echo Folder WSL: %LINUXDIR%

echo PitOpt: memulai server di http://localhost:%PORT%  (tutup jendela ini untuk berhenti)
start "" /b cmd /c "timeout /t 4 /nobreak >nul & start http://localhost:%PORT%"
wsl.exe -d %DISTRO% --cd "%LINUXDIR%" -e env NO_BROWSER=1 bash scripts/start_ui.sh %PORT%
echo.
echo Server berhenti.
pause

exit /b 0

:unc
set "PFX1=\\wsl.localhost\%DISTRO%"
set "PFX2=\\wsl$\%DISTRO%"
call set "P=%%P:%PFX1%=%%"
call set "P=%%P:%PFX2%=%%"
call set "LINUXDIR=%%P:\=/%%"
exit /b 0
