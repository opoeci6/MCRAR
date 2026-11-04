@echo off
rem MCRAR portable launcher. Runs MCRAR in its own window with the bundled Python.
rem Everything (data, models, caches, API keys, the log) stays inside this folder: nothing is
rem written to the user profile or the registry.
rem Options: MCRAR.cmd --port 8010
rem          MCRAR.cmd --console    (keep this console and print the log in it; for troubleshooting)
rem Without --console this script starts MCRAR and ends; the log is logs\mcrar.log.
setlocal

set "APP=%~dp0"
if "%APP:~-1%"=="\" set "APP=%APP:~0,-1%"

title MCRAR

if not exist "%APP%\python\python.exe" (
    echo MCRAR cannot start: python\python.exe is missing next to MCRAR.cmd.
    echo Unzip the whole MCRAR folder first, then double-click MCRAR.cmd inside it.
    echo.
    pause
    exit /b 1
)
if not exist "%APP%\python\pythonw.exe" (
    echo MCRAR cannot start: python\pythonw.exe is missing next to MCRAR.cmd.
    echo Unzip the whole MCRAR folder first, then double-click MCRAR.cmd inside it.
    echo.
    pause
    exit /b 1
)

rem The zip's last entry: without it the unzip stopped early or ran out of disk space.
if not exist "%APP%\python\.complete" (
    echo The MCRAR folder is incomplete: unzipping did not finish, or ran out of disk space.
    echo Delete this folder, make sure about 2.5 GB is free, and unzip again. Wait until the
    echo unzip window closes before you start MCRAR.cmd.
    echo.
    pause
    exit /b 1
)

set "MCRAR_HOME=%APP%"

rem Model weights and library caches go inside this folder, not the user profile.
set "HF_HOME=%APP%\.cache\huggingface"
set "HF_HUB_CACHE=%APP%\.cache\huggingface\hub"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"
set "TORCH_HOME=%APP%\.cache\torch"
set "PYTORCH_KERNEL_CACHE_PATH=%APP%\.cache\torch\kernels"
set "TORCHINDUCTOR_CACHE_DIR=%APP%\.cache\torchinductor"
set "NUMBA_CACHE_DIR=%APP%\.cache\numba"
set "MPLCONFIGDIR=%APP%\.cache\matplotlib"
set "XDG_CACHE_HOME=%APP%\.cache"
set "PYTHONNOUSERSITE=1"

if /i "%~1"=="--console" goto console

rem pythonw has no console window: the window is MCRAR's own, the log goes to logs\mcrar.log and
rem a start-up problem shows in a message box. This script does not wait for it.
start "" "%APP%\python\pythonw.exe" -I -m mcrar desktop --warm %*
endlocal & exit /b 0

:console
rem shift drops --console; %* is not changed by it, so the rest is listed one by one.
shift
echo MCRAR is starting. The first start downloads the search model (about 0.8 GB). Close the MCRAR window to stop it.
echo.

"%APP%\python\python.exe" -I -m mcrar desktop --warm --console-log %1 %2 %3 %4 %5 %6 %7 %8 %9
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo MCRAR stopped with exit code %RC%. The message above says why.
    pause
)
endlocal & exit /b %RC%
