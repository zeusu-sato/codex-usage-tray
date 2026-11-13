[Setup]
AppId={{76F70EFD-4C9D-472F-A3B9-577C640E8424}
AppName=Codex Usage Tray
AppPublisher=zeusu-sato
AppVersion={#AppVersion}
VersionInfoVersion={#NumericVersion}
DefaultDirName={localappdata}\Programs\CodexUsageTray
DisableDirPage=yes
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=CodexUsageTray-Setup-{#AppVersion}
UninstallDisplayIcon={app}\CodexUsageTray.exe
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
#if FileExists(AddBackslash(CompilerPath) + "Languages\Japanese.isl")
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
#else
Name: "japanese"; MessagesFile: "compiler:Default.isl"
#endif

[InstallDelete]
Type: filesandordirs; Name: "{app}\backend"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{userprograms}\Codex Usage Tray"; Filename: "{app}\CodexUsageTray.exe"

[Run]
Filename: "{app}\CodexUsageTray.exe"; Parameters: "{code:LaunchArguments}"; Flags: nowait postinstall; Check: ShouldLaunch

[UninstallDelete]
Type: filesandordirs; Name: "{app}\backend"
Type: filesandordirs; Name: "{app}\docs"
Type: filesandordirs; Name: "{app}\licenses"
Type: filesandordirs; Name: "{app}\macos"
Type: files; Name: "{app}\README.md"
Type: files; Name: "{app}\README.ja.md"
Type: files; Name: "{app}\LICENSE"
Type: files; Name: "{app}\CodexUsageTray.exe"
Type: files; Name: "{app}\CodexUsageTray.ico"
Type: dirifempty; Name: "{app}"

[Code]
function ParameterValue(const Name: String): String;
var I: Integer; S, Prefix: String;
begin
  Result := '';
  Prefix := '/' + Name + '=';
  for I := 1 to ParamCount do begin
    S := ParamStr(I);
    if CompareText(Copy(S, 1, Length(Prefix)), Prefix) = 0 then
      Result := Copy(S, Length(Prefix) + 1, MaxInt);
  end;
end;

function ShouldLaunch: Boolean;
begin
  Result := CompareText(ParameterValue('NOLAUNCH'), '1') <> 0;
end;

function LaunchArguments(Param: String): String;
var DataDir: String;
begin
  Result := '';
  DataDir := ParameterValue('DATADIR');
  if DataDir <> '' then Result := '--tray --data-dir "' + DataDir + '"';
end;

function StopAppProcesses: Boolean;
var WMI, Processes, P: Variant; I, Attempt: Integer; Path, Base, Name: String; Found: Boolean;
begin
  Result := False;
  Base := AddBackslash(ExpandFileName(ExpandConstant('{app}')));
  try
    WMI := CreateOleObject('WbemScripting.SWbemLocator').ConnectServer('.', 'root\cimv2');
    for Attempt := 1 to 100 do begin
      Found := False;
      Processes := WMI.ExecQuery('SELECT * FROM Win32_Process WHERE Name = ''CodexUsageTray.exe'' OR Name = ''CodexUsageBackend.exe''');
      for I := 0 to Processes.Count - 1 do begin
        P := Processes.ItemIndex(I);
        if not VarIsNull(P.ExecutablePath) then begin
          Path := ExpandFileName(P.ExecutablePath);
          Name := ExtractFileName(Path);
          if (CompareText(Copy(Path, 1, Length(Base)), Base) = 0) and
             ((CompareText(Name, 'CodexUsageTray.exe') = 0) or (CompareText(Name, 'CodexUsageBackend.exe') = 0)) then begin
            Found := True;
            if P.Terminate() <> 0 then begin Log('Could not stop ' + Path); exit; end;
          end;
        end;
      end;
      if not Found then begin Result := True; exit; end;
      Sleep(100);
    end;
  except
    Log('Failed to stop application processes: ' + GetExceptionMessage);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not StopAppProcesses then Result := 'Could not stop the installed application.';
end;

function InitializeUninstall(): Boolean;
begin
  Result := StopAppProcesses;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var Shell, Shortcut: Variant; Link: String;
begin
  if CurUninstallStep = usUninstall then begin
    Link := ExpandConstant('{userstartup}\CodexUsageTray-managed.lnk');
    if FileExists(Link) then begin
      try
        Shell := CreateOleObject('WScript.Shell');
        Shortcut := Shell.CreateShortcut(Link);
        if (Shortcut.Description = 'Codex Usage Tray managed startup') and
           (CompareText(ExpandFileName(Shortcut.TargetPath), ExpandFileName(ExpandConstant('{app}\CodexUsageTray.exe'))) = 0) then
          DeleteFile(Link);
      except
        Log('Could not inspect startup shortcut: ' + GetExceptionMessage);
      end;
    end;
  end;
end;
