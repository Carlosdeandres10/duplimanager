; DupliManager - Inno Setup installer baseline (Windows)
; Fase siguiente a pre-empaquetado (Fase 1.5)
; Requiere build PyInstaller onedir previo en .\dist\

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#ifndef BuildMode
  ; client | support
  #define BuildMode "client"
#endif

#if BuildMode == "support"
  #define AppName "DupliManager Maintenance (Soporte)"
  #define AppExeName "DupliManagerMaintenance.exe"
  #define DistFolder "..\\dist\\DupliManagerMaintenance"
  #define DefaultDir "{commonappdata}\\DupliManagerSupport"
#else
  #define AppName "DupliManager"
  #define AppExeName "DupliManager.exe"
  #define ServiceExeName "DupliManagerService.exe"
  #define ServiceXmlName "DupliManagerService.xml"
  #define ServiceId "DupliManager"
  #define DistFolder "..\\dist\\DupliManager"
  ; La app escribe config/logs relativos. ProgramData evita problemas de permisos en Program Files.
  #define DefaultDir "{commonappdata}\\DupliManager"
#endif

[Setup]
AppId={{E8C20E7C-2A88-4E48-BDE5-673D1D66A900}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Caisoft
DefaultDirName={#DefaultDir}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=output
OutputBaseFilename=DupliManager-{#BuildMode}-setup-{#AppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
DisableProgramGroupPage=yes
ChangesEnvironment=no
CloseApplications=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
#if BuildMode != "support"
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked
Name: "installservice"; Description: "Instalar y arrancar servicio Windows de DupliManager (recomendado)"; GroupDescription: "Servicio:"; Flags: checkedonce
#endif

[Dirs]
; Asegurar estructura para primera ejecución / upgrades.
Name: "{app}"
Name: "{app}\config"
Name: "{app}\logs"
Name: "{app}\bin"

[Files]
; Copiar build onedir completo.
Source: "{#DistFolder}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "server.log"
; Manuales locales (HTML + docs de referencia)
Source: "..\docs.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\*"; DestDir: "{app}\docs"; Flags: recursesubdirs createallsubdirs ignoreversion
#if BuildMode != "support"
; WinSW (Windows Service Wrapper) y XML de servicio para modo cliente.
Source: "vendor\winsw\WinSW-x64.exe"; DestDir: "{app}"; DestName: "{#ServiceExeName}"; Flags: ignoreversion
Source: "winsw\DupliManagerService.xml"; DestDir: "{app}"; DestName: "{#ServiceXmlName}"; Flags: ignoreversion
#endif

[Icons]
#if BuildMode != "support"
Name: "{group}\Abrir panel DupliManager"; Filename: "http://127.0.0.1:8500"
Name: "{group}\Manual de usuario"; Filename: "{app}\docs\user-manual.html"
Name: "{group}\DupliManager (modo consola)"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Abrir carpeta de instalación"; Filename: "{app}"
Name: "{autodesktop}\DupliManager"; Filename: "http://127.0.0.1:8500"; Tasks: desktopicon
#else
Name: "{group}\CLI mantenimiento (Soporte)"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Manual de usuario"; Filename: "{app}\docs\user-manual.html"
Name: "{group}\Abrir carpeta de instalación"; Filename: "{app}"
#endif

[Run]
#if BuildMode != "support"
Filename: "{app}\{#ServiceExeName}"; Parameters: "install"; Description: "Registrar servicio Windows"; Flags: runhidden waituntilterminated skipifsilent; Tasks: installservice
Filename: "{app}\{#ServiceExeName}"; Parameters: "start"; Description: "Arrancar servicio Windows"; Flags: runhidden waituntilterminated skipifsilent; Tasks: installservice
Filename: "http://127.0.0.1:8500"; Description: "Abrir panel DupliManager en el navegador"; Flags: shellexec postinstall skipifsilent
#endif

[UninstallRun]
#if BuildMode != "support"
Filename: "{app}\{#ServiceExeName}"; Parameters: "stop"; Flags: runhidden waituntilterminated; Check: ServiceWrapperExists
Filename: "{app}\{#ServiceExeName}"; Parameters: "uninstall"; Flags: runhidden waituntilterminated; Check: ServiceWrapperExists
#endif

[UninstallDelete]
; Higiene. No borrar config/logs para permitir reinstalación/upgrade sin pérdida accidental.
; Se elimina solo el log monolítico legado si existe.
Type: files; Name: "{app}\server.log"

[Code]
#if BuildMode != "support"
function ServiceWrapperExists(): Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\{#ServiceExeName}'));
end;

procedure StopServiceBestEffort();
var
  ResultCode: Integer;
  ServiceExe: string;
begin
  // En upgrade, intenta parar antes de sobrescribir binarios.
  ServiceExe := ExpandConstant('{app}\{#ServiceExeName}');
  if FileExists(ServiceExe) then begin
    Exec(ServiceExe, 'stop', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end
  else begin
    Exec(ExpandConstant('{sys}\sc.exe'), 'stop {#ServiceId}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  StopServiceBestEffort();
end;
#endif
