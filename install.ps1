# 微信文件归类 skill 一键安装（含自检）
# Windows PowerShell
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillSrc  = Join-Path $ScriptDir "wechat-file-organizer"

# 选 Python：优先 managed python，其次系统 python
$HomeDir = $env:USERPROFILE
$MBPy = Join-Path $HomeDir ".workbuddy\binaries\python\versions\3.13.12\python.exe"
if (Test-Path $MBPy) { $Py = $MBPy }
else { $Py = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $Py) { Write-Error "未找到 Python，请先安装 Python 3.8+"; exit 1 }

$DestParent = if ($env:WORKBUDDY_SKILLS_DIR) { $env:WORKBUDDY_SKILLS_DIR }
              else { Join-Path $HomeDir ".workbuddy\skills" }
$Dest = Join-Path $DestParent "wechat-file-organizer"

New-Item -ItemType Directory -Force -Path $DestParent | Out-Null
if (Test-Path $Dest) {
  $stamp = Get-Date -Format "yyyyMMddHHmmss"
  $backup = Join-Path $HomeDir ".workbuddy\skill-backups\wechat-file-organizer.$stamp"
  New-Item -ItemType Directory -Force -Path (Split-Path $backup) | Out-Null
  Move-Item -Path $Dest -Destination $backup
  Write-Host "已备份旧版本到: $backup"
}

Copy-Item -Path $SkillSrc -Destination $Dest -Recurse -Force
Write-Host "已安装到: $Dest"

# 自检
& $Py -u (Join-Path $Dest "scripts\organize.py") --help > $null 2>&1
if ($LASTEXITCODE -eq 0) { Write-Host "自检通过：脚本可正常运行" }
else { Write-Host "自检失败，请检查 Python 环境"; exit 1 }
