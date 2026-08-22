; Inno Setup script — installs the TCU Simulator app AND its hardware drivers.
; Build: ISCC.exe installer.iss   (or via build.ps1)
; Requires an elevated install (drivers are a machine-level operation).
;
; Driver payloads are optional at BUILD time (skipifsourcedoesntexist) so the
; installer compiles before you've dropped them in — but they must be present to
; actually install drivers. See drivers\README.md for exactly what to place where.

#define AppName "5EAT TCU Simulator"
#define AppVer  "1.0.0"
#define AppExe  "TCUSimulator.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=5EAT TCU Tools
DefaultDirName={autopf}\TCU Simulator
DefaultGroupName=TCU Simulator
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=dist
OutputBaseFilename=TCUSimulator-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
WizardStyle=modern

[Files]
; the PyInstaller one-folder app
Source: "dist\TCUSimulator\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; bundled driver payloads (optional at build time)
Source: "drivers\*"; DestDir: "{app}\drivers"; Flags: recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
; two shortcuts — the user picks the front door
Name: "{group}\TCU Simulator (App window)"; Filename: "{app}\{#AppExe}"; Parameters: "--shell window"
Name: "{group}\TCU Simulator (Browser)";    Filename: "{app}\{#AppExe}"; Parameters: "--shell browser"
Name: "{autodesktop}\TCU Simulator";        Filename: "{app}\{#AppExe}"; Parameters: "--shell window"; Tasks: desktopicon
Name: "{group}\Uninstall TCU Simulator";    Filename: "{uninstallexe}"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "drv_ftdi";    Description: "Install Tactrix / FTDI serial driver (OpenPort 2.0 on K-line)"; GroupDescription: "Hardware drivers:"
Name: "drv_canable"; Description: "Configure CANtact Pro WinUSB driver via Zadig (CAN bus)";       GroupDescription: "Hardware drivers:"
Name: "drv_webview"; Description: "Install Edge WebView2 runtime (only needed on older Windows)";  GroupDescription: "Hardware drivers:"; Flags: unchecked

[Run]
; FTDI CDM installer (Tactrix serial). Interactive wizard (Extract -> Next -> Finish).
Filename: "{app}\drivers\ftdi\ftdi_setup.exe"; StatusMsg: "Installing FTDI serial driver..."; \
  Flags: waituntilterminated; Tasks: drv_ftdi; Check: DriverPresent('ftdi\ftdi_setup.exe')
; CANtact Pro -> WinUSB via Zadig (official, signed). Interactive: pick the CANtact device,
; choose WinUSB, click Install. The Check pops a one-time instruction first.
Filename: "{app}\drivers\canable\zadig.exe"; StatusMsg: "Configure the CANtact WinUSB driver in Zadig..."; \
  Flags: waituntilterminated; Tasks: drv_canable; Check: ZadigInfoAndPresent
; Edge WebView2 evergreen bootstrapper (silent; no-op if already present)
Filename: "{app}\drivers\webview2\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; \
  StatusMsg: "Installing WebView2 runtime..."; Flags: waituntilterminated; Tasks: drv_webview; \
  Check: DriverPresent('webview2\MicrosoftEdgeWebview2Setup.exe')
; offer to launch after install
Filename: "{app}\{#AppExe}"; Parameters: "--shell window"; Description: "Launch TCU Simulator"; \
  Flags: nowait postinstall skipifsilent

[Code]
function DriverPresent(Rel: String): Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\drivers\') + Rel);
end;

function ZadigInfoAndPresent: Boolean;
begin
  Result := DriverPresent('canable\zadig.exe');
  if Result then
    MsgBox('Zadig will now open to bind the WinUSB driver to the CANtact Pro.'#13#10#13#10 +
           '1) Options menu -> List All Devices'#13#10 +
           '2) select the CANtact Pro in the dropdown'#13#10 +
           '3) choose WinUSB as the target driver'#13#10 +
           '4) click Install Driver, then close Zadig.',
           mbInformation, MB_OK);
end;
