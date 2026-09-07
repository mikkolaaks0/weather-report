import json
from pathlib import Path
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable,
    VarFileInfo, VarStruct, VSVersionInfo,
)


project_dir = Path(SPECPATH).resolve()
metadata = json.loads((project_dir / "app_metadata.json").read_text(encoding="utf-8"))
version_number = tuple(int(part) for part in metadata["version"].split(".")) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=version_number, prodvers=version_number,
        mask=0x3F, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0),
    ),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("FileDescription", "Weather Report"),
            StringStruct("FileVersion", metadata["version"]),
            StringStruct("ProductName", "Weather Report"),
            StringStruct("ProductVersion", metadata["version"]),
            StringStruct("OriginalFilename", "WeatherReport.exe"),
        ])]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

datas = []


def add_data_dir(source_dir, destination):
    if not source_dir.exists():
        return

    for file_path in source_dir.iterdir():
        if file_path.is_file():
            datas.append((str(file_path), destination))


data_files = [
    ("app_metadata.json", "."),
    ("README.md", "."),
    ("LICENSE", "."),
    ("THIRD_PARTY_NOTICES.md", "."),
    ("assets/logo.png", "assets"),
    ("assets/app.ico", "assets"),
]
for filename, destination in data_files:
    file_path = project_dir / filename
    if file_path.exists():
        datas.append((str(file_path), destination))

add_data_dir(project_dir / "assets" / "weather-icons", "assets/weather-icons")
add_data_dir(project_dir / "assets" / "metric-icons", "assets/metric-icons")
add_data_dir(project_dir / "assets" / "fonts", "assets/fonts")


a = Analysis(
    ["main.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "pystray",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageFilter",
        "PIL.ImageTk",
    ],
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
    version=version_info,
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

