#define AppName "Weather Report"
#define AppVersion "0.1.0"
#define AppPublisher "Weather Report"
#define AppExeName "WeatherReport.exe"
#define BuildRoot "dist\\WeatherReport"

[Setup]
AppId={{5B3CCF75-A282-4A5A-82E6-88B877F2A7AE}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=release
OutputBaseFilename=WeatherReport-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startupshortcut"; Description: "Launch {#AppName} when Windows starts"; GroupDescription: "Optional shortcuts:";
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Optional shortcuts:";

[Files]
Source: "{#BuildRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startupshortcut

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
