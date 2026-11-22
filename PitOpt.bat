@echo off
rem PitOpt - double-click or run from cmd/PowerShell to start the local web UI.
rem Prefers native Windows Python (.venv, py -3, or python 3.10+); falls back to WSL2 only if absent.
setlocal enabledelayedexpansion

set "PORT=%PITOPT_PORT%"
if not defined PORT set "PORT=8765"
set "DISTRO=Ubuntu-24.04"
set "CHECK_ONLY=0"

:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--check-only" (
  set "CHECK_ONLY=1"
  shift
  goto :parse_args
)
if /i "%~1"=="--port" (
  if "%~2"=="" (
    echo [PitOpt] Error: --port membutuhkan nomor port.
    exit /b 1
  )
  set "PORT=%~2"
  shift
  shift
  goto :parse_args
)
set "PORT=%~1"
shift
goto :parse_args

:args_done
cd /d "%~dp0"

rem 1. Detect native Windows Python 3.10+ (.venv first, then py -3, then python)
set "PY_CMD="
set "VENV_PY=.venv\Scripts\python.exe"

if exist "%VENV_PY%" (
  "%VENV_PY%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY_CMD=%VENV_PY%"
)

if not defined PY_CMD (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY_CMD=py -3"
)

if not defined PY_CMD (
  python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
  if not errorlevel 1 set "PY_CMD=python"
)

if defined PY_CMD goto :run_native

rem 2. Fallback to WSL2 only when native Windows Python 3.10+ is absent
where wsl.exe >nul 2>&1
if errorlevel 1 (
  echo [PitOpt] Python 3.10+ native tidak ditemukan dan WSL2 tidak tersedia.
  echo [PitOpt] Pasang Python 3.10+ dari https://www.python.org/downloads/ lalu jalankan ulang PitOpt.bat.
  if "%CHECK_ONLY%"=="0" pause
  exit /b 1
)

echo [PitOpt] Python Windows native 3.10+ tidak ditemukan; menggunakan fallback WSL2 (%DISTRO%)...
set "P=%~dp0"
set "LINUXDIR="
if /i "%P:~0,5%"=="\\wsl" call :unc
if not defined LINUXDIR (
  for /f "usebackq delims=" %%i in (`wsl.exe -d %DISTRO% wslpath -a "%~dp0"`) do set "LINUXDIR=%%i"
)
if not defined LINUXDIR (
  echo Tidak bisa menemukan folder di WSL distro %DISTRO%. Ubah DISTRO di file ini.
  if "%CHECK_ONLY%"=="0" pause
  exit /b 1
)
echo Folder WSL: %LINUXDIR%

if "%CHECK_ONLY%"=="1" (
  wsl.exe -d %DISTRO% --cd "%LINUXDIR%" -e bash scripts/start_ui.sh --check-only --port %PORT%
  exit /b %errorlevel%
)

echo PitOpt: memulai server di http://localhost:%PORT%  (tutup jendela ini untuk berhenti)
start "" /b cmd /c "timeout /t 4 /nobreak >nul & start "" "http://localhost:%PORT%""
wsl.exe -d %DISTRO% --cd "%LINUXDIR%" -e env NO_BROWSER=1 bash scripts/start_ui.sh %PORT%
echo.
echo Server berhenti.
pause
exit /b 0

:run_native
rem Validate port number and ensure pitopt is importable (bootstrap .venv if needed)
%PY_CMD% -c "import sys; p=int(sys.argv[1]); raise SystemExit(0 if 1 <= p <= 65535 else 1)" "%PORT%" >nul 2>&1
if errorlevel 1 (
  echo [PitOpt] Port tidak valid: %PORT%
  if "%CHECK_ONLY%"=="0" pause
  exit /b 1
)

%PY_CMD% -c "import pitopt" >nul 2>&1
if errorlevel 1 (
  if "%CHECK_ONLY%"=="1" (
    echo [PitOpt] Paket pitopt belum terpasang pada %PY_CMD%.
    exit /b 1
  )
  echo [PitOpt] Menyiapkan .venv dan memasang dependensi PitOpt...
  if not exist "%VENV_PY%" (
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
      echo [PitOpt] Gagal membuat .venv.
      pause
      exit /b 1
    )
  )
  "%VENV_PY%" -m pip install --quiet --upgrade pip
  "%VENV_PY%" -m pip install --default-timeout=300 -e .
  if errorlevel 1 (
    echo [PitOpt] Gagal memasang PitOpt ke .venv.
    pause
    exit /b 1
  )
  set "PY_CMD=%VENV_PY%"
)

rem Check port availability on 127.0.0.1
%PY_CMD% -c "import socket, sys; s=socket.socket(); s.settimeout(0.5); busy=s.connect_ex(('127.0.0.1', int(sys.argv[1])))==0; s.close(); raise SystemExit(1 if busy else 0)" "%PORT%" >nul 2>&1
set "PORT_BUSY=%errorlevel%"

if "%CHECK_ONLY%"=="1" (
  %PY_CMD% -m pitopt ui --help >nul 2>&1
  if errorlevel 1 exit /b 1
  echo [PitOpt check-only] Python=%PY_CMD% Port=%PORT% Busy=%PORT_BUSY%
  exit /b 0
)

if "%PORT_BUSY%"=="1" (
  echo [PitOpt] Port %PORT% sudah digunakan di 127.0.0.1.
  echo [PitOpt] Tutup instance PitOpt yang sedang berjalan atau jalankan: PitOpt.bat --port 8766
  pause
  exit /b 1
)

set "UI_ARGS=--root . --port %PORT%"
if "%NO_BROWSER%"=="1" set "UI_ARGS=%UI_ARGS% --no-browser"

echo [PitOpt] Menjalankan server native di http://127.0.0.1:%PORT%  (Ctrl+C atau tutup jendela untuk berhenti)
%PY_CMD% -m pitopt ui %UI_ARGS%
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
