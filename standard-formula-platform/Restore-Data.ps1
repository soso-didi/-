param([Parameter(Mandatory=$true)][string]$ArchivePath)
$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $ArchivePath)) { throw "找不到备份文件：$ArchivePath" }
$data = Join-Path $PSScriptRoot "data"
$temporary = Join-Path $env:TEMP ("formula-restore-" + [guid]::NewGuid())
Expand-Archive -LiteralPath $ArchivePath -DestinationPath $temporary -Force
$restored = Join-Path $temporary "data"
if (-not (Test-Path -LiteralPath $restored)) { throw "备份格式无效，缺少 data 目录" }
Copy-Item -LiteralPath $restored -Destination $PSScriptRoot -Recurse -Force
Remove-Item -LiteralPath $temporary -Recurse -Force
Write-Output "数据已恢复。请重启平台后使用。"
