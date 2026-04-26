# Weather Report

Weather Report is a lightweight Windows tray app for local weather at a glance.
It stays out of the way, updates automatically, and opens a compact forecast panel
from the system tray.

## Features

- Dynamic weather icon in the Windows system tray
- Compact popup with current conditions and a 6-day forecast
- City search with saved settings
- Temperature, daily high/low, precipitation, humidity, wind, sunrise and sunset
- Near-term precipitation probability based on the next 6 hours
- Automatic weather refresh every 30 minutes
- Optional startup shortcut for Windows login
- Manual app update check from the tray menu when running from a Git checkout

## Requirements

- Windows 11
- Python 3.10 or newer for source installs
- Internet access for weather data

Python dependencies are listed in [requirements.txt](./requirements.txt).

## Install

Windows users can install Weather Report with PowerShell after the first GitHub
Release is published:

```powershell
irm https://raw.githubusercontent.com/mikkolaaks0/weather-report/main/install.ps1 | iex
```

The script downloads the latest portable release, verifies it when
`SHA256SUMS.txt` is published with the release, installs it under
`%LOCALAPPDATA%\Programs\WeatherReport`, creates Start Menu and desktop
shortcuts, and launches the app.

Optional install flags:

```powershell
irm https://raw.githubusercontent.com/mikkolaaks0/weather-report/main/install.ps1 -OutFile install.ps1
.\install.ps1 -Startup
```

Useful flags are `-Startup`, `-NoDesktopShortcut`, `-NoStartMenuShortcut`, and
`-NoLaunch`.

To uninstall the portable install:

```powershell
irm https://raw.githubusercontent.com/mikkolaaks0/weather-report/main/uninstall.ps1 | iex
```

Add `-RemoveSettings` when running a downloaded `uninstall.ps1` file if you also
want to remove saved settings.

## Run From Source

```powershell
python -m pip install -r requirements.txt
python .\main.py
```

For a windowless launch, use:

```powershell
.\start_weather_app.vbs
```

## Build

Create a portable release package:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1 -SkipInstaller
```

Create a portable package and an installer, when Inno Setup is installed:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1
```

Release artifacts are written to `release/`.
`SHA256SUMS.txt` is generated alongside the release files.

## Publish A Release

1. Run `powershell -ExecutionPolicy Bypass -File .\build_release.ps1 -SkipInstaller`.
2. Create a new GitHub Release.
3. Upload `release/WeatherReport-portable.zip` and `release/SHA256SUMS.txt`.

The one-line installer uses the latest GitHub Release and verifies the portable
zip when `SHA256SUMS.txt` is present.

## Settings

User settings are stored under:

```text
%APPDATA%\weather-report\weather_settings.json
```

## Updates

When running from a Git checkout, the app can check `origin/main` for updates.
It only applies fast-forward updates, asks before updating, and restarts itself
after a successful update.

For public distribution, prefer GitHub Releases with a signed or checksummed
installer/portable package.

## Weather Data

Weather data is provided by Open-Meteo:

- [Open-Meteo](https://open-meteo.com/)
- [Terms](https://open-meteo.com/en/terms)
- [Licence](https://open-meteo.com/en/licence)

Third-party notices are listed in [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md).

## License

Weather Report is released under the [MIT License](./LICENSE).
