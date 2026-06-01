from pathlib import Path


project_dir = Path(SPECPATH).resolve()

datas = []


def add_data_dir(source_dir, destination):
    if not source_dir.exists():
        return

    for file_path in source_dir.iterdir():
        if file_path.is_file():
            datas.append((str(file_path), destination))


data_files = [
    ("README.md", "."),
    ("start_weather_app.bat", "."),
    ("start_weather_app.vbs", "."),
    ("assets/logo.png", "assets"),
    ("assets/app.ico", "assets"),
    ("assets/tray.png", "assets"),
]
for filename, destination in data_files:
    file_path = project_dir / filename
    if file_path.exists():
        datas.append((str(file_path), destination))

add_data_dir(project_dir / "assets" / "weather-icons", "assets/weather-icons")
add_data_dir(project_dir / "assets" / "fonts", "assets/fonts")


a = Analysis(
    ["main.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=["pystray", "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WeatherReport",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_dir / "assets" / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="WeatherReport",
)

