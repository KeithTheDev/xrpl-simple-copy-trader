@echo off
REM ------------------------------------------------------------------
REM XRPL Token Monitor - Windows version with UTF-8 forced
REM ------------------------------------------------------------------

REM 1. Force console to use code page 65001 (UTF-8) and set Python to UTF-8
chcp 65001 >NUL
set PYTHONUTF8=1

REM 2. Default values
set "PORT=8000"
set "DEBUG=false"
set "TEST_MODE=false"
set "MODE=web"

REM By default, show a short header
echo XRPL Token Monitor

REM 3. Jump to parse_args with all parameters
call :parse_args %*
goto :main

REM ------------------------------------------------------------------
REM :parse_args - handle command-line arguments
:parse_args
:loop
if "%~1"=="" (
    goto after_parse
)

if /i "%~1"=="-h" (
    call :show_help
    exit /b 0
) else if /i "%~1"=="--help" (
    call :show_help
    exit /b 0
) else if /i "%~1"=="-p" (
    set "PORT=%~2"
    shift
    shift
    goto loop
) else if /i "%~1"=="--port" (
    set "PORT=%~2"
    shift
    shift
    goto loop
) else if /i "%~1"=="-d" (
    set "DEBUG=true"
    shift
    goto loop
) else if /i "%~1"=="--debug" (
    set "DEBUG=true"
    shift
    goto loop
) else if /i "%~1"=="-t" (
    set "TEST_MODE=true"
    shift
    goto loop
) else if /i "%~1"=="--test" (
    set "TEST_MODE=true"
    shift
    goto loop
) else if /i "%~1"=="web" (
    set "MODE=web"
    shift
    goto loop
) else if /i "%~1"=="memecoin" (
    set "MODE=memecoin"
    shift
    goto loop
) else (
    echo Unknown option: %~1
    call :show_help
    exit /b 1
)

goto loop

:after_parse
exit /b 0

REM ------------------------------------------------------------------
REM :show_help - prints usage information
:show_help
echo(
echo Usage: startOnWindows.cmd [options] [mode]
echo(
echo Modes:
echo   web       Start web interface (default)
echo   memecoin  Start memecoin monitor directly
echo(
echo Options:
echo   -h, --help          Show this help message
echo   -p, --port PORT     Set web interface port (default: 8000)
echo   -d, --debug         Enable debug mode
echo   -t, --test          Enable test mode (no real transactions)
echo(
exit /b 0

REM ------------------------------------------------------------------
REM :main - main logic after parsing arguments
:main

REM 4. Change to the script's directory
cd /d "%~dp0"

REM 5. Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in your PATH.
    exit /b 1
)

REM 6. Print which Python version we found
for /f "tokens=*" %%i in ('python --version') do set "PYTHON_VERSION=%%i"
echo [INFO] Using Python: %PYTHON_VERSION%

REM 7. Decide which Python script to run based on MODE
if /i "%MODE%"=="web" (
    set "SCRIPT=web_server.py"
    set "ARGS=--port %PORT%"
) else if /i "%MODE%"=="memecoin" (
    set "SCRIPT=memecoin_monitor.py"
    set "ARGS="
) else (
    echo [ERROR] Unknown mode: %MODE%
    call :show_help
    exit /b 1
)

REM 8. Check if the chosen script exists
if not exist "%SCRIPT%" (
    echo [ERROR] Python script not found: "%SCRIPT%"
    exit /b 1
)

REM 9. Add debug/test flags if enabled
if /i "%DEBUG%"=="true" (
    set "ARGS=%ARGS% --debug"
)
if /i "%TEST_MODE%"=="true" (
    set "ARGS=%ARGS% --test"
)

REM 10. Print config
echo [INFO] Starting in mode: %MODE%
if /i "%MODE%"=="web" (
    echo [INFO]   Port: %PORT%
)
echo [INFO]   Debug mode: %DEBUG%
echo [INFO]   Test mode: %TEST_MODE%

if /i "%MODE%"=="web" (
    echo [INFO] Open your browser at: http://localhost:%PORT%
)

REM 11. Run the Python script
python "%SCRIPT%" %ARGS%
set EXITCODE=%ERRORLEVEL%

if %EXITCODE% NEQ 0 (
    echo [ERROR] Script exited with code %EXITCODE%.
    exit /b %EXITCODE%
)

REM 12. Keep the window open if double-clicked
if "%TERM%"=="" (
    echo(
    echo Press any key to exit...
    pause >nul
)

exit /b 0
