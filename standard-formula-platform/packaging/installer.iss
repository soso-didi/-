; 使用 Inno Setup 编译。运行时、data 与 frontend 会随安装包复制。
[Setup]
AppName=规范公式计算平台
AppVersion=1.0.0
DefaultDirName=D:\规范公式计算平台
DisableProgramGroupPage=yes
OutputBaseFilename=规范公式计算平台-安装包

[Files]
Source: "..\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs; Excludes: "tests\*,__pycache__\*,logs\*,data\platform.sqlite"

[Icons]
Name: "{autodesktop}\规范公式计算平台"; Filename: "{app}\0-启动规范公式计算平台.cmd"

[Run]
Filename: "{app}\0-启动规范公式计算平台.cmd"; Description: "启动规范公式计算平台"; Flags: nowait postinstall skipifsilent
