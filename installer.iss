; ==============================================================================
; EVE_IDT — Inno Setup 企业级 Windows 专业安装包编译脚本 (installer.iss)
; 文件说明: Eve_image_dedup_tool
; 核心能力：
; 1. 严格遵循 Windows 64-bit Program Files 标准安装规范与数字签名/卸载向导；
; 2. 100% 完备的中英双语本地化切换 (基于 [CustomMessages])；
; 3. 原生系统级资源管理器右键扩展："使用 EVE_IDT 快速查重此文件夹" / "Quick Deduplicate with EVE_IDT"；
; 4. 开机自启动可选配置（HKCU Run 注册表键）；
; 5. SingleInstanceGuard 内核互斥锁检测（防止覆盖正在运行的程序）；
; 6. 卸载时智能询问是否保留回收暂存区 (staging_trash) 与白名单数据。
; ==============================================================================

#define MyAppName "EVE_IDT"
#define MyAppDisplayName "EVE_IDT"
#define MyAppDescription "Eve_image_dedup_tool"
#define MyAppVersion "4.1.4"
#define MyAppPublisher "EVE_IDT Studio"
#define MyAppURL "https://github.com/YingYiBotime/image-dedup-workbench"
#define MyAppExeName "EVE_IDT.exe"
#define MyAppMutex "Local\EVE_IDT_SingleInstance_Mutex_v4"

[Setup]
; 唯一 GUID 标识符
AppId={{8D4E9F12-6C3B-4E8A-9B1D-7F5A2E3C9D04}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; 纯 64 位现代 Windows 架构
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin

OutputDir=dist_installer
OutputBaseFilename=EVE_IDT_Setup_v{#MyAppVersion}
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppDisplayName} v{#MyAppVersion}

; 高压缩率与现代风格向导
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; 进程互斥锁检测
AppMutex={#MyAppMutex}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
chinesesimplified.TaskDesktopIcon=创建桌面快捷方式
english.TaskDesktopIcon=Create a desktop shortcut

chinesesimplified.GroupShortcuts=快捷方式设置:
english.GroupShortcuts=Shortcut Settings:

chinesesimplified.GroupSystem=系统深度集成:
english.GroupSystem=System Integration:

chinesesimplified.TaskContextMenu=在 Windows 资源管理器右键菜单添加「使用 EVE_IDT 快速查重此文件夹」
english.TaskContextMenu=Add "Quick Deduplicate with EVE_IDT" to Windows Explorer context menu

chinesesimplified.ContextMenuLabel=使用 EVE_IDT 快速查重此文件夹
english.ContextMenuLabel=Quick Deduplicate with EVE_IDT

chinesesimplified.TaskAutoStart=开机自动启动 EVE_IDT
english.TaskAutoStart=Start EVE_IDT automatically on Windows startup

chinesesimplified.UninstallShortcut=卸载 EVE_IDT
english.UninstallShortcut=Uninstall EVE_IDT

chinesesimplified.LaunchApp=立即运行 EVE_IDT (Eve_image_dedup_tool)
english.LaunchApp=Launch EVE_IDT (Eve_image_dedup_tool)

chinesesimplified.UninstallPrompt=是否同时清除 EVE_IDT 的本地回收暂存区 (staging_trash) 与特征缓存？%n%n• 点击「是」：彻底清除所有暂存图片与缓存文件；%n• 点击「否」：保留已删除暂存文件与白名单数据（推荐，方便日后重装使用）。
english.UninstallPrompt=Do you also want to remove local staging trash (staging_trash) and feature caches?%n%n• Click [Yes]: Completely purge all trashed images and cache;%n• Click [No]: Keep staging files and whitelist data (Recommended for future reinstallation).

[Tasks]
Name: "desktopicon"; Description: "{cm:TaskDesktopIcon}"; GroupDescription: "{cm:GroupShortcuts}"; Flags: checkedonce
Name: "contextmenu"; Description: "{cm:TaskContextMenu}"; GroupDescription: "{cm:GroupSystem}"; Flags: checkedonce
Name: "autostart"; Description: "{cm:TaskAutoStart}"; GroupDescription: "{cm:GroupSystem}"; Flags: unchecked

[Files]
Source: "dist_portable\EVE_IDT\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "{#MyAppDescription}"
Name: "{autoprograms}\{#MyAppName}\{cm:UninstallShortcut}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "{#MyAppDescription}"

[Registry]
; 1. 文件夹右键菜单关联 (选中文件夹右键)
Root: HKA; Subkey: "Software\Classes\Directory\shell\EVE_IDT"; ValueType: string; ValueName: ""; ValueData: "{cm:ContextMenuLabel}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\EVE_IDT"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"",0"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\EVE_IDT\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey; Tasks: contextmenu

; 2. 文件夹内部空白处右键菜单关联 (当前目录空白处右键)
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\EVE_IDT"; ValueType: string; ValueName: ""; ValueData: "{cm:ContextMenuLabel}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\EVE_IDT"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"",0"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\EVE_IDT\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%V"""; Flags: uninsdeletekey; Tasks: contextmenu

; 3. 开机自启动 (可选)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "EVE_IDT"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[Code]
// 卸载完成时根据用户选择语言友好询问用户是否保留或清理用户数据
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataPrompt: Integer;
  LocalDataDir, RoamingDataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataPrompt := MsgBox(
      CustomMessage('UninstallPrompt'),
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2
    );
    if DataPrompt = IDYES then
    begin
      LocalDataDir := ExpandConstant('{localappdata}\EVE_IDT');
      RoamingDataDir := ExpandConstant('{userappdata}\EVE_IDT');
      DelTree(LocalDataDir, True, True, True);
      DelTree(RoamingDataDir, True, True, True);
    end;
  end;
end;
