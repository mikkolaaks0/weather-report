#define AppName "Weather Report"
#ifndef AppVersion
#define AppVersion "0.1.1"
#endif
#define AppPublisher "Weather Report"
#define AppExeName "WeatherReport.exe"
#define BuildRoot "dist\\WeatherReport"

[Setup]
AppId={{5B3CCF75-A282-4A5A-82E6-88B877F2A7AE}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=release
OutputBaseFilename=WeatherReport-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startupshortcut"; Description: "Launch {#AppName} when Windows starts"; GroupDescription: "Optional shortcuts:"; Flags: unchecked
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Optional shortcuts:";

[Files]
Source: "{#BuildRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{userstartup}\Weather Report.lnk"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\weather-report"; Filename: "{app}\{#AppExeName}"; Tasks: startupshortcut

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
