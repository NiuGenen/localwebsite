# Windows 启动脚本：Flask 后端 + Nginx
# 用法：powershell -ExecutionPolicy Bypass -File start.ps1
# 可选：-NginxExe nginx（nginx 可执行文件名或完整路径）

param(
    [string]$NginxExe = "nginx"
)

$ErrorActionPreference = "Stop"

# 项目根目录 = 本脚本的上级目录
$ProjectDir = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Resolve-Path $MyInvocation.MyCommand.Path)))
Set-Location -LiteralPath $ProjectDir

# 依赖路径
$VenvPython = Join-Path $ProjectDir "venv-win\Scripts\python.exe"
$BackendPy  = Join-Path $ProjectDir "backend.py"
$NginxConf  = Join-Path $ProjectDir "nginx.windows.conf"
$LogDir     = Join-Path $ProjectDir "logs"
$TempDir    = Join-Path $ProjectDir "temp"

# 1) 校验 Python/依赖
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Error "未找到虚拟环境: $VenvPython。请先运行: python -m venv venv-win; venv-win\Scripts\pip install -r requirements.txt"
    exit 1
}

# 2) 校验 nginx
$NginxCmd = Get-Command $NginxExe -ErrorAction SilentlyContinue
if (-not $NginxCmd) {
    Write-Error "未找到 nginx 可执行文件: $NginxExe。请安装后重启终端，或用 -NginxExe 指定完整路径。"
    exit 1
}
$NginxBin = $NginxCmd.Source

# 3) 确保目录存在
New-Item -ItemType Directory -Force -Path $LogDir  | Out-Null
New-Item -ItemType Directory -Force -Path $TempDir | Out-Null

# 4) 停止现有进程（若在运行）
& (Join-Path $PSScriptRoot "stop.ps1")

# 5) 启动 Flask 后端
Write-Host "Starting Flask backend on port 5000..."
$FlaskProc = Start-Process -FilePath $VenvPython `
    -ArgumentList "`"$BackendPy`"" `
    -WorkingDirectory $ProjectDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir "flask.log") `
    -RedirectStandardError  (Join-Path $LogDir "flask.err.log") `
    -PassThru
Set-Content -LiteralPath (Join-Path $LogDir "flask.pid") -Value $FlaskProc.Id -Encoding Ascii
Start-Sleep -Seconds 2

# 6) 启动 nginx（-p 设置 prefix，使相对路径生效）
Write-Host "Starting nginx on port 8080..."
$NginxProc = Start-Process -FilePath $NginxBin `
    -ArgumentList "-p `"$ProjectDir\`" -c `"$NginxConf`"" `
    -WorkingDirectory $ProjectDir `
    -WindowStyle Hidden `
    -PassThru
$NginxProc.Id | Set-Content -LiteralPath (Join-Path $LogDir "nginx.pid") -Encoding Ascii

Start-Sleep -Seconds 1

Write-Host ""
Write-Host "Done. Services started."
Write-Host "  本机访问:    http://localhost:8080"
Write-Host "  局域网访问:  http://<本机局域网IP>:8080"
Write-Host "  待办/实用功能/自定义页面管理: http://localhost:8080"
