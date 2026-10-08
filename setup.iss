#ifndef AppVersion
  #error Pass /DAppVersion from package.py
#endif
#ifndef BundleDir
  #error Pass /DBundleDir from package.py
#endif
#ifndef ReleaseDir
  #error Pass /DReleaseDir from package.py
#endif

[Setup]
AppId={{4AFCB3BE-FD3A-47BA-96B6-DA48BF55F6AA}
AppName=截图工具 · Screenshot Translator
AppVersion={#AppVersion}
AppPublisher=Wayne
AppPublisherURL=https://github.com/waynepan86/screenshot-translator
AppSupportURL=https://github.com/waynepan86/screenshot-translator/issues
DefaultDirName={localappdata}\Programs\ScreenshotTranslator
DefaultGroupName=Screenshot Translator
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#ReleaseDir}
OutputBaseFilename=ScreenshotTranslator-{#AppVersion}-Setup
SetupIconFile=app.ico
UninstallDisplayIcon={app}\ScreenshotTranslator.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes
UninstallDisplayName=Screenshot Translator

[Languages]
Name: "chinesesimplified"; MessagesFile: "installer\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "portable.flag,data\*,config.json,*.log"

[Icons]
Name: "{autoprograms}\Screenshot Translator"; Filename: "{app}\ScreenshotTranslator.exe"
Name: "{autodesktop}\Screenshot Translator"; Filename: "{app}\ScreenshotTranslator.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ScreenshotTranslator.exe"; Description: "启动 Screenshot Translator"; Flags: nowait postinstall skipifsilent

; User configuration in LocalAppData is retained on uninstall.
[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  StartupCommand: String;
begin
  if CurUninstallStep = usUninstall then
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run',
        'LightweightScreenshotTool', StartupCommand) then
      if CompareText(StartupCommand, '"' + ExpandConstant('{app}\ScreenshotTranslator.exe') + '"') = 0 then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'LightweightScreenshotTool');
end;
