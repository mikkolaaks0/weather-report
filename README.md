# Weather Report

Weather Report is a lightweight Windows tray app for local weather at a glance.
It stays out of the way, updates automatically, and opens a compact forecast panel
from the system tray.

## Features

- Dynamic weather icon in the Windows system tray
- Compact popup with current conditions and a 6-day forecast
- Bundled Fluent-style weather icons for the tray, card, and forecast panel
- Bundled metric icons for rain amount, rain probability, humidity, and wind rows
- Bundled Exo 2 app font; no separate font installation is required
- City search with saved settings
- Temperature, daily high/low, precipitation, humidity, wind, sunrise and sunset
- Near-term precipitation probability based on the next 6 hours
- Automatic weather refresh every 30 minutes
- Optional startup shortcut for Windows login
- Automatic startup check and manual tray update check when running from a Git checkout

## Requirements

- Windows 11
- Python 3.10 or newer for source installs
- Internet access for weather data

Python dependencies are listed in [requirements.txt](./requirements.txt).

## Install

Windows users can install Weather Report from the latest GitHub Release with
PowerShell:

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
`-NoLaunch`. A custom `-InstallDir` must point to an app-specific
`WeatherReport` folder; the installer refuses broad user, AppData, Programs, or
drive-root paths before replacing an existing install. On updates, an existing
startup shortcut is preserved and rewritten to the current executable path.

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

Source-mode shortcuts use this launcher so they keep working after a compatible
Python installation is moved or upgraded.

## Build

Create a portable release package:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1 -Version 0.1.1 -SkipInstaller
```

Create a portable package and an installer, when Inno Setup is installed:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1 -Version 0.1.1
```

Release artifacts are written to `release/`. `SHA256SUMS.txt` contains only the
artifacts produced by the current build, so unrelated files in `release/` cannot
leak into the published checksum manifest. The build stops before packaging if
the test suite fails.

## Test

The test suite uses Python's standard library and does not need extra test
dependencies:

```powershell
python -m unittest discover -s tests -v
```

The tests cover Open-Meteo payload validation and retry behavior, formatting and
time-window logic, settings persistence, redirected Windows shortcut paths, Git
update safety, release and installer invariants, all mapped WMO weather codes,
tray rendering, icon source pairs, PNG transparency, and the PyInstaller asset
manifest.

## Bundled Assets

Weather Report ships with its own transparent PNG/SVG weather icon set under
`assets/weather-icons/`. The Tkinter UI alpha-trims and scales these assets for
the compact card, forecast panel, and Windows tray icon.

Metric row icons live under `assets/metric-icons/` and use the same visual style
for rain amount, rain probability, humidity/fog, and wind indicators.

The app also bundles the Exo 2 font under `assets/fonts/` and registers it as a
private runtime font on Windows. Users do not need to install the font manually.

## Publish A Release

Install GitHub CLI once and sign in:

```powershell
winget install --id GitHub.cli
gh auth login
```

Publish the next patch release automatically, for example `v0.1.0` -> `v0.1.1`:

```powershell
powershell -ExecutionPolicy Bypass -File .\publish_release.ps1 -SkipInstaller
```

Publish a specific version:

```powershell
powershell -ExecutionPolicy Bypass -File .\publish_release.ps1 -Version v0.1.1 -SkipInstaller
```

The publish script requires a clean `main` branch, builds the portable package,
pushes `main` if needed, creates and pushes a version tag, and
publishes `release/WeatherReport-portable.zip`, `release/SHA256SUMS.txt`, and the
Inno Setup installer when one was built. The release version is also passed into
the Windows installer metadata.

The one-line installer uses the latest GitHub Release and verifies the portable
zip when `SHA256SUMS.txt` is present.

## Settings

User settings are stored under:

```text
%APPDATA%\weather-report\weather_settings.json
```

## Updates

When running from a Git checkout on the `main` branch, the app can check
`origin/main` for updates. The current `origin` remote is
`https://github.com/mikkolaaks0/weather-report.git`. The tray action first
fetches `origin/main`, only applies a fast-forward update to a clean checkout,
asks before updating, and restarts itself after a successful update. Other
branches skip the automatic update path to avoid pulling `main` into local
development work. Source runs also perform the same non-destructive update check
shortly after startup. The check reports the running version and offers a restart
when the checkout has already changed while the app was open.

The packaged `WeatherReport.exe` does not update itself with Git. Install the
latest packaged version with `install.ps1`; it queries
`https://api.github.com/repos/mikkolaaks0/weather-report/releases/latest`,
downloads `WeatherReport-portable*.zip`, verifies `SHA256SUMS.txt` when
available, and replaces the installed package. The app's tray update action is
therefore available only when running from a Git checkout.

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
