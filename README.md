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
- City autocomplete with up to five location suggestions and saved coordinates
- Enter or Hae confirms the top suggestion; arrow keys choose another match
- The latest submitted city search takes precedence, including its exact location
- Background refreshes preserve the city being edited and the highlighted suggestion
- Temperature, daily high/low, precipitation, humidity, wind, sunrise and sunset
- Near-term precipitation probability based on the next 6 hours
- Hourly rain probabilities follow Open-Meteo's preceding-hour timestamps,
  including partially overlapping hours at the edges of that window
- Automatic weather refresh every 30 minutes
- Failed refreshes are marked on the popup while keeping the last valid forecast
- Network failures during a city change retry the selected location, not the old city
- Daily metrics and forecast days follow the location's date, including across midnight
- Optional startup shortcut for Windows login, updated without blocking the popup
- Desktop shortcut creation from the tray, also without blocking the popup
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
Downloads have time limits, and the installer stops only the executable inside
the installation being replaced. The old startup shortcut is removed only after
the replacement has been saved successfully.
Core Python/Tk runtime files are checked before stopping the current app. If an
installation step fails after replacement, recovery restores the previous app
directory and the original desktop, Start Menu, and startup shortcuts, including
removing shortcuts that were created by the failed attempt. Recovery errors are
reported rather than treated as a successful installation.
When launching is enabled, the installer watches for an immediate exit of the
new app for 1.5 seconds before removing the previous version's backup. An early
exit triggers the same recovery path; this is a startup check, not a full health
check of the running app.

To uninstall the portable install:

```powershell
irm https://raw.githubusercontent.com/mikkolaaks0/weather-report/main/uninstall.ps1 | iex
```

Add `-RemoveSettings` when running a downloaded `uninstall.ps1` file if you also
want to remove saved settings.
The uninstaller leaves processes and shortcuts belonging to other installations
alone. Settings are shared by the user's installations, so `-RemoveSettings`
also resets their saved preferences.

## Run From Source

Location suggestions appear after a brief typing pause (two characters for exact
names, three or more for prefixes). Enter and Hae use the same selection: the
highlighted result, initially the first one. Pressing Enter before suggestions
arrive waits for the current query's first result. Confirmation finishes editing
and removes keyboard focus from the city field. Escape dismisses suggestions;
another Escape hides the popup. If suggestions are unavailable, confirmation
falls back to the regular name search. Selected coordinates are remembered across
refreshes and restarts, so same-named cities do not silently change location.
After confirmation, switching windows or hiding the popup does not cancel the
search or let its completion steal keyboard focus. Escape or editing the query
still cancels a pending suggestion selection. If a confirmed location's weather
request fails temporarily, refresh retries that location while keeping the last
good forecast visible. A name that cannot be found leaves refresh targeting the
previous location until another search is submitted.
Coordinates resolved by a regular name search are also retained for retries if
the following weather request fails; successful geocoding is not repeated.
Suggestions use the existing Open-Meteo geocoding service, with no location
permission or additional dependencies. See its [matching rules](https://open-meteo.com/en/docs/geocoding-api).

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
The launcher first checks the project's `.venv\Scripts\pythonw.exe`, then falls
back to installed Python interpreters. Candidates must provide Python 3.10+ and
Tkinter. If no usable interpreter can be started, the windowless launcher shows
an error instead of silently disappearing. It does not install dependencies or
change the selected Python environment.
The local `.venv` is excluded from Git status so installing its dependencies does
not block source updates.
The app replaces startup and desktop shortcuts atomically: an interrupted write
keeps the previous working link intact.

## Build

Create a portable release package:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1 -Version 0.1.2 -SkipInstaller
```

Create a portable package and an installer, when Inno Setup is installed:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_release.ps1 -Version 0.1.2
```

Release artifacts are written to `release/`. `SHA256SUMS.txt` contains only the
artifacts produced by the current build, so unrelated files in `release/` cannot
leak into the published checksum manifest. The build stops before packaging if
the test suite fails.

`app_metadata.json` is the single source for the app version and release date.
Without `-Version`, the build uses its version; an explicit version must match.
The same version is embedded in the executable's Windows FileVersion and
ProductVersion fields and passed to Inno Setup. Build the installer through
`build_release.ps1`, which supplies the required Inno Setup version definition.
The popup footer continues to display only the release date.

## Test

The test suite uses Python's standard library and does not need extra test
dependencies:

```powershell
python -m unittest discover -s tests -v
```

Coverage includes:

- Weather payloads, bounded network retries, closed HTTP error responses,
  local-date alignment, precipitation windows, and all mapped WMO codes.
- Autocomplete selection, Enter/Escape bindings, focus changes, superseded
  responses, exact-location persistence, and retry targets after failures.
- Hidden Tk rendering, icon dimensions and transparency, tray failures and
  tooltip limits, background-worker failures, and timer replacement/cleanup.
- Atomic settings and shortcut writes, redirected Windows folders, installer
  rollback, early-exit detection, and source-launcher interpreter selection.
- Git fast-forward/conflict handling, restart detection, inherited repository
  overrides, Unicode paths, hidden untracked files, and release-source validation.
- Release metadata mismatches, hourly probability boundaries across midnight,
  and the fallback window's requested size when the tray is unavailable.

Windows tests render a hidden popup and inspect temporary `.lnk` files. Git tests
use local repositories without contacting GitHub. Installer and launcher tests
use temporary directories, shortcut snapshots, and an isolated virtualenv with a
short non-UI test program. They do not install the app, launch the user's weather
app, or modify the user's startup settings.

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

Update the version and date in `app_metadata.json`, commit the changes, and
publish that version (the script derives the tag from the metadata):

```powershell
powershell -ExecutionPolicy Bypass -File .\publish_release.ps1 -SkipInstaller
```

Publish a specific version:

```powershell
powershell -ExecutionPolicy Bypass -File .\publish_release.ps1 -Version v0.1.2 -SkipInstaller
```

The publish script requires a clean `main` branch, builds the portable package,
pushes `main` if needed, creates and pushes a version tag, and
publishes `release/WeatherReport-portable.zip`, `release/SHA256SUMS.txt`, and the
Inno Setup installer when one was built. The release version is also passed into
the Windows installer metadata.
Publishing checks that the branch, commit, and working tree did not change during
the build, and tags the exact commit that was built. An explicit `-Version` must
match the application metadata, and existing version tags are never overwritten.
The release script verifies the repository root and refuses inherited
repository-local Git overrides before publishing. Untracked files block release
publishing even when Git is configured to hide them from status output.

The one-line installer uses the latest GitHub Release and verifies the portable
zip when `SHA256SUMS.txt` is present.

## Settings

User settings are stored under:

```text
%APPDATA%\weather-report\weather_settings.json
```

If `APPDATA` is unavailable, the app uses `LOCALAPPDATA`. Invalid settings fields
fall back to defaults, and an unreadable or malformed settings file does not
prevent startup.
Settings are saved atomically: a failed write keeps the previous file intact and
shows one warning per failure episode. Unsaved changes remain active in the
current session and are retried after a successful weather refresh and on exit.

## Updates

When running from a Git checkout on the `main` branch, the app can check
`origin/main` for updates. The current `origin` remote is
`https://github.com/mikkolaaks0/weather-report.git`. The tray action
fetches `origin/main`, only applies a fast-forward update to a clean checkout,
asks before updating, and restarts itself after a successful update. Other
branches skip the automatic update path to avoid pulling `main` into local
development work. Source runs also perform the same non-destructive update check
shortly after startup. The check reports the running version and offers a restart
when the checkout has already changed while the app was open.
Manual checks cancel the pending startup check, so the same update is not
offered again seconds later. An early weather request likewise replaces the
startup weather request; each completed request schedules the next refresh.
The updater clears inherited repository-local Git context and reads Git output
as UTF-8, keeping commands scoped to this checkout and supporting international
filenames on Windows. Untracked files remain a reason to skip automatic updates
even when Git's status configuration normally hides them.
That local restart check works without an internet connection. Only one update
can run at a time, including confirmation and restart. In-app restarts reuse the
working Python environment instead of searching for another Python installation.
The current process stays open if the replacement cannot be launched or exits
during the initial 1.5-second startup check; this is an early-exit check, not a
full health check. Update failures are shown in a dialog.

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
