; Inno Setup 6.1+ script for Audiobook-MCP.
; Build:  ISCC.exe installer\Audiobook-MCP.iss   ->   installer\Output\Audiobook-MCP-Setup-<version>.exe
;
; The installer itself is small. At install time it creates a Python 3.12 virtual environment and downloads
; the voice models (SHA-256 verified), so the machine must be online.
;
; Silent install (all optional pieces can be set on the command line):
;   Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /DIR="C:\Tools\Audiobook-MCP" /COMPONENTS="core,english,german"
;             /ACCEL=auto|cuda|cpu /MCPCLIENTS=none|auto|claude-desktop,cursor,...
;             /SKILLS=none|all|pdf-to-mp3,text-to-mp3  /SKILLTARGETS=none|all|export,claude-code

#define MyAppName "Audiobook-MCP"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "Jan Philipp Drude"
#define MyAppURL "https://github.com/jpdrude/Audiobook-MCP"

[Setup]
AppId={{B6D4C1E2-5A3F-4E7B-9C18-2F0A7D6E4B91}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
OutputDir=Output
OutputBaseFilename=Audiobook-MCP-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayName={#MyAppName}
SetupLogging=yes

[Messages]
FinishedLabel=Setup has finished installing [name] on your computer.%n%nRestart any AI app you added the MCP server to. Claude Desktop must be quit completely (tray icon > Quit) and started again.

[Types]
Name: "full"; Description: "English and German voices"
Name: "custom"; Description: "Custom"; Flags: iscustom

[Components]
Name: "core"; Description: "MCP server, renderer and Python environment"; Types: full custom; Flags: fixed
Name: "english"; Description: "English voices (Kokoro, about 350 MB download)"; Types: full custom
Name: "german"; Description: "German voice (Martin, about 330 MB download)"; Types: full custom

[Files]
Source: "..\kokoro_mcp.py"; DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "..\render_book.py"; DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "..\german_prep.py"; DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "..\render_book.bat"; DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "..\claude_skills\*.skill"; DestDir: "{app}\claude_skills"; Flags: ignoreversion; Components: core
Source: "register_clients.py"; DestDir: "{app}\installer"; Flags: ignoreversion; Components: core
Source: "install_skills.py"; DestDir: "{app}\installer"; Flags: ignoreversion; Components: core
Source: "extract_ffmpeg.py"; DestDir: "{app}\installer"; Flags: ignoreversion; Components: core
Source: "requirements-*.txt"; DestDir: "{app}\installer"; Flags: ignoreversion; Components: core

[Icons]
Name: "{group}\Render a book to MP3"; Filename: "{app}\render_book.bat"; WorkingDir: "{app}"
Name: "{group}\README"; Filename: "{app}\README.md"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\skills"; Description: "Open the folder with the exported skill packages"; Flags: postinstall shellexec skipifsilent; Check: ExportedSkills

[UninstallRun]
; These run before the files are removed, so the venv is still there.
Filename: "{app}\.venv\Scripts\python.exe"; Parameters: """{app}\installer\register_clients.py"" remove --state ""{app}\install_state.json"""; Flags: runhidden skipifdoesntexist; RunOnceId: "UnregisterMcp"
Filename: "{app}\.venv\Scripts\python.exe"; Parameters: """{app}\installer\install_skills.py"" remove --state ""{app}\install_state.json"""; Flags: runhidden skipifdoesntexist; RunOnceId: "RemoveSkills"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\ffmpeg"
Type: filesandordirs; Name: "{app}\jobs"
Type: filesandordirs; Name: "{app}\skills"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\installer\__pycache__"
Type: files; Name: "{app}\install_state.json"
Type: files; Name: "{app}\install.log"

[Code]
const
  // Downloads are verified against these SHA-256 values; the Martin URL is pinned to a repo revision.
  KOKORO_URL = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx';
  KOKORO_SHA = '7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5';
  VOICES_URL = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin';
  VOICES_SHA = 'bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d';
  MARTIN_BASE = 'https://huggingface.co/Godelaune/Kokoro-82M-ONNX-German-Martin/resolve/a1cba7fbf0e72fbae38f0a3a48ce0dc8e6077804/';
  MARTIN_ONNX_SHA = 'c302f1d8bc7adf40a842cb550e18c39a5026bdb1afdd29dbb700b501cb49276b';
  MARTIN_VOICES_SHA = '5b9c8553398d7abf67498ce500c186cefaa7b68fed3e3d415da5380670105acd';
  PYTHON_URL = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe';
  PYTHON_SHA = '67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb';
  FFMPEG_URL = 'https://github.com/GyanD/codexffmpeg/releases/download/8.1.1/ffmpeg-8.1.1-essentials_build.zip';
  FFMPEG_SHA = '6f58ce889f59c311410f7d2b18895b33c03456463486f3b1ebc93d97a0f54541';

var
  AccelPage: TInputOptionWizardPage;
  McpPage: TInputOptionWizardPage;
  SkillsPage: TWizardPage;
  McpIds: array of String;
  SkillOld: array[0..2] of String;
  SkillChk: array[0..2] of TNewCheckBox;
  SkillEdit: array[0..2] of TNewEdit;
  ChkExport: TNewCheckBox;
  ChkClaudeCode: TNewCheckBox;
  DownloadPage: TDownloadWizardPage;
  DlUrl, DlName, DlSha: array of String;
  NvidiaMajor: Integer;
  ClaudeCodeFound: Boolean;
  Problems: String;

// ------------------------------------------------------------------ small helpers
function Q(const S: String): String;
begin
  Result := '"' + S + '"';
end;

function ListHas(const List, Item: String): Boolean;
begin
  Result := Pos(',' + Lowercase(Item) + ',', ',' + Lowercase(List) + ',') > 0;
end;

function UserDir(const Sub: String): String;
begin
  Result := ExpandConstant('{%USERPROFILE}') + '\' + Sub;
end;

// Runs a command line through cmd.exe, appending stdout+stderr to the install log.
function RunLogged(const CmdLine: String): Integer;
var
  RC: Integer;
begin
  Log('RUN: ' + CmdLine);
  if not Exec(ExpandConstant('{cmd}'), '/S /C "' + CmdLine + ' >> ' + Q(ExpandConstant('{app}\install.log')) + ' 2>&1"',
              '', SW_HIDE, ewWaitUntilTerminated, RC) then
    RC := -1;
  Log('  -> exit code ' + IntToStr(RC));
  Result := RC;
end;

procedure Status(const S: String);
begin
  WizardForm.StatusLabel.Caption := S;
  WizardForm.FilenameLabel.Caption := '';
  Log('STEP: ' + S);
end;

procedure AddProblem(const S: String);
begin
  Problems := Problems + '- ' + S + #13#10;
  Log('PROBLEM: ' + S);
end;

// ------------------------------------------------------------------ detection
function FindPython: String;
var
  P: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, 'Software\Python\PythonCore\3.12\InstallPath', 'ExecutablePath', P) and FileExists(P) then
    Result := P
  else if RegQueryStringValue(HKLM, 'Software\Python\PythonCore\3.12\InstallPath', 'ExecutablePath', P) and FileExists(P) then
    Result := P;
end;

function FfmpegOnPath: Boolean;
var
  RC: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/S /C "where ffmpeg >nul 2>nul"', '', SW_HIDE, ewWaitUntilTerminated, RC) and (RC = 0);
end;

procedure DetectHardware;
var
  Tmp: String;
  Lines: TArrayOfString;
  RC, P: Integer;
  S: String;
begin
  NvidiaMajor := 0;
  Tmp := ExpandConstant('{tmp}\nvsmi.txt');
  Exec(ExpandConstant('{cmd}'), '/S /C "nvidia-smi --query-gpu=driver_version --format=csv,noheader > ' + Q(Tmp) + ' 2>nul"',
       '', SW_HIDE, ewWaitUntilTerminated, RC);
  if LoadStringsFromFile(Tmp, Lines) and (GetArrayLength(Lines) > 0) then
  begin
    S := Trim(Lines[0]);
    P := Pos('.', S);
    if P > 1 then
      NvidiaMajor := StrToIntDef(Copy(S, 1, P - 1), 0);
  end;
  ClaudeCodeFound := FileExists(UserDir('.local\bin\claude.exe')) or DirExists(UserDir('.claude'));
end;

function IsValidSkillName(const S: String): Boolean;
var
  I: Integer;
  C: Char;
begin
  Result := (Length(S) >= 1) and (Length(S) <= 64) and (S[1] <> '-') and (S[Length(S)] <> '-') and (Pos('--', S) = 0);
  if Result then
    for I := 1 to Length(S) do
    begin
      C := S[I];
      if not (((C >= 'a') and (C <= 'z')) or ((C >= '0') and (C <= '9')) or (C = '-')) then
        Result := False;
    end;
end;

// ------------------------------------------------------------------ selections (also used by the ready page)
function SelectedAccel: String;
begin
  if not (WizardIsComponentSelected('english') or WizardIsComponentSelected('german')) then
    Result := 'cpu'
  else
    if AccelPage.SelectedValueIndex = 0 then
      Result := 'cuda'
    else
      Result := 'cpu';
end;

function SelectedMcpClients: String;
var
  I: Integer;
begin
  Result := '';
  for I := 0 to GetArrayLength(McpIds) - 1 do
    if McpPage.Values[I] then
    begin
      if Result <> '' then Result := Result + ',';
      Result := Result + McpIds[I];
    end;
end;

function SelectedSkillMap: String;
var
  I: Integer;
begin
  Result := '';
  for I := 0 to 2 do
    if SkillChk[I].Checked then
    begin
      if Result <> '' then Result := Result + ',';
      Result := Result + SkillOld[I] + '=' + Trim(SkillEdit[I].Text);
    end;
end;

function ExportedSkills: Boolean;
begin
  Result := (SelectedSkillMap <> '') and ChkExport.Checked;
end;

// ------------------------------------------------------------------ wizard pages
procedure SkillChkClick(Sender: TObject);
var
  I: Integer;
begin
  for I := 0 to 2 do
    SkillEdit[I].Enabled := SkillChk[I].Checked;
end;

procedure BuildSkillsPage;
var
  I, Y: Integer;
  Lbl: TNewStaticText;
begin
  SkillOld[0] := 'pdf-to-mp3';
  SkillOld[1] := 'pdf-to-tts';
  SkillOld[2] := 'text-to-mp3';

  Lbl := TNewStaticText.Create(SkillsPage);
  Lbl.Parent := SkillsPage.Surface;
  Lbl.Left := 0;
  Lbl.Top := 0;
  Lbl.Width := SkillsPage.SurfaceWidth;
  Lbl.AutoSize := False;
  Lbl.WordWrap := True;
  Lbl.Height := ScaleY(44);
  Lbl.Caption := 'These skills are written for Claude (they use Claude''s own tools), so they are only offered for Claude. '
               + 'Tick a skill to install it and change its name if you like (lowercase letters, digits and hyphens). '
               + 'References between the skills are renamed too.';

  Y := ScaleY(52);
  for I := 0 to 2 do
  begin
    SkillChk[I] := TNewCheckBox.Create(SkillsPage);
    SkillChk[I].Parent := SkillsPage.Surface;
    SkillChk[I].Left := 0;
    SkillChk[I].Top := Y;
    SkillChk[I].Width := SkillsPage.SurfaceWidth;
    SkillChk[I].Caption := SkillOld[I];
    SkillChk[I].Checked := True;
    SkillChk[I].OnClick := @SkillChkClick;

    Lbl := TNewStaticText.Create(SkillsPage);
    Lbl.Parent := SkillsPage.Surface;
    Lbl.Left := ScaleX(18);
    Lbl.Top := Y + ScaleY(22);
    Lbl.Caption := 'Install as:';

    SkillEdit[I] := TNewEdit.Create(SkillsPage);
    SkillEdit[I].Parent := SkillsPage.Surface;
    SkillEdit[I].Left := ScaleX(80);
    SkillEdit[I].Top := Y + ScaleY(19);
    SkillEdit[I].Width := ScaleX(240);
    SkillEdit[I].Text := SkillOld[I];
    Y := Y + ScaleY(50);
  end;

  ChkClaudeCode := TNewCheckBox.Create(SkillsPage);
  ChkClaudeCode.Parent := SkillsPage.Surface;
  ChkClaudeCode.Left := 0;
  ChkClaudeCode.Top := Y + ScaleY(4);
  ChkClaudeCode.Width := SkillsPage.SurfaceWidth;
  ChkClaudeCode.Caption := 'Install into Claude Code (~\.claude\skills)';
  ChkClaudeCode.Enabled := ClaudeCodeFound;
  ChkClaudeCode.Checked := ClaudeCodeFound;

  ChkExport := TNewCheckBox.Create(SkillsPage);
  ChkExport.Parent := SkillsPage.Surface;
  ChkExport.Left := 0;
  ChkExport.Top := Y + ScaleY(28);
  ChkExport.Width := SkillsPage.SurfaceWidth;
  ChkExport.Caption := 'Export .skill packages to the install folder (upload them in Claude Desktop / claude.ai under Settings > Skills)';
  ChkExport.Checked := True;
end;

procedure AddClient(const Id, Caption: String; Detected: Boolean);
var
  N: Integer;
begin
  if Detected then
  begin
    N := GetArrayLength(McpIds);
    SetArrayLength(McpIds, N + 1);
    McpIds[N] := Id;
    McpPage.Values[McpPage.Add(Caption)] := True;
  end;
end;

procedure ApplyCommandLine;
var
  V: String;
  I: Integer;
begin
  V := Lowercase(ExpandConstant('{param:ACCEL|auto}'));
  if V = 'cuda' then AccelPage.SelectedValueIndex := 0
  else if V = 'cpu' then AccelPage.SelectedValueIndex := 1;

  V := ExpandConstant('{param:MCPCLIENTS|}');
  if V <> '' then
    for I := 0 to GetArrayLength(McpIds) - 1 do
      McpPage.Values[I] := (Lowercase(V) = 'auto') or ListHas(V, McpIds[I]);

  V := ExpandConstant('{param:SKILLS|}');
  if V <> '' then
    for I := 0 to 2 do
      SkillChk[I].Checked := (Lowercase(V) = 'all') or ListHas(V, SkillOld[I]);

  V := ExpandConstant('{param:SKILLTARGETS|}');
  if V <> '' then
  begin
    ChkExport.Checked := (Lowercase(V) = 'all') or ListHas(V, 'export');
    ChkClaudeCode.Checked := ClaudeCodeFound and ((Lowercase(V) = 'all') or ListHas(V, 'claude-code'));
  end;
  SkillChkClick(nil);
end;

procedure InitializeWizard;
var
  Info: String;
begin
  DetectHardware;

  AccelPage := CreateInputOptionPage(wpSelectComponents, 'Hardware acceleration',
    'How should the voices run?', '', True, False);
  if NvidiaMajor >= 580 then
    Info := 'Detected: NVIDIA driver version ' + IntToStr(NvidiaMajor) + '.x (supports CUDA 13).'
  else if NvidiaMajor > 0 then
    Info := 'Detected: NVIDIA driver version ' + IntToStr(NvidiaMajor) + '.x. CUDA 13 needs driver 580 or newer, so the CPU is preselected.'
  else
    Info := 'No NVIDIA GPU was detected, so the CPU is preselected. (AMD and Intel GPUs are not supported.)';
  AccelPage.SubCaptionLabel.Caption := Info;
  AccelPage.Add('NVIDIA GPU with CUDA - English about 15x, German about 3x faster than real time (about 1.8 GB extra download)');
  AccelPage.Add('CPU only - English about 3x, German only about 1x real time (a 60-minute chapter takes about an hour); no extra download');
  if NvidiaMajor >= 580 then AccelPage.SelectedValueIndex := 0
  else AccelPage.SelectedValueIndex := 1;

  McpPage := CreateInputOptionPage(AccelPage.ID, 'AI apps',
    'Add the MCP server to your AI apps',
    'These apps were found on this computer. A backup of each changed config file is made, and the entry is removed again on uninstall.',
    False, False);
  AddClient('claude-desktop', 'Claude Desktop', DirExists(ExpandConstant('{userappdata}\Claude')));
  AddClient('claude-code', 'Claude Code (user scope)', ClaudeCodeFound);
  AddClient('cursor', 'Cursor', DirExists(UserDir('.cursor')));
  AddClient('vscode', 'VS Code (GitHub Copilot)', DirExists(ExpandConstant('{userappdata}\Code\User')));
  AddClient('windsurf', 'Windsurf', DirExists(UserDir('.codeium\windsurf')));
  AddClient('lmstudio', 'LM Studio', DirExists(UserDir('.lmstudio')));
  AddClient('gemini-cli', 'Gemini CLI', DirExists(UserDir('.gemini')));

  SkillsPage := CreateCustomPage(McpPage.ID, 'Claude skills', 'Install the bundled skills (optional)');
  BuildSkillsPage;

  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), nil);
  ApplyCommandLine;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = AccelPage.ID then
    Result := not (WizardIsComponentSelected('english') or WizardIsComponentSelected('german'))
  else if PageID = McpPage.ID then
    Result := GetArrayLength(McpIds) = 0;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  I, J: Integer;
  N: String;
begin
  Result := True;
  if CurPageID = wpSelectComponents then
  begin
    if not (WizardIsComponentSelected('english') or WizardIsComponentSelected('german')) then
    begin
      MsgBox('Select at least one voice language.', mbError, MB_OK);
      Result := False;
    end;
  end
  else if CurPageID = SkillsPage.ID then
  begin
    for I := 0 to 2 do
      if SkillChk[I].Checked then
      begin
        N := Trim(SkillEdit[I].Text);
        if not IsValidSkillName(N) then
        begin
          MsgBox('"' + N + '" is not a valid skill name. Use lowercase letters, digits and single hyphens (not at the start or end).', mbError, MB_OK);
          Result := False;
          Exit;
        end;
        for J := I + 1 to 2 do
          if SkillChk[J].Checked and (Trim(SkillEdit[J].Text) = N) then
          begin
            MsgBox('Two skills would get the name "' + N + '". Give each skill its own name.', mbError, MB_OK);
            Result := False;
            Exit;
          end;
      end;
    if (SelectedSkillMap <> '') and (not ChkExport.Checked) and (not ChkClaudeCode.Checked) then
    begin
      MsgBox('You ticked skills but no place to put them. Tick "Export" or "Claude Code", or untick the skills.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  S: String;
begin
  S := MemoDirInfo + NewLine + NewLine + MemoComponentsInfo;
  if WizardIsComponentSelected('english') or WizardIsComponentSelected('german') then
    S := S + NewLine + NewLine + 'Acceleration:' + NewLine + Space + SelectedAccel;
  S := S + NewLine + NewLine + 'MCP server will be added to:' + NewLine + Space;
  if SelectedMcpClients = '' then S := S + '(nothing)' else S := S + SelectedMcpClients;
  S := S + NewLine + NewLine + 'Skills:' + NewLine + Space;
  if SelectedSkillMap = '' then S := S + '(none)' else S := S + SelectedSkillMap;
  Result := S;
end;

// ------------------------------------------------------------------ downloads
procedure AddDownload(const Url, Name, Sha: String);
var
  N: Integer;
begin
  N := GetArrayLength(DlUrl);
  SetArrayLength(DlUrl, N + 1);
  SetArrayLength(DlName, N + 1);
  SetArrayLength(DlSha, N + 1);
  DlUrl[N] := Url;
  DlName[N] := Name;
  DlSha[N] := Sha;
end;

procedure AddDownloadUnlessPresent(const Dest, Url, Name, Sha: String);
begin
  if FileExists(Dest) and (CompareText(GetSHA256OfFile(Dest), Sha) = 0) then
    Log('already present and verified: ' + Dest)
  else
    AddDownload(Url, Name, Sha);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  I: Integer;
  App: String;
begin
  Result := '';
  App := ExpandConstant('{app}');
  SetArrayLength(DlUrl, 0);
  SetArrayLength(DlName, 0);
  SetArrayLength(DlSha, 0);

  if WizardIsComponentSelected('english') then
  begin
    AddDownloadUnlessPresent(App + '\models\kokoro-v1.0.onnx', KOKORO_URL, 'kokoro-v1.0.onnx', KOKORO_SHA);
    AddDownloadUnlessPresent(App + '\models\voices-v1.0.bin', VOICES_URL, 'voices-v1.0.bin', VOICES_SHA);
  end;
  if WizardIsComponentSelected('german') then
  begin
    AddDownloadUnlessPresent(App + '\models\kokoro-de-martin\kokoro-martin.onnx', MARTIN_BASE + 'kokoro-martin.onnx',
      'kokoro-martin.onnx', MARTIN_ONNX_SHA);
    AddDownloadUnlessPresent(App + '\models\kokoro-de-martin\voices-martin.npz', MARTIN_BASE + 'voices-martin.npz',
      'voices-martin.npz', MARTIN_VOICES_SHA);
  end;
  if FindPython = '' then
    AddDownload(PYTHON_URL, 'python-3.12.10-amd64.exe', PYTHON_SHA);
  if (not FfmpegOnPath) and (not FileExists(App + '\ffmpeg\bin\ffmpeg.exe')) then
    AddDownload(FFMPEG_URL, 'ffmpeg-8.1.1-essentials_build.zip', FFMPEG_SHA);

  if GetArrayLength(DlUrl) = 0 then Exit;

  if WizardSilent then
  begin
    try
      for I := 0 to GetArrayLength(DlUrl) - 1 do
        DownloadTemporaryFile(DlUrl[I], DlName[I], DlSha[I], nil);
    except
      Result := 'Download failed: ' + GetExceptionMessage;
    end;
  end
  else
  begin
    DownloadPage.Clear;
    for I := 0 to GetArrayLength(DlUrl) - 1 do
      DownloadPage.Add(DlUrl[I], DlName[I], DlSha[I]);
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
      except
        if DownloadPage.AbortedByUser then
          Result := 'Download cancelled.'
        else
          Result := 'Download failed: ' + GetExceptionMessage;
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

// ------------------------------------------------------------------ installation steps
procedure CopyDownloaded(const Name, Dest: String);
begin
  if FileExists(ExpandConstant('{tmp}\') + Name) then
  begin
    ForceDirectories(ExtractFileDir(Dest));
    if not CopyFile(ExpandConstant('{tmp}\') + Name, Dest, False) then
      AddProblem('Could not copy ' + Name + ' to ' + Dest);
  end;
end;

procedure DoPostInstall;
var
  App, PyExe, Venv, Reqs, Accel, Clients, Skills, Args: String;
  Ok: Boolean;
  RC: Integer;
begin
  App := ExpandConstant('{app}');
  Venv := App + '\.venv\Scripts\python.exe';
  Reqs := App + '\installer\';
  Accel := SelectedAccel;
  Ok := True;
  DeleteFile(App + '\install.log');

  Status('Copying voice models ...');
  CopyDownloaded('kokoro-v1.0.onnx', App + '\models\kokoro-v1.0.onnx');
  CopyDownloaded('voices-v1.0.bin', App + '\models\voices-v1.0.bin');
  CopyDownloaded('kokoro-martin.onnx', App + '\models\kokoro-de-martin\kokoro-martin.onnx');
  CopyDownloaded('voices-martin.npz', App + '\models\kokoro-de-martin\voices-martin.npz');

  // --- Python 3.12
  PyExe := FindPython;
  if (PyExe = '') and FileExists(ExpandConstant('{tmp}\python-3.12.10-amd64.exe')) then
  begin
    Status('Installing Python 3.12 (for your user only) ...');
    if not Exec(ExpandConstant('{tmp}\python-3.12.10-amd64.exe'),
                '/quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0 Include_doc=0 Shortcuts=0',
                '', SW_HIDE, ewWaitUntilTerminated, RC) or (RC <> 0) then
      AddProblem('Python installer failed (exit code ' + IntToStr(RC) + ').');
    PyExe := FindPython;
  end;
  if PyExe = '' then
  begin
    AddProblem('Python 3.12 was not found and could not be installed. Install it from python.org, then run this setup again.');
    Ok := False;
  end;

  // --- virtual environment
  if Ok and (not FileExists(Venv)) then
  begin
    Status('Creating the Python environment ...');
    if (RunLogged(Q(PyExe) + ' -m venv ' + Q(App + '\.venv')) <> 0) or (not FileExists(Venv)) then
    begin
      AddProblem('Creating the Python environment failed (see install.log).');
      Ok := False;
    end;
  end;

  // --- packages
  if Ok then
  begin
    Status('Installing Python packages (this can take several minutes) ...');
    Args := Q(Venv) + ' -m pip install --disable-pip-version-check ';
    if RunLogged(Args + '-r ' + Q(Reqs + 'requirements-base.txt')) <> 0 then
    begin
      AddProblem('pip could not install the base packages (see install.log).');
      Ok := False;
    end;
    // Martin (German) runs on kokoro-onnx too, so both voices need it.
    if Ok and (WizardIsComponentSelected('english') or WizardIsComponentSelected('german')) then
      if RunLogged(Args + '-r ' + Q(Reqs + 'requirements-kokoro.txt')) <> 0 then
        AddProblem('pip could not install kokoro-onnx (the voices will not work).');
    if Ok and WizardIsComponentSelected('german') then
      if RunLogged(Args + '-r ' + Q(Reqs + 'requirements-german.txt')) <> 0 then
        AddProblem('pip could not install wordfreq (English terms inside German text will not be detected).');
    if Ok and (Accel <> 'cpu') then
    begin
      Status('Installing GPU support (' + Accel + ') ...');
      RunLogged(Q(Venv) + ' -m pip uninstall -y onnxruntime');
      if RunLogged(Args + '-r ' + Q(Reqs + 'requirements-' + Accel + '.txt')) <> 0 then
      begin
        AddProblem('GPU support (' + Accel + ') could not be installed; falling back to the CPU build.');
        RunLogged(Q(Venv) + ' -m pip uninstall -y onnxruntime-gpu');
        RunLogged(Args + 'onnxruntime==1.31.1');
      end;
    end;
  end;

  // --- ffmpeg
  if Ok and FileExists(ExpandConstant('{tmp}\ffmpeg-8.1.1-essentials_build.zip')) then
  begin
    Status('Unpacking ffmpeg ...');
    if RunLogged(Q(Venv) + ' -I ' + Q(Reqs + 'extract_ffmpeg.py') + ' ' + Q(ExpandConstant('{tmp}\ffmpeg-8.1.1-essentials_build.zip')) + ' ' + Q(App + '\ffmpeg')) <> 0 then
      AddProblem('Could not unpack ffmpeg. Install ffmpeg yourself and put it on PATH.');
  end;

  // --- MCP registration
  Clients := SelectedMcpClients;
  if Ok and (Clients <> '') then
  begin
    Status('Adding the MCP server to your AI apps ...');
    RC := RunLogged(Q(Venv) + ' -I ' + Q(Reqs + 'register_clients.py') + ' add --clients ' + Clients
                    + ' --python ' + Q(Venv) + ' --script ' + Q(App + '\kokoro_mcp.py') + ' --state ' + Q(App + '\install_state.json'));
    if RC <> 0 then
      AddProblem('Not every AI app could be updated (see install.log; lines starting with FAIL). Add the server by hand to those.');
  end;

  // --- skills
  Skills := SelectedSkillMap;
  if Ok and (Skills <> '') then
  begin
    Status('Installing skills ...');
    Args := Q(Venv) + ' -I ' + Q(Reqs + 'install_skills.py') + ' add --src ' + Q(App + '\claude_skills') + ' --skills ' + Q(Skills)
            + ' --state ' + Q(App + '\install_state.json');
    if ChkExport.Checked then Args := Args + ' --export ' + Q(App + '\skills');
    if ChkClaudeCode.Checked then Args := Args + ' --claude-code';
    if RunLogged(Args) <> 0 then
      AddProblem('Some skills were skipped or failed (see install.log; lines starting with SKIP or FAIL).');
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    DoPostInstall
  else if (CurStep = ssDone) and (Problems <> '') then
    SuppressibleMsgBox('Setup finished, but with problems:' + #13#10#13#10 + Problems + #13#10
      + 'Details: ' + ExpandConstant('{app}\install.log'), mbError, MB_OK, IDOK);
end;
