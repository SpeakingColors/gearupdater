; Windows installer + uninstaller (Inno Setup) for the updater. Called as: ISCC /DVersion=0.1.2 packaging/windows.iss
; The app itself never needs administrator rights (no administrator manifest). This installer starts as a normal user and
; lets you choose: for all users (Windows then shows its UAC prompt) or just for you (no prompt). An update installed
; over an older copy keeps the choice made the first time.
; Expects the PyInstaller folder in ..\dist\Studio87GearUpdater and the manual in ..\stage. Works offline.
; The uninstaller removes everything it installed. The updater's own settings and installed-versions list
; (%APPDATA%\Studio 87\Gear Updater) are kept unless you answer Yes; a silent uninstall always keeps them.
[Setup]
AppId={{6F1D3C52-8B7A-4E0D-A2C9-5B14E7D0A9F3}
AppName=Studio 87 Gear Updater
AppVersion={#Version}
AppPublisher=Studio 87
AppPublisherURL=https://github.com/SpeakingColors/gearupdater
DefaultDirName={autopf}\Studio 87\Gear Updater
DefaultGroupName=Studio 87
OutputDir=..\Output
OutputBaseFilename=Studio87-GearUpdater-Setup
LicenseFile=..\LICENSE
SetupIconFile=..\studio87_updater\assets\icon.ico
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
UsePreviousPrivileges=yes
ChangesAssociations=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
UninstallDisplayName=Studio 87 Gear Updater
UninstallDisplayIcon={app}\icon.ico
CloseApplications=yes
DisableProgramGroupPage=yes

[Messages]
SelectDirDesc=Where should the Studio 87 Gear Updater be installed?
SelectDirLabel3=The app, its manual and the uninstaller go into this folder. The plugins it updates go to their own places (for example C:\Program Files\Common Files\VST3).
SelectDirBrowseLabel=To continue, click Next. Choose another folder only if you want the app somewhere else.

[Files]
Source: "..\dist\Studio87GearUpdater\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\stage\Studio87-GearUpdater-manual.pdf"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\studio87_updater\assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Studio 87 Gear Updater"; Filename: "{app}\Studio87GearUpdater.exe"; IconFilename: "{app}\icon.ico"
Name: "{group}\Studio 87 Gear Updater manual"; Filename: "{app}\Studio87-GearUpdater-manual.pdf"; IconFilename: "{app}\icon.ico"
Name: "{group}\Uninstall Studio 87 Gear Updater"; Filename: "{uninstallexe}"; IconFilename: "{app}\icon.ico"

[Registry]
; studio87://open lets a plugin's About page open this updater (docs/plugin-link.md). HKA is HKLM for an all-users install
; and HKCU for a just-for-me install; the uninstaller removes the keys. The link only opens the window, nothing is executed from it.
Root: HKA; Subkey: "Software\Classes\studio87"; ValueType: string; ValueName: ""; ValueData: "URL:Studio 87 Gear Updater"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\studio87"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\studio87\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\Studio87GearUpdater.exe,0"
Root: HKA; Subkey: "Software\Classes\studio87\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Studio87GearUpdater.exe"" ""%1"""

[Run]
; interactive install: an optional "start it" checkbox; silent install (used by the in-app 'Update the updater'): start it again
Filename: "{app}\Studio87GearUpdater.exe"; Description: "Start Studio 87 Gear Updater"; Flags: nowait postinstall skipifsilent
Filename: "{app}\Studio87GearUpdater.exe"; Flags: nowait skipifnotsilent runasoriginaluser

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  data, vendor: String;
begin
  if CurUninstallStep <> usPostUninstall then exit;
  data := ExpandConstant('{userappdata}\Studio 87\Gear Updater');
  vendor := ExpandConstant('{userappdata}\Studio 87');
  if DirExists(data) and (not UninstallSilent) then
    if MsgBox('Also delete the updater''s settings and its list of installed versions?' + #13#10 + #13#10 + data + #13#10 + #13#10 +
              'Choose No to keep them (recommended if you plan to reinstall). Your plugins and presets are never touched.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(data, True, True, True);
  RemoveDir(vendor);   { only succeeds when empty }
end;
