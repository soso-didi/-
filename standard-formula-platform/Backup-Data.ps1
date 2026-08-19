param([string]$Destination = (Join-Path $PSScriptRoot "backups"))
$ErrorActionPreference = "Stop"
$data = Join-Path $PSScriptRoot "data"
if (-not (Test-Path -LiteralPath $data)) { throw "数据目录不存在：$data" }
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$archive = Join-Path $Destination "规范公式计算平台-$stamp.zip"
Compress-Archive -LiteralPath $data -DestinationPath $archive -CompressionLevel Optimal
Write-Output "备份已创建：$archive"
