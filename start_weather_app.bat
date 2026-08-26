@echo off
cd /d "%~dp0"

where pythonw >nul 2>nul
if %errorlevel%==0 (
    pythonw -c "import sys;raise SystemExit(sys.version_info < (3,10))"
    if not errorlevel 1 (
        start "" pythonw ".\main.py"
        exit /b 0
    )
)

where pyw >nul 2>nul
if %errorlevel%==0 (
    pyw -3 -c "import sys;raise SystemExit(sys.version_info < (3,10))"
    if not errorlevel 1 (
        start "" pyw -3 ".\main.py"
        exit /b 0
    )
)

for /f "delims=" %%D in ('dir /b /ad /o-n "%LocalAppData%\Programs\Python\Python3??" 2^>nul') do (
    if exist "%LocalAppData%\Programs\Python\%%D\pythonw.exe" (
        start "" "%LocalAppData%\Programs\Python\%%D\pythonw.exe" ".\main.py"
        exit /b 0
    )
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -c "import sys;raise SystemExit(sys.version_info < (3,10))"
    if not errorlevel 1 (
        start "" py -3 ".\main.py"
        exit /b 0
    )
)

where python >nul 2>nul
if %errorlevel%==0 (
    python -c "import sys;raise SystemExit(sys.version_info < (3,10))"
    if not errorlevel 1 (
        start "" python ".\main.py"
        exit /b 0
    )
)

echo Python not found. Install Python 3.10+ or add it to PATH.
exit /b 1
