@echo off
cd /d "%~dp0"
if errorlevel 1 exit /b 1

rem Native startup failures can be negative; accept only an exact zero exit code.
if exist ".venv\Scripts\pythonw.exe" (
    ".venv\Scripts\pythonw.exe" -c "import sys, tkinter;raise SystemExit(sys.version_info < (3,10))"
    if errorlevel 0 if not errorlevel 1 (
        start "" ".venv\Scripts\pythonw.exe" ".\main.py"
        exit /b
    )
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
    pythonw -c "import sys, tkinter;raise SystemExit(sys.version_info < (3,10))"
    if errorlevel 0 if not errorlevel 1 (
        start "" pythonw ".\main.py"
        exit /b
    )
)

where pyw >nul 2>nul
if %errorlevel%==0 (
    pyw -3 -c "import sys, tkinter;raise SystemExit(sys.version_info < (3,10))"
    if errorlevel 0 if not errorlevel 1 (
        start "" pyw -3 ".\main.py"
        exit /b
    )
)

for /f "delims=" %%D in ('dir /b /ad /o-n "%LocalAppData%\Programs\Python\Python3??" 2^>nul') do (
    if exist "%LocalAppData%\Programs\Python\%%D\pythonw.exe" (
        "%LocalAppData%\Programs\Python\%%D\pythonw.exe" -c "import sys, tkinter;raise SystemExit(sys.version_info < (3,10))"
        if errorlevel 0 if not errorlevel 1 (
            start "" "%LocalAppData%\Programs\Python\%%D\pythonw.exe" ".\main.py"
            exit /b
        )
    )
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -c "import sys, tkinter;raise SystemExit(sys.version_info < (3,10))"
    if errorlevel 0 if not errorlevel 1 (
        start "" py -3 ".\main.py"
        exit /b
    )
)

where python >nul 2>nul
if %errorlevel%==0 (
    python -c "import sys, tkinter;raise SystemExit(sys.version_info < (3,10))"
    if errorlevel 0 if not errorlevel 1 (
        start "" python ".\main.py"
        exit /b
    )
)

echo Python with Tkinter not found. Install Python 3.10+ or check the project .venv.
exit /b 1
