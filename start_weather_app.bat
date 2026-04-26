@echo off
cd /d "%~dp0"

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw .\main.py
    exit /b 0
)

where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 .\main.py
    exit /b 0
)

set "LOCAL_PYW=%LocalAppData%\Programs\Python\Python313\pythonw.exe"
if exist "%LOCAL_PYW%" (
    start "" "%LOCAL_PYW%" .\main.py
    exit /b 0
)

set "LOCAL_PYW=%LocalAppData%\Programs\Python\Python312\pythonw.exe"
if exist "%LOCAL_PYW%" (
    start "" "%LOCAL_PYW%" .\main.py
    exit /b 0
)

set "LOCAL_PYW=%LocalAppData%\Programs\Python\Python311\pythonw.exe"
if exist "%LOCAL_PYW%" (
    start "" "%LOCAL_PYW%" .\main.py
    exit /b 0
)

set "LOCAL_PYW=%LocalAppData%\Programs\Python\Python310\pythonw.exe"
if exist "%LOCAL_PYW%" (
    start "" "%LOCAL_PYW%" .\main.py
    exit /b 0
)

where py >nul 2>nul
if %errorlevel%==0 (
    start "" py -3 .\main.py
    exit /b 0
)

where python >nul 2>nul
if %errorlevel%==0 (
    start "" python .\main.py
    exit /b 0
)

echo Python not found. Install Python 3.10+ or add it to PATH.
pause
