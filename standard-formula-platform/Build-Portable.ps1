$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$frontend = Join-Path $root "frontend"
$distIndex = Join-Path $frontend "dist\index.html"
if (-not (Test-Path -LiteralPath $distIndex)) {
  $node = 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
  if (-not (Test-Path -LiteralPath $node)) { throw "缺少已构建前端且构建机没有 Node.js。" }
  Push-Location $frontend
  try { & $node .\node_modules\vite\bin\vite.js build; if ($LASTEXITCODE -ne 0) { throw "前端构建失败" } } finally { Pop-Location }
}
$output = Join-Path $root "release"
New-Item -ItemType Directory -Force -Path $output | Out-Null
$archive = Join-Path $output "规范公式计算平台-便携版.zip"
if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
$staging = Join-Path $env:TEMP ("formula-platform-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path $staging | Out-Null
Get-ChildItem -LiteralPath $root -Force | Where-Object Name -notin @("frontend", "release", "logs", "backups") | Copy-Item -Destination $staging -Recurse -Force
robocopy $frontend (Join-Path $staging "frontend") /E /XD node_modules | Out-Null
if ($LASTEXITCODE -gt 7) { throw "复制前端文件失败，robocopy 返回 $LASTEXITCODE" }
Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $archive -CompressionLevel Optimal
Remove-Item -LiteralPath $staging -Recurse -Force
Write-Output "便携包已生成：$archive"
