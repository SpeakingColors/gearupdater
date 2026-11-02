; Windows installer + uninstaller (Inno Setup) for the updater. Called as: ISCC /DVersion=0.1.0 packaging/windows.iss
; Expects the PyInstaller folder in ..\dist\Studio87Updater and the manual in ..\stage. Works offline.
; The uninstaller removes everything it installed. The updater's own settings and installed-versions list
; (%APPDATA%\Studio 87\Updater) are kept unless you answer Yes; a silent uninstall always keeps them.
[Setup]
AppId={{6F1D3C52-8B7A-4E0D-A2C9-5B14E7D0A9F3}
AppName=Studio 87 Updater
AppVersion={#Version}
AppPublisher=Studio 87
AppPublisherURL=https://github.com/SpeakingColors/gearupdater
DefaultDirName={autopf}\Studio 87\Updater
DefaultGroupName=Studio 87
OutputDir=..\Output
OutputBaseFilename=Studio87-Updater-Setup
LicenseFile=..\LICENSE
SetupIconFile=..\studio87_updater\assets\icon.ico
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
UninstallDisplayName=Studio 87 Updater
UninstallDisplayIcon={app}\icon.ico
CloseApplications=yes
DisableProgramGroupPage=yes

[Messages]
SelectDirDesc=Where should the Studio 87 Updater be installed?
SelectDirLabel3=The app, its manual and the uninstaller go into this folder. The plugins it updates go to their own places (for example C:\Program Files\Common Files\VST3).
SelectDirBrowseLabel=To continue, click Next. Choose another folder only if you want the app somewhere else.

[Files]
Source: "..\dist\Studio87Updater\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\stage\Studio87-Updater-manual.pdf"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\studio87_updater\assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Studio 87 Updater"; Filename: "{app}\Studio87Updater.exe"; IconFilename: "{app}\icon.ico"
Name: "{group}\Studio 87 Updater manual"; Filename: "{app}\Studio87-Updater-manual.pdf"; IconFilename: "{app}\icon.ico"
Name: "{group}\Uninstall Studio 87 Updater"; Filename: "{uninstallexe}"; IconFilename: "{app}\icon.ico"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  data, vendor: String;
begin
  if CurUninstallStep <> usPostUninstall then exit;
  data := ExpandConstant('{userappdata}\Studio 87\Updater');
  vendor := ExpandConstant('{userappdata}\Studio 87');
  if DirExists(data) and (not UninstallSilent) then
    if MsgBox('Also delete the updater''s settings and its list of installed versions?' + #13#10 + #13#10 + data + #13#10 + #13#10 +
              'Choose No to keep them (recommended if you plan to reinstall). Your plugins and presets are never touched.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(data, True, True, True);
  RemoveDir(vendor);   { only succeeds when empty }
end;
